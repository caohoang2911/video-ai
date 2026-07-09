"""3 thumbnail variants generated immediately at render time (not after upload) so
the manual YouTube-Studio A/B test always has candidates ready to go.

Each variant pairs a distinct key-frame with one title option's `thumbnail_text` — the
overlay line written to pair with that specific title (script.json carries 3 title options),
so the A/B title test and thumbnail test line up variant-for-variant instead of overlaying a
generic hook line on every frame.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from ..config import OUTPUT_DIR
from ..db import SessionLocal
from ..db.models import Asset, Video
from ..logging_setup import get_logger
from . import thumbnail_style

log = get_logger("assembler.thumbnail")

WIDTH, HEIGHT = 1280, 720
N_VARIANTS = 3
VARIANT_LETTERS = "abc"
_SCALE_FILL = f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}"


def generate(video_id: int) -> list[str]:
    """Write `thumb_a.jpg`, `thumb_b.jpg`, `thumb_c.jpg` under output/<video_id>/ and
    record the primary one on `videos.thumb_path`. Requires assemble() to have run."""
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None or not video.video_path:
            raise ValueError(f"video {video_id} has no rendered video_path yet")
        video_path = Path(video.video_path)

    video_dir = OUTPUT_DIR / str(video_id)
    overlays = _overlay_texts(video_dir / "script.json")
    sources = _pick_spread(_caption_free_sources(video_id), N_VARIANTS) or [video_path]

    paths = []
    for i in range(N_VARIANTS):
        frame_path = video_dir / f"_thumb_frame_{i}.jpg"
        variant_path = video_dir / f"thumb_{VARIANT_LETTERS[i]}.jpg"
        _extract_frame(sources[i % len(sources)], frame_path)
        _overlay_text(frame_path, overlays[i] if i < len(overlays) else "", variant_path)
        frame_path.unlink(missing_ok=True)
        paths.append(str(variant_path))

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
    script = json.loads(script_path.read_text(encoding="utf-8"))
    return [o.get("thumbnail_text", "").upper() for o in script.get("title_options", [])]


def _caption_free_sources(video_id: int) -> list[Path]:
    """Raw per-beat visuals (b-roll clips + stills) as frame sources. Unlike the final render
    these carry NO burned narration captions, so nothing shows through the overlay text.
    Ordered by filename (== beat order) so `_pick_spread` samples across the video."""
    with SessionLocal() as session:
        rows = session.execute(
            select(Asset).where(
                Asset.video_id == video_id, Asset.kind.in_(("video_broll", "gen", "stock"))
            )
        ).scalars().all()
    paths = sorted((Path(r.url_or_path) for r in rows), key=lambda p: p.name)
    return [p for p in paths if p.exists()]


def _pick_spread(items: list, n: int) -> list:
    """`n` items spread evenly across `items` (variety early/mid/late); fewer if list is short."""
    if len(items) <= n:
        return list(items)
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def _extract_frame(src: Path, out_path: Path) -> None:
    """One WIDTHxHEIGHT frame from `src`: a mid-ish frame for a b-roll clip, the scaled image
    for a still. Aspect is filled-and-cropped (no distortion)."""
    seek = ["-ss", "1"] if src.suffix.lower() == ".mp4" else []  # 1s in; every clip is longer
    cmd = ["ffmpeg", "-y", *seek, "-i", str(src), "-frames:v", "1", "-vf", _SCALE_FILL, str(out_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extract failed for {src.name}: {result.stderr[-500:]}")


def _overlay_text(frame_path: Path, text: str, out_path: Path) -> None:
    """Bold-documentary treatment: cinematic grade + vignette + dark band, then the big
    yellow stroked overlay line (see thumbnail_style)."""
    img = thumbnail_style.stylize(Image.open(frame_path))
    thumbnail_style.draw_title(img, text)
    img.save(out_path, "JPEG", quality=92)
