"""Persisted media assets -- md5 dedup, AI watermark for generated images, DB rows for audit.

Every acquired image must be traceable to a license before the publish phase's upload; a
duplicate check by content hash stops Pexels/Pixabay returning the same stock photo twice
across beats, and generated images get an "AI-Generated" watermark burned in for transparency.
"""

from __future__ import annotations

import hashlib
import time
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from ..config import OUTPUT_DIR
from ..db.engine import SessionLocal
from ..db.models import Asset, Video
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
    """Md5s a new save must not duplicate. A MAIN video dedups against its own assets (no
    two beats share one image). A SHORT dedups against its whole FAMILY — parent plus every
    sibling: sibling shorts refetch from the same Commons pool with near-identical queries,
    so without the family scope they all pick the same top-ranked photos and the batch
    reads as duplicates in the feed."""
    with SessionLocal() as s:
        ids = [video_id]
        video = s.get(Video, video_id)
        if video is not None and video.parent_id is not None:
            siblings = s.execute(
                select(Video.id).where(Video.parent_id == video.parent_id)
            ).scalars().all()
            ids = [video.parent_id, *siblings]
        rows = s.execute(select(Asset.md5).where(Asset.video_id.in_(ids))).scalars().all()
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


def save_archival(
    video_id: int, beat_id: int, url: str, *, license_short: str, artist: str, file_page: str
) -> dict | None:
    """Download a Wikimedia Commons archival photo. Licensing is PER-FILE (unlike the
    per-provider stock licenses), so the row's license field stores the full attribution
    triple `license | artist | file page URL` -- the publish phase splits it to build the
    description credit line. Returns None on duplicate/failed download."""
    resp = None
    # upload.wikimedia.org (Varnish) throttles bursts with 429 + a Retry-After hint. The
    # CLIP-rerank thumbnail burst just before this call routinely trips it, so ONE retry
    # isn't enough -- respect Retry-After and back off a few times. The window drains in
    # ~10s, so paced retries recover the real photo instead of falling through to generation.
    # Full descriptive UA per Wikimedia policy (a bare "ai-operator/0.1" is throttled harder).
    headers = {"User-Agent": "ai-operator/0.1 (self-hosted documentary pipeline)"}
    for attempt in range(4):
        try:
            resp = requests.get(url, timeout=15, headers=headers)
            resp.raise_for_status()
            break
        except Exception as exc:
            throttled = getattr(resp, "status_code", None) == 429 or "429" in str(exc)
            if throttled and attempt < 3:
                try:
                    retry_after = int((getattr(resp, "headers", {}) or {}).get("Retry-After", "10"))
                except (TypeError, ValueError):
                    retry_after = 10
                time.sleep(min(max(retry_after, 5), 15) + 2)
                continue
            log.warning("beat %s: archival download failed: %s", beat_id, exc)
            return None

    md5 = _md5_bytes(resp.content)
    if md5 in _existing_md5s(video_id):
        log.info("beat %s: duplicate archival image (md5=%s), skipping", beat_id, md5)
        return None

    dest = _img_dir(video_id) / f"beat_{beat_id:02d}.jpg"
    dest.write_bytes(resp.content)
    license_full = f"{license_short} | {artist or 'unknown author'} | {file_page}"
    return _write_row(video_id, kind="archival", source="wikimedia", path=dest,
                      license_=license_full, md5=md5)


def save_video_broll(video_id: int, beat_id: int, url: str, source: str, index: int = 0) -> dict | None:
    """Download a stock VIDEO clip, dedup by raw-content md5, normalize to 1920x1080@24fps
    (audio stripped), and persist an `Asset(kind="video_broll")`. Returns None on a
    duplicate, a failed download, or a normalize failure -- the caller then falls back to
    stills for that beat, so a single bad clip never blocks the whole video.

    `index` distinguishes multiple montage clips for one beat: the first (index 0) keeps the
    plain `beat_NN.mp4` name, extra clips are `beat_NN_01.mp4`, `beat_NN_02.mp4`, ..."""
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
    suffix = "" if index == 0 else f"_{index:02d}"
    raw = broll_dir / f"beat_{beat_id:02d}{suffix}.raw.mp4"
    dest = broll_dir / f"beat_{beat_id:02d}{suffix}.mp4"
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


_PLACEHOLDER_LICENSE = "synthesized placeholder (no source available)"


def save_placeholder(video_id: int, beat_id: int) -> dict:
    """Absolute last-resort still: a neutral graded card so a beat is NEVER left blank -- a
    beat with no frame has nothing for the assembler to render and crashes the whole video.
    Only reached when every stock + generation tier failed for the beat."""
    dest = _img_dir(video_id) / f"beat_{beat_id:02d}.jpg"
    _gradient_card().save(dest, "JPEG", quality=90)
    return _write_row(video_id, kind="gen", source="placeholder", path=dest,
                      license_=_PLACEHOLDER_LICENSE, md5=None)


def _gradient_card(size: tuple[int, int] = (1920, 1080),
                   top: tuple[int, int, int] = (20, 30, 46),
                   bottom: tuple[int, int, int] = (6, 9, 14)) -> Image.Image:
    """Fast vertical dark gradient: build a 1px-wide column then stretch to full width."""
    h = size[1]
    col = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / h
        col.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return col.resize(size)


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
