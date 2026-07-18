"""Event-relevance scoring of a candidate image against the video's subject.

The thumbnail hero must show the ACTUAL event, not just a good-looking but wrong-subject
archive (the wrong ship, the wrong livery). This scores an image against the event subject
so the gate can drop mismatches. Backed by Gemini vision (already the project's fallback
LLM) — no torch/CLIP dependency, so it runs in the same lean render venv the pipeline
already uses, instead of silently no-op'ing when torch is absent. Fully best-effort: any
failure returns None and the caller keeps the image.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from ..config import settings
from ..logging_setup import get_logger

log = get_logger("media.relevance_scorer")

# Downscale before upload: a thumbnail-relevance judgment needs no more detail, and a
# smaller image costs fewer vision tokens.
_MAX_EDGE = 512


def available() -> bool:
    """True when a relevance backend is usable (Gemini configured). No torch required."""
    return bool(settings.GEMINI_API_KEY)


def score(subject: str, image_path: Path, *, video_id: int | None = None) -> float | None:
    """0..1 relevance of the image to `subject` (1 = depicts exactly this event/subject),
    or None on any failure. Never raises — the gate is best-effort."""
    if not subject or not available():
        return None
    try:
        data = _downscaled_jpeg(image_path)
    except Exception as exc:  # noqa: BLE001 - unreadable image -> no judgment, keep it
        log.warning("relevance score: unreadable image %s (%s)", image_path.name, exc)
        return None
    # Lazy import keeps this module off the content-package import path (avoids any cycle).
    from ..content import llm_client

    return llm_client.score_image_relevance(subject, data, video_id=video_id)


def _downscaled_jpeg(image_path: Path) -> bytes:
    """Load, cap the long edge at `_MAX_EDGE`, and re-encode as JPEG bytes."""
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        im.thumbnail((_MAX_EDGE, _MAX_EDGE))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
