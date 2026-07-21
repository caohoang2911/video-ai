"""4-tier visual acquisition: stock VIDEO -> stock photo -> generated still -> fallback generator.
The generated-still tier runs fal.ai FLUX.1-dev by default (higher quality) with local SDXL as the
offline fallback; IMAGE_GEN_BACKEND="sdxl" swaps the order (SDXL first). Historically the note below
read "local SDXL -> fal.ai" (SDXL was primary); the tier order is now backend-driven.

Motion b-roll is tried FIRST so the video reads as documentary footage, not a static slideshow
(the "AI slop" signature). Where maritime footage is scarce it falls back to a stock photo
(Ken Burns later), then to generated stills for beats stock can't serve well (maps, diagrams,
reenactments). Generated images are graded in batches so a run doesn't drift in style from one
beat to the next. The motion-vs-still ratio is logged per video against a target -- footage
scarcity for obscure wrecks is expected, not an error.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import requests

from .. import checkpoint
from ..assembler.beat_timing import compute_beat_durations
from ..assembler.ffmpeg_encode import probe_duration
from ..config import OUTPUT_DIR, settings
from ..db.engine import SessionLocal
from ..db.models import Video
from ..logging_setup import get_logger
from . import asset_store, clip_reranker, cloud_flux, local_sdxl, stock_clients

log = get_logger("visual_fetcher")

STEP = "visual_fetch"
_MAP_DIAGRAM_HINTS = ("map", "diagram", "chart", "route", "schematic", "illustration", "reenact", "blueprint")
STOCK_TIMEOUT_SEC = 5
STOCK_VIDEO_TIMEOUT_SEC = 8   # video search returns more metadata than photo search
# Local SDXL runs fp32 on Apple-Silicon MPS (fp16 NaNs to black frames): ~90-120s/image idle,
# but up to ~5min/image under load (thermal/memory pressure, gen-all's 10 back-to-back images).
# The worker pool waits for completion on exit regardless, so a too-tight bound just DISCARDS a
# finished image and drops the beat to a (rate-limited) stock fallback -- keep it generous.
LOCAL_GEN_TIMEOUT_SEC = 600
# fal FLUX.1-dev returns in ~3-6s idle, but the hosted queue can spike under load. As the PRIMARY
# generator now (not a rare fallback), give it room before dropping a beat to the slow local
# SDXL fallback -- a premature timeout trades a 60s wait for a multi-minute local render.
FAL_TIMEOUT_SEC = 60
COHERENCE_BATCH_SIZE = 10
COHERENCE_MIN_RATIO = 0.8
MOTION_TARGET_RATIO = 0.5     # aim for >=50% of beats on real footage; below this is logged, not failed
# A long beat gets several DISTINCT clips (montage) instead of one short clip looped over and over:
# one clip per ~TARGET_CLIP_SEC of screen time, capped so a single beat can't drain the search.
TARGET_CLIP_SEC = 12.0
MAX_CLIPS_PER_BEAT = 4


@dataclass
class _GeneratedItem:
    beat_id: int
    keywords: list[str]
    mood: str
    is_diagram: bool
    source: str
    path: Path
    image_prompt: str = ""  # scene description from the script; regen must reuse it


def _is_diagram_beat(beat: dict) -> bool:
    haystack = " ".join(beat.get("keywords", [])).lower() + " " + beat.get("mood", "").lower()
    return any(hint in haystack for hint in _MAP_DIAGRAM_HINTS)


def _run_with_timeout(fn, timeout_sec: float, *args, **kwargs):
    """Local SDXL/fal calls are synchronous; bound their wall-clock time with a worker thread.
    On timeout the worker is ABANDONED (`shutdown(wait=False)`), NOT joined, so `timeout_sec` is
    a real deadline -- a stuck fal hosted-queue drops to the next tier after the bound instead of
    hanging the beat. (A `with ThreadPoolExecutor()` block would `shutdown(wait=True)` on exit and
    block until the worker finished, defeating the timeout.) Abandoning is safe: both tiers are
    idempotent single-image generations with no shared state -- a late worker just writes an orphan
    temp file the caller never reads."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn, *args, **kwargs).result(timeout=timeout_sec)
    finally:
        pool.shutdown(wait=False)


def _gather_candidates(query: str, pexels_fn, pixabay_fn, timeout: float) -> list[dict]:
    """Both providers concurrently -> deduped {"url","thumb","source"} candidates (Pexels first).
    Shared by the photo + video paths; [] if both come back empty or the gather times out."""
    async def _gather():
        loop = asyncio.get_event_loop()
        pex = loop.run_in_executor(None, pexels_fn, query)
        pix = loop.run_in_executor(None, pixabay_fn, query)
        return await asyncio.wait_for(asyncio.gather(pex, pix), timeout=timeout)

    try:
        pex_hits, pix_hits = asyncio.run(_gather())
    except Exception as exc:
        log.warning("stock fetch timed out/failed for %r: %s", query, exc)
        return []
    seen: set[str] = set()
    out: list[dict] = []
    for hit, src in [(h, "pexels") for h in pex_hits] + [(h, "pixabay") for h in pix_hits]:
        if hit["url"] in seen:
            continue
        seen.add(hit["url"])
        out.append({**hit, "source": src})
    return out


def _download_thumb(url: str, dest: Path) -> Path | None:
    """A candidate's small preview, or None. Retries a throttle; gives up on anything else.

    Commons thumbnails live on upload.wikimedia.org, which 429s requests without a descriptive
    User-Agent (Wikimedia UA policy). CLIP reranking pulls MANY thumbs per beat, so a missing UA
    here is the biggest source of archival rate-limiting -- and the beat-match gate then asks for
    the same previews again moments later. Both sibling downloaders (`save_archival`, the Commons
    search) already honour Retry-After; this one used to swallow the throttle into a debug line,
    which read downstream as "no candidate" instead of "ask again in a second".
    """
    if not url:
        return None
    headers = {"User-Agent": stock_clients._COMMONS_UA}
    for attempt in range(_THUMB_RETRIES):
        try:
            r = requests.get(url, timeout=STOCK_TIMEOUT_SEC, headers=headers)
            r.raise_for_status()
            dest.write_bytes(r.content)
            return dest
        except Exception as exc:  # noqa: BLE001 - a missing thumb just drops that candidate from ranking
            throttled = getattr(getattr(exc, "response", None), "status_code", None) == 429
            if throttled and attempt < _THUMB_RETRIES - 1:
                time.sleep(_COMMONS_PACE_SEC * (attempt + 2))
                continue
            log.debug("thumb download failed %s: %s", url, exc)
            return None
    return None


# Rerank only the leading candidates, paced. Wikimedia's file server (upload.wikimedia.org)
# throttles rapid bursts with 429; downloading a thumbnail for every candidate back-to-back
# trips it, and the real archival image download is then refused. The Commons search already
# orders by relevance, so CLIP only needs the top few to pick a winner -- a small cap plus a
# gap between fetches keeps us under the limit.
_RERANK_MAX = 4
_COMMONS_PACE_SEC = 1.2
# How many CLIP-ranked candidates get a beat-match vision call before the beat gives up and
# falls to the tiers below. Each is one metered call per beat, and a candidate the ranker
# buried is not the one that saves the beat.
_BEAT_MATCH_MAX_JUDGED = 3
# Wikimedia throttles preview bursts; one retry that honours the pace turns a transient 429 into
# a candidate instead of a phantom miss.
_THUMB_RETRIES = 2


def _rank_candidates(text: str, candidates: list[dict]) -> list[dict]:
    """Reorder candidates most-relevant-first by CLIP-scoring each preview thumbnail against
    `text`. No-op (original provider order) when CLIP is unavailable, there's nothing to rank,
    or thumbnails can't be fetched -- so relevance ranking only ever helps, never blocks."""
    if len(candidates) <= 1 or not text or not clip_reranker.available():
        return candidates
    head, tail = candidates[:_RERANK_MAX], candidates[_RERANK_MAX:]
    with tempfile.TemporaryDirectory() as td:
        thumbs, ranked_idx = [], []
        for i, c in enumerate(head):
            if i:
                time.sleep(_COMMONS_PACE_SEC)  # pace the burst under Wikimedia's rate limit
            p = _download_thumb(c.get("thumb", ""), Path(td) / f"t{i}.jpg")
            if p is not None:
                thumbs.append(p)
                ranked_idx.append(i)
        if len(thumbs) <= 1:
            return candidates
        order = clip_reranker.rank(text, thumbs)  # indices into thumbs/ranked_idx
        ranked = [head[ranked_idx[o]] for o in order]
        # head candidates whose thumb failed, then the un-reranked tail, keep provider order
        ranked += [head[i] for i in range(len(head)) if i not in ranked_idx] + tail
        return ranked


# Event/topic titles lead with the entity and trail with an angle or hook after a delimiter:
# a colon or pipe ("The Halifax Explosion: A City Erased"), or a spaced dash
# ("Pan Am Flight 103 - Lockerbie"). A spaced dash only — so a hyphenated name like
# "Marie-Antoinette" is never split.
_ENTITY_DELIMITERS = re.compile(r"\s*[:|]\s*|\s+[—–-]{1,2}\s+")


def extract_entity(title: str) -> str:
    """The leading event/subject entity of a title, used to anchor BOTH archive search and the
    thumbnail relevance judgement. Splits on the FIRST delimiter (colon / pipe / spaced dash)
    and takes the segment before it; returns the whole trimmed title when there is no
    delimiter (better than the old ':'-only split, which returned the entire noisy line for a
    dash- or delimiter-free title)."""
    title = (title or "").strip()
    if not title:
        return ""
    return _ENTITY_DELIMITERS.split(title, maxsplit=1)[0].strip()


def _event_era(video_id: int) -> str:
    """The year the story happens in, as a string, or "" when the script never states one.

    A generator draws the present unless told otherwise: asked for "conspiracy theories, ufo
    drawings, vintage newspaper headlines" it produced two men in jeans and nylon backpacks
    watching a saucer, in a story set in 1947. Beat keywords describe a SUBJECT and rarely a
    period, so the year has to be pinned separately. A SHORT carries no `event_year` of its
    own -- it inherits the parent documentary's, the same redirect `_archival_anchor` makes.
    """
    own = _script_year(video_id)
    if own:
        return own                      # a main video states its own year: no DB round-trip
    parent = _parent_id(video_id)
    return _script_year(parent) if parent else ""


def _script_year(video_id: int) -> str:
    script = OUTPUT_DIR / str(video_id) / "script.json"
    if not script.exists():
        return ""
    try:
        return str(json.loads(script.read_text()).get("event_year") or "").strip()
    except Exception as exc:  # noqa: BLE001 - era is a hint; a broken script must not stop visuals
        log.warning("event-era lookup failed for video %s: %s", video_id, exc)
        return ""


def _parent_id(video_id: int) -> int | None:
    try:
        with SessionLocal() as s:
            video = s.get(Video, video_id)
            return video.parent_id if video else None
    except Exception as exc:  # noqa: BLE001 - same best-effort stance as the archival anchor
        log.warning("parent lookup failed for video %s: %s", video_id, exc)
        return None


def _archival_anchor(video_id: int) -> str:
    """Entity phrase anchoring Commons searches. Beat keywords describe VISUALS ("stopped
    clock", "burning ship") -- useless as archive queries; the archive is organized around
    the EVENT, which the topic names ("The Halifax Explosion: ..."). Falls back to the
    video title's pre-colon segment when the topic row is gone.

    A SHORT has no topic row and its title is a hook with the entity after an em-dash
    ("Butter, Cheese, and Ammunition — Lusitania's Manifest, 1915") -- splitting that on
    ':' yields the whole noisy line and Commons misses. Anchor a short on its PARENT's
    clean event title instead."""
    from ..db.models import Topic  # local import: avoids widening module deps for one lookup

    try:
        with SessionLocal() as s:
            video = s.get(Video, video_id)
            if video and video.parent_id:  # short -> anchor on the parent's event title
                video = s.get(Video, video.parent_id)
            topic = s.get(Topic, video.topic_id) if video and video.topic_id else None
            title = (topic.title if topic else (video.title if video else "")) or ""
    except Exception as exc:  # noqa: BLE001 - anchor là gia vị, thiếu nó tier vẫn chạy bằng keywords
        log.warning("archival anchor lookup failed for video %s: %s", video_id, exc)
        return ""
    return extract_entity(title)


def _fetch_archival(
    keywords: list[str], text: str = "", anchor: str = "", used: set[str] | None = None,
    video_id: int | None = None, era: str = "",
) -> dict | None:
    """Most content-relevant Wikimedia Commons ARCHIVAL photo candidate for a beat
    (already license- and resolution-filtered by the client); None when Commons has
    nothing usable -- the caller then falls through to generic stock/generation.
    Query = event anchor + the beat's first keywords, CLIP re-ranked against the beat
    text. `used` carries URLs already taken by earlier beats: anchor-retry gives every
    beat the SAME candidate pool, so without it one photo tops every CLIP ranking, the
    md5 dedup rejects it and beats needlessly fall to generation (the sibling-shorts
    batch_used lesson). "Thật khi có thể, vẽ khi phải"."""
    cands: list[dict] = []
    for label, query in _archival_queries(keywords, anchor, era):
        cands = stock_clients.search_wikimedia_commons(query)
        if cands:
            log.info("archival query %s hit: %r -> %d candidate(s)", label, query, len(cands))
            break
    ranked = _rank_candidates(text, cands)
    if used:
        ranked = [c for c in ranked if c["url"] not in used]
    return _first_beat_relevant(ranked, text, video_id)


def _archival_queries(keywords: list[str], anchor: str, era: str) -> list[tuple[str, str]]:
    """Commons queries to try in order, stopping at the first that returns anything.

    Commons full-text ANDs its terms, so the beat-specific query almost never matches a file
    description and the search has in practice always fallen through to the event name alone.
    That is fine while the event name is also a searchable thing ("The Halifax Explosion" ->
    eight 1917 plates) and useless when it is a poetic one: "Star Dust" returns the Cone Nebula,
    the Helix Nebula, and a motel sign in Reno.

    Pinning the year is what separates the two. Measured: "Star Dust" -> 7 hits, none the
    aircraft; "Star Dust 1947" -> 6 hits led by the actual Avro Lancastrian G-AGWH that
    vanished. "The Halifax Explosion 1917" keeps the same 1917 plates, so the good case is
    untouched. The year rides ahead of the bare anchor for exactly that reason.
    """
    queries = [("anchor+keywords", f"{anchor} {' '.join(keywords[:2])}".strip())]
    if anchor and era:
        queries.append(("anchor+era", f"{anchor} {era}"))
    if anchor:
        queries.append(("anchor", anchor))
    return [(label, q) for label, q in queries if q]


def _first_beat_relevant(ranked: list[dict], text: str, video_id: int | None) -> dict | None:
    """The best-ranked candidate that actually shows what this beat narrates, or None.

    CLIP only ORDERS candidates, it never rejects: the top of an entirely off-beat pool still
    won, so a beat could never fall through to the tiers below. That is how a wicker balloon
    basket and a museum's rusted hull fragment ended up illustrating lines about stopped clocks
    and a judicial inquiry -- Commons is full of museum catalogue photography, and the
    anchor-only retry hands every beat that same pool. Only the top few are judged: each
    judgment is a vision call, and a candidate the ranker buried is not going to be the save.
    Unjudgeable (no backend / quota / outage) degrades to taking the best candidate the gate has
    NOT already turned down, rather than starving the render of real photographs. Two rules keep
    that degradation honest, both learned the hard way:

    A preview that fails to download is not a verdict. It used to `continue`, burning one of the
    judging slots without producing a score, so a Wikimedia throttle (the CLIP rerank burst just
    before this call routinely trips one) emptied the budget and the beat reported a miss -- the
    tier vanished on a transient 429 that predates any judgement.

    And falling back to `ranked[0]` is wrong once `ranked[0]` has been scored BELOW the floor:
    that hands the beat the exact image the gate just rejected. Fail-open may only reach for
    candidates that were never judged."""
    if not ranked:
        return None
    if not text:
        return ranked[0]
    from ..content import llm_client  # lazy: keeps the content package off this import path

    rejected: set[int] = set()
    judged = downloaded = 0
    with tempfile.TemporaryDirectory() as td:
        for i, cand in enumerate(ranked):
            if judged >= _BEAT_MATCH_MAX_JUDGED:
                break
            thumb = _download_thumb(cand.get("thumb", ""), Path(td) / f"m{i}.jpg")
            if thumb is None:  # no preview to look at: not a rejection, and not a spent slot
                continue
            downloaded += 1
            score = llm_client.score_scene_match(text, thumb.read_bytes(), video_id=video_id)
            if score is None:
                log.warning("archival beat-match unjudged -> falling back to the best un-rejected candidate")
                return _first_unrejected(ranked, rejected)
            judged += 1
            log.info("archival beat-match %.2f (min %.2f) img=%s",
                     score, settings.ARCHIVAL_BEAT_MATCH_MIN, cand["url"].rsplit("/", 1)[-1][:60])
            if score >= settings.ARCHIVAL_BEAT_MATCH_MIN:
                return cand
            rejected.add(i)
    if downloaded == 0:  # every preview 404'd/throttled -- the gate never got to look at anything
        log.warning("archival beat-match saw no downloadable preview -> keeping the top candidate un-vetted")
        return ranked[0]
    return None


def _first_unrejected(ranked: list[dict], rejected: set[int]) -> dict | None:
    return next((c for i, c in enumerate(ranked) if i not in rejected), None)


def _fetch_stock(keywords: list[str], text: str = "") -> tuple[str, str] | None:
    """Most content-relevant stock-PHOTO (url, source); None if both providers empty/timeout."""
    cands = _gather_candidates(
        " ".join(keywords[:4]), stock_clients.search_pexels, stock_clients.search_pixabay, STOCK_TIMEOUT_SEC
    )
    if not cands:
        return None
    best = _rank_candidates(text, cands)[0]
    return best["url"], best["source"]


def _fetch_stock_video_list(keywords: list[str], n: int, text: str = "") -> list[tuple[str, str]]:
    """The `n` most content-relevant DISTINCT stock-VIDEO (url, source) for a beat's montage.
    Empty list if both providers come back empty or the search times out."""
    cands = _gather_candidates(
        " ".join(keywords[:4]),
        stock_clients.search_pexels_video, stock_clients.search_pixabay_video, STOCK_VIDEO_TIMEOUT_SEC,
    )
    if not cands:
        return []
    return [(c["url"], c["source"]) for c in _rank_candidates(text, cands)[:n]]


def _estimate_beat_seconds(video_id: int, shot_list: list[dict]) -> list[float]:
    """Seconds each beat will run, to size its montage. Uses the real narration length (same
    split assemble uses) when narration.mp3 exists; 0.0 (=> one clip) when it can't be probed."""
    narration = OUTPUT_DIR / str(video_id) / "narration.mp3"
    if not narration.exists():
        return [0.0] * len(shot_list)
    try:
        return compute_beat_durations(shot_list, probe_duration(narration))
    except Exception as exc:  # noqa: BLE001 - estimate only; fall back to single-clip beats
        log.warning("beat-duration estimate failed (%s) -> one clip per beat", exc)
        return [0.0] * len(shot_list)


def _clips_needed(beat_seconds: float) -> int:
    """One montage clip per ~TARGET_CLIP_SEC of screen time (>=1, capped). 0/unknown -> 1."""
    if beat_seconds <= 0:
        return 1
    return max(1, min(MAX_CLIPS_PER_BEAT, math.ceil(beat_seconds / TARGET_CLIP_SEC)))


def _acquire_broll_clips(
    video_id: int, beat_id: int, keywords: list[str], n_clips: int, text: str = ""
) -> list[dict]:
    """Download + persist up to `n_clips` DISTINCT, content-ranked clips for a beat (md5 dedup
    drops repeats, a bad download/normalize is skipped). Returns saved records (may be fewer)."""
    recs: list[dict] = []
    for url, source in _fetch_stock_video_list(keywords, n_clips, text):
        rec = asset_store.save_video_broll(video_id, beat_id, url, source, index=len(recs))
        if rec is not None:
            recs.append(rec)
    return recs


def _generate_visual(
    beat_id: int, keywords: list[str], mood: str, is_diagram: bool, image_prompt: str = "",
    era: str = "",
) -> tuple[Path, str] | None:
    # Escape hatch for a fast, fully stock-footage (no-generation) render: turns off image
    # generation so every beat resolves to stock (a diagram beat then falls to a stock photo
    # via the last-resort tier instead of a slow render). AI_OPERATOR_DISABLE_SDXL kept as an
    # alias so existing gen-all scripts keep working after the SDXL->fal-primary switch.
    if os.getenv("AI_OPERATOR_DISABLE_IMAGE_GEN") or os.getenv("AI_OPERATOR_DISABLE_SDXL"):
        return None

    # The script's per-beat image_prompt (a written-out scene: subject, era details, mood,
    # composition) draws far closer to the narration than a bag of search keywords.
    prompt = image_prompt.strip() or ", ".join(k for k in keywords if k) or mood
    # A generator defaults to the present day, and a documentary set in 1947 cannot carry a
    # frame of people in jeans and nylon backpacks. Constrain the period ADJECTIVALLY: an
    # earlier wording listed the categories to police -- "clothing, vehicles, technology and
    # architecture of that decade only, no modern vehicles" -- and a diffusion model paints the
    # nouns it is handed. Asked for nothing but "andes mountains, snowy peaks, clouds" it
    # returned two 1940s cars, a village and pedestrians; the same prompt under the wording
    # below returned bare mountains. Naming a noun invites it, and negating one ("no modern
    # vehicles") still names it.
    if era:
        prompt = f"a {era} period scene, historically accurate to {era}, nothing anachronistic. {prompt}"

    # Generator tiers in priority order. fal FLUX.1-dev is the primary generator (faster and
    # higher quality); local SDXL is the offline fallback so a render survives a fal/network
    # outage. Only an explicit IMAGE_GEN_BACKEND="sdxl" flips to SDXL-first (fully-offline/free
    # run, rollback); any other/typo'd value keeps the fal-first default rather than silently
    # dropping fal.
    fal_tier = (cloud_flux.generate, FAL_TIMEOUT_SEC, "fal")
    sdxl_tier = (local_sdxl.generate, LOCAL_GEN_TIMEOUT_SEC, "sdxl")
    sdxl_first = settings.IMAGE_GEN_BACKEND.strip().lower() == "sdxl"
    tiers = [sdxl_tier, fal_tier] if sdxl_first else [fal_tier, sdxl_tier]

    for gen_fn, timeout, label in tiers:
        try:
            t0 = time.monotonic()
            image = _run_with_timeout(gen_fn, timeout, prompt, is_diagram=is_diagram)
            log.info("beat %s: %s generated in %.1fs", beat_id, label, time.monotonic() - t0)
            return image, label
        except Exception as exc:
            log.warning("beat %s: %s generator unavailable/failed: %s", beat_id, label, exc)

    log.error("beat %s: all image generators failed", beat_id)
    return None


def _flush_generated_batch(video_id: int, items: list[_GeneratedItem], era: str = "") -> list[dict]:
    """Grade a batch of generated images for style coherence; regenerate outliers once."""
    paths = [it.path for it in items]
    ratio, outliers = asset_store.grade_batch_coherence(paths)
    if ratio < COHERENCE_MIN_RATIO:
        log.warning("batch coherence %.0f%% < 80%% -- regenerating %d outlier(s)", ratio * 100, len(outliers))
        for idx in outliers:
            it = items[idx]
            regen = _generate_visual(
                it.beat_id, it.keywords, it.mood, it.is_diagram, image_prompt=it.image_prompt, era=era
            )
            if regen is not None:
                items[idx] = _GeneratedItem(
                    it.beat_id, it.keywords, it.mood, it.is_diagram, regen[1], regen[0], it.image_prompt
                )
        ratio, _ = asset_store.grade_batch_coherence([it.path for it in items])
        log.info("post-regen batch coherence %.0f%%", ratio * 100)
    else:
        log.info("batch coherence %.0f%% OK (%d images)", ratio * 100, len(paths))

    return [
        rec for it in items
        if (rec := asset_store.save_generated(video_id, it.beat_id, it.path, it.source)) is not None
    ]


def acquire(
    video_id: int, shot_list: list[dict], stills_only: bool = False, force_generate: bool = False
) -> list[dict]:
    """Resolve >=1 visual per beat (motion b-roll first, then stills) and persist via
    asset_store; idempotent. `stills_only` skips the video tier for cheap/offline runs.
    `force_generate` skips BOTH stock tiers and generates every beat (fal FLUX or SDXL per
    IMAGE_GEN_BACKEND) -- for period/event topics stock can't serve (a modern city clip for a
    1917 harbor), a period-styled illustration tracks the narration better."""
    if checkpoint.is_done(video_id, STEP):
        log.info("video %s: visuals already acquired, skipping", video_id)
        return asset_store.list_assets(video_id)

    saved: list[dict] = []
    pending: list[_GeneratedItem] = []
    motion_beats = 0
    total_beats = 0
    beat_seconds = _estimate_beat_seconds(video_id, shot_list)
    anchor = _archival_anchor(video_id)  # tên sự kiện neo mọi query Commons của video này
    era = _event_era(video_id)  # pins generated stills to the decade the story happens in
    log.info("video %s: archival anchor=%r era=%r", video_id, anchor, era or "unknown")
    archival_used: set[str] = set()  # ảnh đã lấy — beat sau chọn ảnh kế tiếp, không đụng hàng

    for i, beat in enumerate(shot_list):
        total_beats += 1
        beat_id = beat["beat_id"]
        keywords = beat.get("keywords", [])[:4]
        mood = beat.get("mood", "")
        # Two distinct "generate" reasons, split because the archival tier treats them
        # differently: a MAP/diagram beat is genuinely better drawn (SDXL), but an
        # `illustration` beat -- an era-specific scene generic stock can't show -- is
        # exactly where a real period photograph (Commons) beats a painted one.
        is_map = _is_diagram_beat(beat)
        is_illustration = (beat.get("visual_kind") or "").lower() == "illustration"
        is_diagram = is_map or is_illustration  # stock tiers still skip both
        # CLIP relevance text for this beat: its keywords + narration span (what the scene is about).
        text = ", ".join(keywords) + (f". {beat.get('narration_span', '')}" if beat.get("narration_span") else "")

        # Stock tiers are skipped entirely in force_generate mode (SDXL every beat).
        if not force_generate:
            # Tier 1: motion b-roll montage (skipped for illustration/diagram beats -- footage
            # rarely fits them -- and for stills-only runs). A long beat pulls several DISTINCT
            # clips so it isn't one short clip looped; no clip lands -> fall through to stills.
            if not is_diagram and not stills_only:
                broll = _acquire_broll_clips(video_id, beat_id, keywords, _clips_needed(beat_seconds[i]), text)
                if broll:
                    saved.extend(broll)
                    motion_beats += 1
                    continue

            # Tier 2a: archival photo (Wikimedia Commons) -- a real photograph of the actual
            # ship/event beats both generic stock and AI illustration for this niche. Tried
            # for illustration beats TOO (era scenes are archival's home turf); only true
            # map/diagram beats go straight to generation.
            record = None
            if not is_map:
                best = _fetch_archival(keywords, text, anchor, archival_used, video_id, era)
                if best is None:
                    log.info("beat %s: archival MISS (no qualifying Commons candidate)", beat_id)
                else:
                    record = asset_store.save_archival(
                        video_id, beat_id, best["url"],
                        license_short=best["license"], artist=best["artist"],
                        file_page=best["file_page"],
                    )
                    if record is not None:
                        archival_used.add(best["url"])
                    log.info(
                        "beat %s: archival %s — %s (%s)",
                        beat_id, "SAVED" if record else "dup/download-failed",
                        best["url"].rsplit("/", 1)[-1][:70], best["license"],
                    )
            if record is not None:
                saved.append(record)
                continue

            # Tier 2b: stock photo (Ken Burns later) where no footage/archival landed.
            record = None
            if not is_diagram:
                hit = _fetch_stock(keywords, text)
                if hit is not None:
                    record = asset_store.save_stock(video_id, beat_id, hit[0], hit[1])
            if record is not None:
                saved.append(record)
                continue

        # Tier 3/4: generated stills (fal FLUX -> SDXL fallback by default; order per
        # IMAGE_GEN_BACKEND), graded for style coherence in batches.
        generated = _generate_visual(
            beat_id, keywords, mood, is_diagram, image_prompt=beat.get("image_prompt", ""), era=era
        )
        if generated is None:
            # Last resort for ANY beat that reached generation and failed (generator missing,
            # timed out, or a transient stock miss earlier): the assembler needs one frame per
            # beat or it crashes, so try a stock photo rather than leaving the beat blank.
            if (hit := _fetch_stock(keywords, text)) is not None:
                record = asset_store.save_stock(video_id, beat_id, hit[0], hit[1])
                if record is not None:
                    saved.append(record)
                    continue
            # Every tier failed for this beat -> synthesize a neutral still so it is NEVER left
            # blank (a blank beat has no frame and crashes the assembler).
            log.warning("beat %s: all visual tiers failed -> placeholder still (video %s)", beat_id, video_id)
            saved.append(asset_store.save_placeholder(video_id, beat_id))
            continue
        path, source = generated
        pending.append(
            _GeneratedItem(beat_id, keywords, mood, is_diagram, source, path, beat.get("image_prompt", ""))
        )
        if len(pending) >= COHERENCE_BATCH_SIZE:
            saved.extend(_flush_generated_batch(video_id, pending, era))
            pending = []

    if pending:
        saved.extend(_flush_generated_batch(video_id, pending, era))

    _log_motion_ratio(video_id, motion_beats, total_beats)
    checkpoint.write(video_id, STEP, {"count": len(saved), "motion_beats": motion_beats})
    return saved


def _log_motion_ratio(video_id: int, motion_beats: int, total_beats: int) -> None:
    """Log the motion-vs-still ratio; a below-target ratio is expected for obscure wrecks
    (scarce footage), so it's a warning for visibility, never a pipeline failure."""
    if total_beats == 0:
        return
    ratio = motion_beats / total_beats
    if ratio < MOTION_TARGET_RATIO:
        log.warning(
            "video %s: motion b-roll %d/%d beats (%.0f%%) -- below %.0f%% target (footage scarce)",
            video_id, motion_beats, total_beats, ratio * 100, MOTION_TARGET_RATIO * 100,
        )
    else:
        log.info("video %s: motion b-roll %d/%d beats (%.0f%%)", video_id, motion_beats, total_beats, ratio * 100)
