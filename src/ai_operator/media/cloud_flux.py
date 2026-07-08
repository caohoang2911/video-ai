"""fal.ai Flux -- tier-3 visual fallback, used only when local SDXL is unavailable/times out.

`fal-client` is an opt-in extra (`pip install .[cloud]`), NOT a base dependency, so the
import is deferred into `generate()` -- this module must stay importable with FAL_KEY unset
and fal-client not installed (the CLI imports `visual_fetcher` -> this module on every run).
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import requests

from ..config import settings
from ..cost.budget_guard import check_and_reserve, record_actual
from ..cost.estimator import estimate_step
from ..logging_setup import get_logger

log = get_logger("cloud_flux")

FAL_MODEL = "fal-ai/flux-dev"
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
            result = asyncio.run(fal_client.run_async(FAL_MODEL, arguments={"prompt": full_prompt}))
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
