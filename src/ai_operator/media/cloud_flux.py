"""fal.ai Flux -- the primary still generator by default (IMAGE_GEN_BACKEND="fal_flux"); local
SDXL is the offline fallback. Set IMAGE_GEN_BACKEND="sdxl" to swap the order (SDXL first, fal
fallback) for a free/offline run.

`fal-client` is an opt-in extra (`pip install .[cloud]`), NOT a base dependency, so the
import is deferred into `generate()` -- this module must stay importable with FAL_KEY unset
and fal-client not installed (the CLI imports `visual_fetcher` -> this module on every run).
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import requests

from ..config import settings
from ..cost.budget_guard import check_and_reserve, record_actual
from ..cost.estimator import estimate_step
from ..logging_setup import get_logger

log = get_logger("cloud_flux")

# fal.ai routes Flux.1 [dev] at `fal-ai/flux/dev` (namespace/app/variant). The old
# `fal-ai/flux-dev` parsed as an app literally named "flux-dev", which fal rejects with
# "Application 'flux-dev' not found" -- so every generation failed.
FAL_MODEL = "fal-ai/flux/dev"
# FLUX.1 Kontext [pro]: image->image edit that preserves the subject/composition and only
# relights/regrades per the instruction. Verified live against fal (fal-ai/flux/kontext 404s).
FAL_KONTEXT_MODEL = "fal-ai/flux-pro/kontext"
_BACKOFF_SEC = (0, 2, 4, 8)  # first attempt has no delay
_DOWNLOAD_TIMEOUT_SEC = 30

# Same non-photorealistic guard as local_sdxl.py -- fal.ai output must never masquerade as
# real stock footage.
_MAP_STYLE_PREFIX = "hand-drawn historical map, muted 19th-century colors, "
_GENERIC_ILLUSTRATION_PREFIX = "editorial illustration, muted color palette, non-photorealistic, "


def generate(
    prompt: str, *, is_diagram: bool = True, photoreal: bool = False, video_id: int | None = None
) -> Path:
    """Generate one image via fal.ai flux-dev; returns a local temp file (caller persists it).

    `photoreal=True` skips the non-photorealistic guard prefix and requests a 16:9 frame — a
    deliberate THUMBNAIL-only exception (a dramatic hero face for the video card), never used
    in the in-video visual pipeline where synthetic stills must stay clearly illustrative.
    """
    if not settings.FAL_KEY:
        raise RuntimeError("cloud_flux: FAL_KEY not configured")
    # fal_client authenticates from the FAL_KEY OS env var, but our key lives in settings
    # (loaded from .env) and isn't necessarily exported to the process env -- propagate it,
    # else fal_client raises "No credentials found" even though FAL_KEY is configured.
    os.environ["FAL_KEY"] = settings.FAL_KEY

    try:
        import fal_client  # optional "cloud" extra -- only imported once this tier is reached
    except ImportError as exc:
        raise RuntimeError("cloud_flux: fal-client not installed (pip install .[cloud])") from exc

    if photoreal:
        full_prompt = prompt
        arguments = {"prompt": full_prompt, "image_size": "landscape_16_9"}
    else:
        style_prefix = _MAP_STYLE_PREFIX if is_diagram else _GENERIC_ILLUSTRATION_PREFIX
        full_prompt = f"{style_prefix}{prompt}"
        arguments = {"prompt": full_prompt}

    estimated = estimate_step("fal", images=1)
    ledger_id = check_and_reserve(estimated, step="visual_fal", provider="fal", video_id=video_id, units=1)

    last_exc: Exception | None = None
    billed = False
    for attempt, delay in enumerate(_BACKOFF_SEC):
        if delay:
            time.sleep(delay)
        try:
            # Sync API, NOT asyncio.run(run_async(...)): asyncio.run creates then CLOSES a
            # fresh event loop each retry, but fal_client caches a global async HTTP client
            # bound to the first loop -- later retries then hit "Event loop is closed".
            result = fal_client.run(FAL_MODEL, arguments=arguments)
            billed = True  # fal has generated (and billed) by the time run() returns
            url = result["images"][0]["url"]
            path = _download(url)
            record_actual(ledger_id, estimated)
            return path
        except Exception as exc:
            last_exc = exc
            log.warning("fal.ai attempt %d/%d failed: %s", attempt + 1, len(_BACKOFF_SEC), exc)

    # If a generation succeeded but the download failed, fal still billed -- don't zero it out.
    record_actual(ledger_id, estimated if billed else 0.0)
    raise RuntimeError(f"cloud_flux: all retries exhausted: {last_exc}")


def kontext_edit(image_path: Path, instruction: str, *, video_id: int | None = None) -> Path:
    """Relight/regrade `image_path` via FLUX Kontext under `instruction`, preserving the
    subject + composition (no invented objects). Returns a local temp file. ~$0.04. Raises on
    exhausted retries — the caller falls back to a PIL grade so a thumbnail is never missing.
    """
    if not settings.FAL_KEY:
        raise RuntimeError("cloud_flux: FAL_KEY not configured")
    os.environ["FAL_KEY"] = settings.FAL_KEY

    try:
        import fal_client
    except ImportError as exc:
        raise RuntimeError("cloud_flux: fal-client not installed (pip install .[cloud])") from exc

    estimated = estimate_step("fal_kontext", images=1)
    ledger_id = check_and_reserve(
        estimated, step="thumbnail_kontext", provider="fal", video_id=video_id, units=1
    )

    last_exc: Exception | None = None
    billed = False
    for attempt, delay in enumerate(_BACKOFF_SEC):
        if delay:
            time.sleep(delay)
        try:
            image_url = fal_client.upload_file(str(image_path))
            result = fal_client.run(
                FAL_KONTEXT_MODEL,
                arguments={"prompt": instruction, "image_url": image_url, "num_images": 1},
            )
            billed = True  # Kontext has run (and billed) by the time run() returns
            path = _download(result["images"][0]["url"])
            record_actual(ledger_id, estimated)
            return path
        except Exception as exc:
            last_exc = exc
            log.warning("fal Kontext attempt %d/%d failed: %s", attempt + 1, len(_BACKOFF_SEC), exc)

    record_actual(ledger_id, estimated if billed else 0.0)
    raise RuntimeError(f"cloud_flux.kontext_edit: all retries exhausted: {last_exc}")


def _download(url: str) -> Path:
    resp = requests.get(url, timeout=_DOWNLOAD_TIMEOUT_SEC)
    resp.raise_for_status()
    fd, path_str = tempfile.mkstemp(suffix=".jpg", prefix="fal_")
    import os

    os.close(fd)
    path = Path(path_str)
    path.write_bytes(resp.content)
    return path
