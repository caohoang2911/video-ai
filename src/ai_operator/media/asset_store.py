"""Persisted media assets -- md5 dedup, AI watermark for generated images, DB rows for audit.

Every acquired image must be traceable to a license before the publish phase's upload; a
duplicate check by content hash stops Pexels/Pixabay returning the same stock photo twice
across beats, and generated images get an "AI-Generated" watermark burned in for transparency.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from ..config import OUTPUT_DIR
from ..db.engine import SessionLocal
from ..db.models import Asset
from ..logging_setup import get_logger
from . import video_normalize

log = get_logger("asset_store")

_LICENSES = {
    "pexels": "Pexels License (free, no attribution required)",
    "pixabay": "Pixabay License (free, no attribution required)",
    "sdxl": "AI-generated (local SDXL) -- synthetic, not licensed stock",
    "fal": "AI-generated (fal.ai Flux) -- synthetic, not licensed stock",
}
# Pixabay VIDEO is CC0 (public-domain equivalent), a stronger grant than its image license.
_VIDEO_LICENSES = {
    "pexels": "Pexels License (free, no attribution required)",
    "pixabay": "Pixabay Content License / CC0 (free, no attribution required)",
}
_WATERMARK_TEXT = "AI-Generated"
_VIDEO_DOWNLOAD_TIMEOUT_SEC = 30  # b-roll clips are larger than photos; allow a longer pull


def _img_dir(video_id: int) -> Path:
    d = OUTPUT_DIR / str(video_id) / "img"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _broll_dir(video_id: int) -> Path:
    d = OUTPUT_DIR / str(video_id) / "broll"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _existing_md5s(video_id: int) -> set[str]:
    with SessionLocal() as s:
        rows = s.execute(select(Asset.md5).where(Asset.video_id == video_id)).scalars().all()
    return {r for r in rows if r}


def list_assets(video_id: int) -> list[dict]:
    """All persisted assets for a video (used when a checkpoint says visual_fetch is already done)."""
    with SessionLocal() as s:
        rows = s.execute(select(Asset).where(Asset.video_id == video_id)).scalars().all()
        return [
            {"id": r.id, "video_id": r.video_id, "kind": r.kind, "source": r.source,
             "path": r.url_or_path, "md5": r.md5}
            for r in rows
        ]


def save_stock(video_id: int, beat_id: int, url: str, source: str) -> dict | None:
    """Download a stock photo; returns None (and skips the write) on a duplicate/failed download."""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except Exception as exc:
        log.warning("beat %s: stock download failed (%s): %s", beat_id, source, exc)
        return None

    md5 = _md5_bytes(resp.content)
    if md5 in _existing_md5s(video_id):
        log.info("beat %s: duplicate stock image (md5=%s), skipping", beat_id, md5)
        return None

    dest = _img_dir(video_id) / f"beat_{beat_id:02d}.jpg"
    dest.write_bytes(resp.content)
    return _write_row(video_id, kind="stock", source=source, path=dest, license_=_LICENSES[source], md5=md5)


def save_video_broll(video_id: int, beat_id: int, url: str, source: str) -> dict | None:
    """Download a stock VIDEO clip, dedup by raw-content md5, normalize to 1920x1080@24fps
    (audio stripped), and persist an `Asset(kind="video_broll")`. Returns None on a
    duplicate, a failed download, or a normalize failure -- the caller then falls back to
    stills for that beat, so a single bad clip never blocks the whole video."""
    try:
        resp = requests.get(url, timeout=_VIDEO_DOWNLOAD_TIMEOUT_SEC)
        resp.raise_for_status()
    except Exception as exc:
        log.warning("beat %s: b-roll download failed (%s): %s", beat_id, source, exc)
        return None

    # md5 is of the RAW download (dedups identical source clips); the persisted file is the
    # normalized copy, so a b-roll row's md5 intentionally != its on-disk bytes (unlike photos).
    md5 = _md5_bytes(resp.content)
    if md5 in _existing_md5s(video_id):
        log.info("beat %s: duplicate b-roll clip (md5=%s), skipping", beat_id, md5)
        return None

    broll_dir = _broll_dir(video_id)
    raw = broll_dir / f"beat_{beat_id:02d}.raw.mp4"
    dest = broll_dir / f"beat_{beat_id:02d}.mp4"
    raw.write_bytes(resp.content)
    try:
        video_normalize.normalize(raw, dest)
    except Exception as exc:
        log.warning("beat %s: b-roll normalize failed, falling back to stills: %s", beat_id, exc)
        dest.unlink(missing_ok=True)  # drop any half-written output -- never leave a corrupt clip behind
        return None
    finally:
        raw.unlink(missing_ok=True)  # the un-normalized source is never needed again

    return _write_row(
        video_id, kind="video_broll", source=source, path=dest, license_=_VIDEO_LICENSES[source], md5=md5
    )


def save_generated(video_id: int, beat_id: int, image_path: Path, source: str) -> dict | None:
    """Watermark + dedup an AI-generated image and move it into the video's img dir."""
    image = Image.open(image_path).convert("RGB")
    _watermark(image)

    buf = BytesIO()
    image.save(buf, format="JPEG", quality=92)
    data = buf.getvalue()
    md5 = _md5_bytes(data)
    if md5 in _existing_md5s(video_id):
        log.info("beat %s: duplicate generated image (md5=%s), skipping", beat_id, md5)
        return None

    dest = _img_dir(video_id) / f"beat_{beat_id:02d}.jpg"
    dest.write_bytes(data)
    return _write_row(video_id, kind="gen", source=source, path=dest, license_=_LICENSES[source], md5=md5)


def _watermark(image: Image.Image) -> None:
    """Burn a small 'AI-Generated' label into the bottom-right corner (transparency/compliance)."""
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    w, h = image.size
    margin = 10
    bbox = draw.textbbox((0, 0), _WATERMARK_TEXT, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = w - tw - margin * 2, h - th - margin * 2
    draw.rectangle([x - 4, y - 4, x + tw + 4, y + th + 4], fill=(0, 0, 0))
    draw.text((x, y), _WATERMARK_TEXT, fill="white", font=font)


def _write_row(video_id: int, *, kind: str, source: str, path: Path, license_: str, md5: str) -> dict:
    with SessionLocal() as s:
        row = Asset(video_id=video_id, kind=kind, source=source, url_or_path=str(path), license=license_, md5=md5)
        s.add(row)
        s.commit()
        return {"id": row.id, "video_id": video_id, "kind": kind, "source": source, "path": str(path), "md5": md5}


def average_color(path: Path) -> tuple[float, float, float]:
    """Cheap tone/style proxy for batch-coherence grading (avoids a heavy CLIP dependency)."""
    image = Image.open(path).convert("RGB").resize((64, 64))
    pixels = list(image.getdata())
    n = len(pixels)
    r = sum(p[0] for p in pixels) / n
    g = sum(p[1] for p in pixels) / n
    b = sum(p[2] for p in pixels) / n
    return (r, g, b)


def grade_batch_coherence(paths: list[Path], threshold: float = 45.0) -> tuple[float, list[int]]:
    """(coherent_ratio, outlier_indexes) -- outliers sit far from the batch's average color/tone,
    a heuristic proxy for the temporal-drift / style-mismatch "AI slop" risk across generated beats."""
    if not paths:
        return 1.0, []
    colors = [average_color(p) for p in paths]
    n = len(colors)
    centroid = tuple(sum(c[i] for c in colors) / n for i in range(3))
    outliers = [
        idx for idx, c in enumerate(colors)
        if sum((c[i] - centroid[i]) ** 2 for i in range(3)) ** 0.5 > threshold
    ]
    return (n - len(outliers)) / n, outliers
