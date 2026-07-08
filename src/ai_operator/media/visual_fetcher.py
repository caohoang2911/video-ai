"""3-tier visual acquisition: stock (Pexels/Pixabay) -> local SDXL -> fal.ai.

Stock b-roll is the default so the video reads as documentary footage, not AI slop. SDXL/fal
only cover beats stock can't serve well (maps, diagrams, reenactments) or where stock genuinely
returned nothing, and generated images are graded in batches so a run doesn't drift in style
from one beat to the next.
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
SDXL_TIMEOUT_SEC = 45
FAL_TIMEOUT_SEC = 30
COHERENCE_BATCH_SIZE = 10
COHERENCE_MIN_RATIO = 0.8


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


def _fetch_stock(keywords: list[str]) -> tuple[str, str] | None:
    """First non-empty hit from Pexels/Pixabay run concurrently; None if both are empty/timeout."""
    query = " ".join(keywords[:4])

    async def _gather():
        loop = asyncio.get_event_loop()
        pexels_fut = loop.run_in_executor(None, stock_clients.search_pexels, query)
        pixabay_fut = loop.run_in_executor(None, stock_clients.search_pixabay, query)
        return await asyncio.wait_for(asyncio.gather(pexels_fut, pixabay_fut), timeout=STOCK_TIMEOUT_SEC)

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


def acquire(video_id: int, shot_list: list[dict]) -> list[dict]:
    """Resolve >=1 image per beat (stock-first) and persist via asset_store; idempotent."""
    if checkpoint.is_done(video_id, STEP):
        log.info("video %s: visuals already acquired, skipping", video_id)
        return asset_store.list_assets(video_id)

    saved: list[dict] = []
    pending: list[_GeneratedItem] = []

    for beat in shot_list:
        beat_id = beat["beat_id"]
        keywords = beat.get("keywords", [])[:4]
        mood = beat.get("mood", "")
        is_diagram = _is_diagram_beat(beat)

        record = None
        if not is_diagram:
            hit = _fetch_stock(keywords)
            if hit is not None:
                url, source = hit
                record = asset_store.save_stock(video_id, beat_id, url, source)

        if record is not None:
            saved.append(record)
            continue

        generated = _generate_visual(beat_id, keywords, mood, is_diagram)
        if generated is None:
            log.error("beat %s: no visual acquired (video %s)", beat_id, video_id)
            continue
        path, source = generated
        pending.append(_GeneratedItem(beat_id, keywords, mood, is_diagram, source, path))
        if len(pending) >= COHERENCE_BATCH_SIZE:
            saved.extend(_flush_generated_batch(video_id, pending))
            pending = []

    if pending:
        saved.extend(_flush_generated_batch(video_id, pending))

    checkpoint.write(video_id, STEP, {"count": len(saved)})
    return saved
