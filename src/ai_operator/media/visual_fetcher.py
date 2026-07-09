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
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .. import checkpoint
from ..logging_setup import get_logger
from . import asset_store, cloud_flux, local_sdxl, stock_clients

log = get_logger("visual_fetcher")

STEP = "visual_fetch"
_MAP_DIAGRAM_HINTS = ("map", "diagram", "chart", "route", "schematic", "illustration", "reenact", "blueprint")
STOCK_TIMEOUT_SEC = 5
STOCK_VIDEO_TIMEOUT_SEC = 8   # video search returns more metadata than photo search
SDXL_TIMEOUT_SEC = 45
FAL_TIMEOUT_SEC = 30
COHERENCE_BATCH_SIZE = 10
COHERENCE_MIN_RATIO = 0.8
MOTION_TARGET_RATIO = 0.5     # aim for >=50% of beats on real footage; below this is logged, not failed


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


def _fetch_first(query: str, pexels_fn, pixabay_fn, timeout: float) -> tuple[str, str] | None:
    """Run the two providers concurrently; return the first (url, source) hit, Pexels first.

    Shared by the photo and video search paths -- only the provider functions + timeout differ.
    None if both come back empty or the gather times out."""
    async def _gather():
        loop = asyncio.get_event_loop()
        pex = loop.run_in_executor(None, pexels_fn, query)
        pix = loop.run_in_executor(None, pixabay_fn, query)
        return await asyncio.wait_for(asyncio.gather(pex, pix), timeout=timeout)

    try:
        pexels_urls, pixabay_urls = asyncio.run(_gather())
    except Exception as exc:
        log.warning("stock fetch timed out/failed for %r: %s", query, exc)
        return None
    if pexels_urls:
        return pexels_urls[0], "pexels"
    if pixabay_urls:
        return pixabay_urls[0], "pixabay"
    return None


def _fetch_stock(keywords: list[str]) -> tuple[str, str] | None:
    """First non-empty stock-PHOTO hit from Pexels/Pixabay; None if both empty/timeout."""
    query = " ".join(keywords[:4])
    return _fetch_first(query, stock_clients.search_pexels, stock_clients.search_pixabay, STOCK_TIMEOUT_SEC)


def _fetch_stock_video(keywords: list[str]) -> tuple[str, str] | None:
    """First non-empty stock-VIDEO hit from Pexels/Pixabay; None if both empty/timeout."""
    query = " ".join(keywords[:4])
    return _fetch_first(
        query, stock_clients.search_pexels_video, stock_clients.search_pixabay_video, STOCK_VIDEO_TIMEOUT_SEC
    )


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


def acquire(video_id: int, shot_list: list[dict], stills_only: bool = False) -> list[dict]:
    """Resolve >=1 visual per beat (motion b-roll first, then stills) and persist via
    asset_store; idempotent. `stills_only` skips the video tier for cheap/offline runs."""
    if checkpoint.is_done(video_id, STEP):
        log.info("video %s: visuals already acquired, skipping", video_id)
        return asset_store.list_assets(video_id)

    saved: list[dict] = []
    pending: list[_GeneratedItem] = []
    motion_beats = 0
    total_beats = 0

    for beat in shot_list:
        total_beats += 1
        beat_id = beat["beat_id"]
        keywords = beat.get("keywords", [])[:4]
        mood = beat.get("mood", "")
        is_diagram = _is_diagram_beat(beat)

        record = None
        # Tier 1: motion b-roll (skipped for map/diagram beats -- footage rarely fits them --
        # and for stills-only runs). A download/normalize miss returns None -> fall through.
        if not is_diagram and not stills_only:
            vhit = _fetch_stock_video(keywords)
            if vhit is not None:
                record = asset_store.save_video_broll(video_id, beat_id, vhit[0], vhit[1])
                if record is not None:
                    motion_beats += 1

        # Tier 2: stock photo (Ken Burns later) where no footage landed.
        if record is None and not is_diagram:
            hit = _fetch_stock(keywords)
            if hit is not None:
                record = asset_store.save_stock(video_id, beat_id, hit[0], hit[1])

        if record is not None:
            saved.append(record)
            continue

        # Tier 3/4: generated stills (SDXL -> fal), graded for style coherence in batches.
        generated = _generate_visual(beat_id, keywords, mood, is_diagram)
        if generated is None:
            # Last resort: a diagram/illustration beat skipped the stock tiers above, so with no
            # image generator installed it would otherwise get NO frame at all -- and the assembler
            # needs one per beat. Fall back to a stock photo rather than leaving the beat blank.
            if is_diagram and (hit := _fetch_stock(keywords)) is not None:
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
