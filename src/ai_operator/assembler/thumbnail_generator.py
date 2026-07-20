"""3 thumbnail variants generated immediately at render time (not after upload) so
the manual YouTube-Studio A/B test always has candidates ready to go.

Each variant pairs a distinct key-frame with one title option's `thumbnail_text` — the
overlay line written to pair with that specific title (script.json carries 3 title options),
so the A/B title test and thumbnail test line up variant-for-variant.

The HERO (variant a — the primary thumb_path) is chosen for authenticity AND relevance: a
real archival photo that clears the event-relevance gate, enhanced with a subject-preserving
FLUX Kontext relight; when no archival is both relevant and available, a synthetic FLUX drama
frame stands in. Variants b/c stay real frames with a PIL cinematic grade — cheaper, and a
more varied A/B set. Every fal step degrades to a PIL grade so a thumbnail is never missing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from ..config import OUTPUT_DIR, settings
from ..db import SessionLocal
from ..db.models import Asset, Video
from ..logging_setup import get_logger
from ..media import cloud_flux, relevance_scorer
from . import thumbnail_frame_score, thumbnail_style

log = get_logger("assembler.thumbnail")

WIDTH, HEIGHT = 1280, 720
N_VARIANTS = 3
VARIANT_LETTERS = "abc"
# Relevances within this band count as a tie, so the aesthetic frame-score breaks it — a
# punchier frame only wins among near-equally-relevant photos, never over a clearly more
# relevant one. Keeps score noise from flipping the hero on a 0.01 difference.
_RELEVANCE_TIE_EPS = 0.05
_SCALE_FILL = f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}"

# Preserve-subject Kontext edit: relight/regrade only, never invent or remove objects — keeps
# a real historical photo defensible (a derivative grade, not a fabrication).
_KONTEXT_INSTRUCTION = (
    "enhance cinematic lighting, contrast and depth; add subtle atmospheric haze; "
    "preserve the subject, composition and all real details exactly; "
    "do NOT add, remove or invent objects; keep photorealistic and natural."
)


def generate(video_id: int, *, same_hero: bool = False) -> list[str]:
    """Write `thumb_a.jpg`, `thumb_b.jpg`, `thumb_c.jpg` under output/<video_id>/ and
    record the primary one on `videos.thumb_path`. Requires assemble() to have run.

    `same_hero` puts the SAME prepared hero behind all three variants so they differ only in
    headline. A default set varies image, copy and art style at once, so a Studio A/B winner
    cannot be attributed to any of them; holding the image fixed makes the copy the only
    variable. It is also cheaper — one Kontext/synthesis pass instead of per-variant work."""
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None or not video.video_path:
            raise ValueError(f"video {video_id} has no rendered video_path yet")
        video_path = Path(video.video_path)
        title = video.title or ""

    video_dir = OUTPUT_DIR / str(video_id)
    overlays = _overlay_texts(video_dir / "script.json")
    archival_ranked, others_ranked, subject = _gated_pools(video_id)
    hero_src, hero_mode, synth_path = _pick_hero(video, archival_ranked, video_id)

    # kicker year: title/subject first, else the script's canonical event_year (titles like
    # "...Sealed for 26 Years" carry no year). credits: per-photo CC BY/BY-SA burn-in lines.
    kicker = thumbnail_style.compose_kicker(subject, title, event_year=_event_year(video_dir / "script.json"))
    credits = _archival_credits(video_id)

    pool: list[Path] = [hero_src] if hero_src is not None else []
    for p in archival_ranked + others_ranked:
        if p not in pool:
            pool.append(p)
    if not pool:
        pool = [video_path]

    # each variant's punch line pairs with its title option; fall back to a title-derived
    # hook when that option carried no thumbnail_text (older scripts).
    headlines = [
        overlays[i] if i < len(overlays) and overlays[i].strip()
        else thumbnail_style.fallback_headline(title, subject)
        for i in range(N_VARIANTS)
    ]
    # With one shared hero the headline is the ONLY thing left that differs, so a script whose
    # title options carry no distinct thumbnail_text would silently write three identical files
    # and call it an A/B test. Refuse loudly instead — exactly the older scripts this path targets.
    if same_hero and len(set(headlines)) < 2:
        raise ValueError(
            f"video {video_id}: same_hero needs distinct per-title thumbnail_text, but this script "
            f"yields {len(set(headlines))} distinct headline(s) — all variants would be identical. "
            "Regenerate the script, or generate without same_hero so the image varies instead."
        )

    paths = []
    hero_cache: Path | None = None  # prepared hero frame, reused when every variant shares it
    hero_graded = False
    try:
        for i in range(N_VARIANTS):
            frame_path = video_dir / f"_thumb_frame_{i}.jpg"
            variant_path = video_dir / f"thumb_{VARIANT_LETTERS[i]}.jpg"
            source = pool[0] if same_hero else pool[i % len(pool)]
            credit = credits.get(str(source))  # only real archival photos carry a credit line
            headline = headlines[i]
            try:
                if hero_cache is not None:  # same_hero: reuse the already-prepared frame verbatim
                    shutil.copy2(hero_cache, frame_path)
                    already_graded = hero_graded
                else:
                    _extract_frame(source, frame_path)
                    # `_prepare_hero` returns True when the frame is ALREADY cinematically graded
                    # (Kontext hero / synthetic) -> skip the PIL grade so it is not double-graded.
                    already_graded = _prepare_hero(frame_path, hero_mode, video_id) if i == 0 else False
                _overlay_text(frame_path, headline, variant_path, kicker,
                              grade=not already_graded, credit=credit)
                if same_hero and hero_cache is None:
                    # Cache only once the frame has actually produced a variant — caching earlier
                    # would hand b/c a hero that a failed variant a never used.
                    hero_cache = video_dir / "_thumb_hero.jpg"
                    shutil.copy2(frame_path, hero_cache)
                    hero_graded = already_graded
            except Exception as exc:  # noqa: BLE001 - a bad source must never leave a variant missing
                log.warning("thumb variant %s failed (%s) -> plain video keyframe", VARIANT_LETTERS[i], exc)
                _extract_frame(video_path, frame_path)
                _overlay_text(frame_path, headline, variant_path, kicker, grade=True)  # keyframe -> no credit
            finally:
                frame_path.unlink(missing_ok=True)
            paths.append(str(variant_path))
    finally:  # temps must not survive an abort partway through the variant loop
        if synth_path is not None:
            synth_path.unlink(missing_ok=True)
        if hero_cache is not None:
            hero_cache.unlink(missing_ok=True)

    with SessionLocal() as session:
        video = session.get(Video, video_id)
        video.thumb_path = paths[0]
        session.commit()
    return paths


def _overlay_texts(script_path: Path) -> list[str]:
    """Thumbnail overlay lines, one per title option (dict access — script.json entries are
    `{title, thumbnail_text}`, not pydantic objects). Empty when script.json is absent."""
    if not script_path.exists():
        return []
    try:
        script = json.loads(script_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:  # corrupt script -> title-derived headlines
        log.warning("thumbnail overlays: unreadable script.json (%s)", exc)
        return []
    # `or ""` (not the .get default) also coalesces an explicit JSON null thumbnail_text.
    return [(o.get("thumbnail_text") or "").upper() for o in script.get("title_options", [])]


def _caption_free_sources(video_id: int) -> tuple[list[Path], list[Path]]:
    """Raw per-beat visuals as frame sources, split `(archival, others)`. Unlike the final
    render these carry NO burned narration captions, so nothing shows through the overlay
    text. Each group is ordered by filename (== beat order) so equal-scored candidates keep a
    deterministic beat-order tie-break."""
    with SessionLocal() as session:
        rows = session.execute(
            select(Asset).where(
                Asset.video_id == video_id,
                Asset.kind.in_(("archival", "video_broll", "gen", "stock")),
            )
        ).scalars().all()
    archival, others = [], []
    for r in rows:
        p = Path(r.url_or_path)
        if p.exists():
            (archival if r.kind == "archival" else others).append(p)
    return sorted(archival, key=lambda p: p.name), sorted(others, key=lambda p: p.name)


def _subject_text(video_id: int) -> str:
    """Event/subject phrase for the relevance gate — the same clean pre-colon anchor the
    archive search uses, so the gate judges against what the video is actually about."""
    from ..media.visual_fetcher import _archival_anchor  # local: avoid import cycle at module load

    try:
        return _archival_anchor(video_id)
    except Exception:  # noqa: BLE001 - gate is best-effort; empty subject => gate skipped
        return ""


def _gate_disabled_alert(video_id: int, reason: str) -> None:
    """One loud operator signal that the relevance gate could not judge this video's hero — the
    disabled check must never be silent. A missing/expired/quota'd key, an outage, or an
    underivable subject all land here."""
    from ..ops.alerting import alert  # lazy: keep ops off this module's import path

    alert(
        f"thumbnail relevance gating DISABLED ({reason}) — "
        f"hero for video {video_id} chosen without an event-match check"
    )


def _relevance_gate(
    paths: list[Path], subject: str, video_id: int, *, expect_scores: bool = True
) -> list[tuple[Path, float | None]]:
    """Keep archival photos that depict `subject`, each paired with its event-relevance score —
    a good-looking but wrong-subject archive (wrong ship, wrong livery) must not face the video.
    The score rides along so the caller can rank relevance-first (see `_rank_relevance_first`).
    Best-effort per image: an unscored image (score None) is kept, not punished. The gate FAILS
    LOUD (an operator alert, never a silent pass) whenever it cannot actually judge: no subject,
    no backend configured, OR a configured backend that returns no usable score for ANY candidate
    (an expired/quota'd key or an outage — the likeliest silent-off in practice). `expect_scores`
    is False for the video-heavy `others` pool, where all-None is normal (clips can't be
    image-scored) and would false-alarm."""
    if not paths:
        return []
    if not subject:
        _gate_disabled_alert(video_id, "event subject could not be derived")
        return [(p, None) for p in paths]
    if not relevance_scorer.available():
        _gate_disabled_alert(video_id, "no relevance backend configured")
        return [(p, None) for p in paths]
    kept: list[tuple[Path, float | None]] = []
    scored_any = False
    for p in paths:
        s = relevance_scorer.score(subject, p, video_id=video_id)
        if s is None:  # unreadable / model hiccup -> keep, don't punish on a failed measure
            kept.append((p, None))
            continue
        scored_any = True
        log.info("thumb relevance %.3f (min %.2f) subject=%r img=%s",
                 s, settings.THUMB_RELEVANCE_MIN, subject, p.name)
        if s >= settings.THUMB_RELEVANCE_MIN:
            kept.append((p, s))
    if expect_scores and not scored_any:  # backend present but judged nothing -> broken / quota'd
        _gate_disabled_alert(video_id, "relevance backend returned no usable score")
    return kept


def _rank_relevance_first(scored: list[tuple[Path, float | None]]) -> list[Path]:
    """Order gate-passers by event-relevance first; within a relevance band (`_RELEVANCE_TIE_EPS`)
    delegate to `thumbnail_frame_score.rank`, which orders by aesthetic punch AND drops
    near-duplicate frames — so two crops of one photo never take two A/B slots. Unscored images
    (fail-open) all share one band -> pure frame-score order + dedup, the prior behaviour.

    Frames unfit to face a video at all are dropped BEFORE banding. Ranking inside a band cannot
    do it: a band holding exactly as many candidates as there are variants gives each one a slot
    no matter how badly it scores, which is how scans of 1917 newsprint reached the A/B set."""
    fit = [(p, rel) for p, rel in scored if thumbnail_frame_score.usable(p)]
    scored = fit or scored  # everything unfit -> keep the field rather than return nothing

    bands: dict[int, list[Path]] = {}
    for path, rel in scored:
        band = round(rel / _RELEVANCE_TIE_EPS) if rel is not None else 0
        bands.setdefault(band, []).append(path)
    ranked: list[Path] = []
    for band in sorted(bands, reverse=True):  # highest relevance first
        ranked.extend(thumbnail_frame_score.rank(bands[band], N_VARIANTS))
    return ranked[:N_VARIANTS]


def _gated_pools(video_id: int) -> tuple[list[Path], list[Path], str]:
    """`(archival_ranked, others_ranked, subject)`. Archival is relevance-gated then ranked
    relevance-first (aesthetic tie-break + near-duplicate dedup). `others` (stock/broll/gen)
    normally only fill secondary A/B variants, so frame-score ranking is enough — BUT when no
    archival is relevant an `others` frame can fall through to the hero (no-FAL_KEY path), so in
    that branch it must clear the same relevance gate too: a generic modern clip must not face
    the video un-judged. Gating `others` only in that branch keeps the extra vision calls off the
    common path; `expect_scores=False` there because video-broll can't be image-scored."""
    subject = _subject_text(video_id)
    archival, others = _caption_free_sources(video_id)
    archival_ranked = _rank_relevance_first(_relevance_gate(archival, subject, video_id))
    if archival_ranked:
        others_ranked = thumbnail_frame_score.rank(others, N_VARIANTS)
    else:
        others_ranked = _rank_relevance_first(
            _relevance_gate(others, subject, video_id, expect_scores=False)
        )
    return archival_ranked, others_ranked, subject


def _thumbnail_sources(video_id: int) -> list[Path]:
    """Ordered variant base frames, ARCHIVAL FIRST (relevance-gated), others filling the rest.
    Kept as a thin, directly-testable view of source selection; `generate` adds hero synthesis
    on top."""
    archival_ranked, others_ranked, _ = _gated_pools(video_id)
    picked = list(archival_ranked)
    if len(picked) < N_VARIANTS:
        picked += others_ranked[: N_VARIANTS - len(picked)]
    return picked[:N_VARIANTS]


def _pick_hero(video: Video, archival_ranked: list[Path], video_id: int) -> tuple[Path | None, str | None, Path | None]:
    """Choose the primary-variant source: a gate-passing archival photo ("archival"), else a
    synthetic FLUX drama frame ("synthetic"). Returns `(hero_src, mode, synth_temp)` — mode
    None (with no source) when neither is available and `generate` falls back to the pool."""
    if archival_ranked:
        return archival_ranked[0], "archival", None
    if settings.FAL_KEY:
        try:
            synth = cloud_flux.generate(
                _hero_prompt(video), is_diagram=False, photoreal=True, video_id=video_id
            )
            return synth, "synthetic", synth
        except Exception as exc:  # noqa: BLE001 - never block a thumbnail on the synthetic tier
            log.warning("synthetic hero generation failed (%s) -> falling back to best frame", exc)
    return None, None, None


def _prepare_hero(frame_path: Path, hero_mode: str | None, video_id: int) -> bool:
    """Ready the primary variant's frame; return whether stylize should skip its PIL grade.
    A real archival hero gets a Kontext relight (toggle on); a synthetic hero is already
    cinematic. Both then skip the grade. Kontext failure / toggle off -> PIL grade the frame.
    """
    if hero_mode == "archival" and settings.THUMBNAIL_KONTEXT_ENHANCE:
        enhanced = None
        try:
            enhanced = cloud_flux.kontext_edit(frame_path, _KONTEXT_INSTRUCTION, video_id=video_id)
            _extract_frame(enhanced, frame_path)  # rescale Kontext output back to WIDTHxHEIGHT
            return True  # already graded -> skip PIL grade
        except Exception as exc:  # noqa: BLE001 - degrade to PIL grade, never a missing thumb
            log.warning("Kontext enhance failed (%s) -> PIL grade", exc)
            return False
        finally:
            if enhanced is not None:  # drop the Kontext temp even if the rescale raised
                enhanced.unlink(missing_ok=True)
    return hero_mode == "synthetic"  # synthetic already cinematic; archival w/o Kontext -> grade


def _hero_prompt(video: Video) -> str:
    """Cinematic dark synthetic-hero prompt anchored on the video's subject (leading entity)
    plus its canonical year — an entity + era cue so FLUX draws the ACTUAL event period-
    accurately, not a generic moody frame. Year comes from the script's `event_year` when the
    title carries none."""
    from ..media.visual_fetcher import extract_entity  # lazy: avoid import cycle at module load

    # Same anchor the gate judges against (parent-aware for shorts, whose own title is a hook
    # with the entity after a dash) so the synthetic hero draws the ACTUAL event; fall back to
    # the title's leading entity when the DB lookup yields nothing (detached/test video, no topic).
    subject = _subject_text(video.id) or extract_entity(video.title or "") or settings.NICHE
    script_path = OUTPUT_DIR / str(video.id) / "script.json"
    year = _event_year(script_path)
    era = f", {year}" if year else ""
    return (
        f"cinematic documentary movie-poster still of {_visual_subject(subject, script_path, video.id)}{era}, "
        "period-accurate detail, dramatic low-key lighting, moody atmosphere, volumetric haze, "
        "deep shadows, teal and amber color grade, photorealistic, ultra detailed, "
        "no text, no watermark"
    )


def _visual_subject(subject: str, script_path: Path, video_id: int) -> str:
    """Turn a bare subject NAME into what that subject physically IS, for the image generator.

    A name on its own is ambiguous to a text-to-image model in a way it never is to a reader:
    the 1891 excursion steamboat "General Slocum" renders as a military officer in dress
    uniform, because "General" reads as a rank. One cheap text call, grounded in the script's
    own narration, resolves that ("the wooden excursion steamboat General Slocum"). Degrades to
    the bare subject on any failure — a slightly generic hero beats no hero."""
    context = _narration_excerpt(script_path)
    if not subject or not context:
        return subject
    from ..content import llm_client  # lazy: keep the content package off this import path

    try:
        phrase = llm_client.complete(
            "You identify what a historical subject physically is, so an image generator draws "
            "the right thing. Reply with ONE noun phrase of at most 10 words that states the KIND "
            "of object, vessel, structure or place AND keeps the subject's proper name — e.g. "
            "'the paddle steamboat General Slocum'. Never describe a person unless the subject "
            "truly is one. No punctuation, no explanation.",
            f'Subject: "{subject}"\n\nFrom the documentary narration:\n{context}',
            max_tokens=32,
            step="thumb_hero_subject",
            video_id=video_id,
        ).strip()
    except Exception as exc:  # noqa: BLE001 - never block a thumbnail on the disambiguation call
        log.warning("hero subject disambiguation failed (%s) -> bare subject", exc)
        return subject
    # A rambling or empty answer is worse than the plain name; only take a tight noun phrase.
    if not phrase or len(phrase.split()) > 12:
        return subject
    log.info("hero subject %r -> %r", subject, phrase)
    return phrase


def _narration_excerpt(script_path: Path, limit: int = 600) -> str:
    """Opening narration, which states what the subject is before any hook language. Empty
    when the script is missing or unreadable."""
    if not script_path.exists():
        return ""
    try:
        narration = json.loads(script_path.read_text(encoding="utf-8")).get("narration") or ""
    except (json.JSONDecodeError, OSError):
        return ""
    return str(narration)[:limit]


def _extract_frame(src: Path, out_path: Path) -> None:
    """One WIDTHxHEIGHT frame from `src`: a mid-ish frame for a b-roll clip, the scaled image
    for a still. Aspect is filled-and-cropped (no distortion)."""
    seek = ["-ss", "1"] if src.suffix.lower() == ".mp4" else []  # 1s in; every clip is longer
    cmd = ["ffmpeg", "-y", *seek, "-i", str(src), "-frames:v", "1", "-vf", _SCALE_FILL, str(out_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extract failed for {src.name}: {result.stderr[-500:]}")


def _overlay_text(frame_path: Path, text: str, out_path: Path, kicker: str,
                  grade: bool = True, credit: str | None = None) -> None:
    """Cinematic grade (optional) + vignette, then the negative-space poster headline (see
    thumbnail_style) under the shared brass `kicker`, plus a bottom-right photo credit when the
    source is a CC BY/BY-SA archival photo."""
    img = thumbnail_style.stylize(Image.open(frame_path), grade=grade)
    thumbnail_style.draw_title(img, text, kicker=kicker)
    thumbnail_style.draw_credit(img, credit or "")
    img.save(out_path, "JPEG", quality=92)


def _event_year(script_path: Path) -> int | None:
    """The disaster's canonical 4-digit year, emitted by the script generator — a reliable
    kicker year when the title itself carries none. None when absent/unparseable."""
    if not script_path.exists():
        return None
    try:
        year = json.loads(script_path.read_text(encoding="utf-8")).get("event_year")
        return int(year) if year else None
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def _archival_credits(video_id: int) -> dict[str, str]:
    """`{archival photo path -> on-image credit line}` for this video's CC BY/BY-SA stills. The
    Asset license field is the `short | artist | page` triple written by save_archival."""
    with SessionLocal() as session:
        rows = session.execute(
            select(Asset.url_or_path, Asset.license).where(
                Asset.video_id == video_id, Asset.kind == "archival"
            )
        ).all()
    credits: dict[str, str] = {}
    for path, lic in rows:
        line = _thumb_credit(lic)
        if line:
            credits[str(Path(path))] = line
    return credits


def _thumb_credit(license_field: str | None) -> str | None:
    """An on-image credit for a CC BY / CC BY-SA Commons photo, else None — PD/CC0 need no
    attribution and stay off the thumbnail to keep it clean."""
    parts = [p.strip() for p in (license_field or "").split("|")]
    if len(parts) != 3:
        return None
    short, artist, _page = parts
    if not short.lower().startswith(("cc by", "cc-by")):
        return None
    who = artist if artist and artist.lower() != "unknown author" else "Unknown author"
    return f"Photo: {who} · Wikimedia Commons · {short}"
