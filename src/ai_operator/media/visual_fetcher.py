"""4-tier visual acquisition: stock VIDEO -> stock photo -> local SDXL -> fal.ai.

Motion b-roll is tried FIRST so the video reads as documentary footage, not a static slideshow
(the "AI slop" signature). Where maritime footage is scarce it falls back to a stock photo
(Ken Burns later), then to generated stills for beats stock can't serve well (maps, diagrams,
reenactments). Generated images are graded in batches so a run doesn't drift in style from one
beat to the next. The motion-vs-still ratio is logged per video against a target -- footage
scarcity for obscure wrecks is expected, not an error.
"""

from __future__ import annotations

import asyncio
import math
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import requests

from .. import checkpoint
from ..assembler.beat_timing import compute_beat_durations
from ..assembler.ffmpeg_encode import probe_duration
from ..config import OUTPUT_DIR
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
SDXL_TIMEOUT_SEC = 600
FAL_TIMEOUT_SEC = 30
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


def _is_diagram_beat(beat: dict) -> bool:
    haystack = " ".join(beat.get("keywords", [])).lower() + " " + beat.get("mood", "").lower()
    return any(hint in haystack for hint in _MAP_DIAGRAM_HINTS)


def _run_with_timeout(fn, timeout_sec: float, *args, **kwargs):
    """Local SDXL/fal calls are synchronous; bound their wall-clock time with a worker thread
    (the timed-out thread is abandoned, not killed -- acceptable since both tiers are idempotent
    single-image generations with no shared state)."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn, *args, **kwargs)
        return future.result(timeout=timeout_sec)


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
    if not url:
        return None
    try:
        r = requests.get(url, timeout=STOCK_TIMEOUT_SEC)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return dest
    except Exception as exc:  # noqa: BLE001 - a missing thumb just drops that candidate from ranking
        log.debug("thumb download failed %s: %s", url, exc)
        return None


def _rank_candidates(text: str, candidates: list[dict]) -> list[dict]:
    """Reorder candidates most-relevant-first by CLIP-scoring each preview thumbnail against
    `text`. No-op (original provider order) when CLIP is unavailable, there's nothing to rank,
    or thumbnails can't be fetched -- so relevance ranking only ever helps, never blocks."""
    if len(candidates) <= 1 or not text or not clip_reranker.available():
        return candidates
    with tempfile.TemporaryDirectory() as td:
        thumbs, ranked_idx = [], []
        for i, c in enumerate(candidates):
            p = _download_thumb(c.get("thumb", ""), Path(td) / f"t{i}.jpg")
            if p is not None:
                thumbs.append(p)
                ranked_idx.append(i)
        if len(thumbs) <= 1:
            return candidates
        order = clip_reranker.rank(text, thumbs)  # indices into thumbs/ranked_idx
        ranked = [candidates[ranked_idx[o]] for o in order]
    # candidates whose thumbnail failed to download stay usable, appended after the ranked ones
    ranked += [c for i, c in enumerate(candidates) if i not in ranked_idx]
    return ranked


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


def _generate_visual(beat_id: int, keywords: list[str], mood: str, is_diagram: bool) -> tuple[Path, str] | None:
    prompt = ", ".join(k for k in keywords if k) or mood

    try:
        t0 = time.monotonic()
        image = _run_with_timeout(local_sdxl.generate, SDXL_TIMEOUT_SEC, prompt, is_diagram=is_diagram)
        log.info("beat %s: sdxl generated in %.1fs", beat_id, time.monotonic() - t0)
        return image, "sdxl"
    except Exception as exc:
        log.warning("beat %s: local sdxl unavailable/timed out: %s -- trying fal.ai", beat_id, exc)

    try:
        t0 = time.monotonic()
        image = _run_with_timeout(cloud_flux.generate, FAL_TIMEOUT_SEC, prompt, is_diagram=is_diagram)
        log.info("beat %s: fal.ai generated in %.1fs", beat_id, time.monotonic() - t0)
        return image, "fal"
    except Exception as exc:
        log.error("beat %s: fal.ai also failed: %s", beat_id, exc)
        return None


def _flush_generated_batch(video_id: int, items: list[_GeneratedItem]) -> list[dict]:
    """Grade a batch of generated images for style coherence; regenerate outliers once."""
    paths = [it.path for it in items]
    ratio, outliers = asset_store.grade_batch_coherence(paths)
    if ratio < COHERENCE_MIN_RATIO:
        log.warning("batch coherence %.0f%% < 80%% -- regenerating %d outlier(s)", ratio * 100, len(outliers))
        for idx in outliers:
            it = items[idx]
            regen = _generate_visual(it.beat_id, it.keywords, it.mood, it.is_diagram)
            if regen is not None:
                items[idx] = _GeneratedItem(it.beat_id, it.keywords, it.mood, it.is_diagram, regen[1], regen[0])
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
    `force_generate` skips BOTH stock tiers and generates every beat with SDXL -- for
    period/event topics stock can't serve (a modern city clip for a 1917 harbor), a
    period-styled illustration tracks the narration better."""
    if checkpoint.is_done(video_id, STEP):
        log.info("video %s: visuals already acquired, skipping", video_id)
        return asset_store.list_assets(video_id)

    saved: list[dict] = []
    pending: list[_GeneratedItem] = []
    motion_beats = 0
    total_beats = 0
    beat_seconds = _estimate_beat_seconds(video_id, shot_list)

    for i, beat in enumerate(shot_list):
        total_beats += 1
        beat_id = beat["beat_id"]
        keywords = beat.get("keywords", [])[:4]
        mood = beat.get("mood", "")
        is_diagram = _is_diagram_beat(beat)
        # CLIP relevance text for this beat: its keywords + narration span (what the scene is about).
        text = ", ".join(keywords) + (f". {beat.get('narration_span', '')}" if beat.get("narration_span") else "")

        # Stock tiers are skipped entirely in force_generate mode (SDXL every beat).
        if not force_generate:
            # Tier 1: motion b-roll montage (skipped for map/diagram beats -- footage rarely
            # fits them -- and for stills-only runs). A long beat pulls several DISTINCT clips
            # so it isn't one short clip looped; no clip lands -> fall through to stills.
            if not is_diagram and not stills_only:
                broll = _acquire_broll_clips(video_id, beat_id, keywords, _clips_needed(beat_seconds[i]), text)
                if broll:
                    saved.extend(broll)
                    motion_beats += 1
                    continue

            # Tier 2: stock photo (Ken Burns later) where no footage landed.
            record = None
            if not is_diagram:
                hit = _fetch_stock(keywords, text)
                if hit is not None:
                    record = asset_store.save_stock(video_id, beat_id, hit[0], hit[1])
            if record is not None:
                saved.append(record)
                continue

        # Tier 3/4: generated stills (SDXL -> fal), graded for style coherence in batches.
        generated = _generate_visual(beat_id, keywords, mood, is_diagram)
        if generated is None:
            # Last resort for ANY beat that reached generation and failed (generator missing,
            # timed out, or a transient stock miss earlier): the assembler needs one frame per
            # beat or it crashes, so try a stock photo rather than leaving the beat blank.
            if (hit := _fetch_stock(keywords, text)) is not None:
                record = asset_store.save_stock(video_id, beat_id, hit[0], hit[1])
                if record is not None:
                    saved.append(record)
                    continue
            log.error("beat %s: no visual acquired (video %s)", beat_id, video_id)
            continue
        path, source = generated
        pending.append(_GeneratedItem(beat_id, keywords, mood, is_diagram, source, path))
        if len(pending) >= COHERENCE_BATCH_SIZE:
            saved.extend(_flush_generated_batch(video_id, pending))
            pending = []

    if pending:
        saved.extend(_flush_generated_batch(video_id, pending))

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
