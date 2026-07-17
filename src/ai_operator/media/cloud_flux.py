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
_BACKOFF_SEC = (0, 2, 4, 8)  # first attempt has no delay
_DOWNLOAD_TIMEOUT_SEC = 30

# Same non-photorealistic guard as local_sdxl.py -- fal.ai output must never masquerade as
# real stock footage.
_MAP_STYLE_PREFIX = "hand-drawn historical map, muted 19th-century colors, "
_GENERIC_ILLUSTRATION_PREFIX = "editorial illustration, muted color palette, non-photorealistic, "


def generate(prompt: str, *, is_diagram: bool = True, video_id: int | None = None) -> Path:
    """Generate one image via fal.ai flux-dev; returns a local temp file (caller persists it)."""
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

    style_prefix = _MAP_STYLE_PREFIX if is_diagram else _GENERIC_ILLUSTRATION_PREFIX
    full_prompt = f"{style_prefix}{prompt}"

    estimated = estimate_step("fal", images=1)
    ledger_id = check_and_reserve(estimated, step="visual_fal", provider="fal", video_id=video_id, units=1)

    last_exc: Exception | None = None
    for attempt, delay in enumerate(_BACKOFF_SEC):
        if delay:
            time.sleep(delay)
        try:
            # Sync API, NOT asyncio.run(run_async(...)): asyncio.run creates then CLOSES a
            # fresh event loop each retry, but fal_client caches a global async HTTP client
            # bound to the first loop -- later retries then hit "Event loop is closed".
            result = fal_client.run(FAL_MODEL, arguments={"prompt": full_prompt})
            url = result["images"][0]["url"]
            path = _download(url)
            record_actual(ledger_id, estimated)
            return path
        except Exception as exc:
            last_exc = exc
            log.warning("fal.ai attempt %d/%d failed: %s", attempt + 1, len(_BACKOFF_SEC), exc)

    record_actual(ledger_id, 0.0)
    raise RuntimeError(f"cloud_flux: all retries exhausted: {last_exc}")


def _download(url: str) -> Path:
    resp = requests.get(url, timeout=_DOWNLOAD_TIMEOUT_SEC)
    resp.raise_for_status()
    fd, path_str = tempfile.mkstemp(suffix=".jpg", prefix="fal_")
    import os

    os.close(fd)
    path = Path(path_str)
    path.write_bytes(resp.content)
    return path
