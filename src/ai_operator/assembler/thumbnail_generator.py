"""3 thumbnail variants generated immediately at render time (not after upload) so
phase 06's manual YouTube-Studio A/B test always has candidates ready to go.

Each variant pairs a distinct key-frame with a distinct hook's `text_overlay` (script.json
already carries 2-3 hook variants written for this exact purpose), giving genuinely
different thumbnails instead of the same frame with cosmetic tweaks.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from ..config import OUTPUT_DIR
from ..db import SessionLocal
from ..db.models import Video
from ..logging_setup import get_logger
from .branding import font_path

log = get_logger("assembler.thumbnail")

WIDTH, HEIGHT = 1280, 720
N_VARIANTS = 3
SCENE_THRESHOLD = 0.4
VARIANT_LETTERS = "abc"


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
    duration = _probe_duration(video_path)
    timestamps = _scene_cut_timestamps(video_path, duration)

    paths = []
    for i in range(N_VARIANTS):
        frame_path = video_dir / f"_thumb_frame_{i}.jpg"
        variant_path = video_dir / f"thumb_{VARIANT_LETTERS[i]}.jpg"
        _extract_frame(video_path, timestamps[i], frame_path)
        _overlay_text(frame_path, overlays[i] if i < len(overlays) else "", variant_path)
        frame_path.unlink(missing_ok=True)
        paths.append(str(variant_path))

    with SessionLocal() as session:
        video = session.get(Video, video_id)
        video.thumb_path = paths[0]
        session.commit()
    return paths


def _overlay_texts(script_path: Path) -> list[str]:
    if not script_path.exists():
        return []
    script = json.loads(script_path.read_text(encoding="utf-8"))
    return [h.get("text_overlay", "").upper() for h in script.get("hooks", [])]


def _probe_duration(video_path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _scene_cut_timestamps(video_path: Path, duration: float) -> list[float]:
    """Prefer visually distinct scene-cut frames; a static/slow source that never trips
    the scene threshold falls back to even thirds of the runtime."""
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',showinfo",
        "-vsync", "vfr", "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    times = []
    for line in result.stderr.splitlines():
        if "pts_time:" in line:
            try:
                times.append(float(line.split("pts_time:")[1].split()[0]))
            except (IndexError, ValueError):
                continue
    if len(times) >= N_VARIANTS:
        step = len(times) / N_VARIANTS
        return [times[int(i * step)] for i in range(N_VARIANTS)]
    return [duration * f for f in (0.25, 0.5, 0.75)]


def _extract_frame(video_path: Path, timestamp: float, out_path: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-ss", f"{timestamp:.3f}", "-i", str(video_path),
        "-frames:v", "1", "-vf", f"scale={WIDTH}:{HEIGHT}", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extract failed at {timestamp}s: {result.stderr[-500:]}")


def _overlay_text(frame_path: Path, text: str, out_path: Path) -> None:
    img = Image.open(frame_path).convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.15)
    img = ImageEnhance.Color(img).enhance(1.1)
    if text:
        _draw_stroked_text(ImageDraw.Draw(img), text, _load_font())
    img.save(out_path, "JPEG", quality=92)


def _load_font() -> ImageFont.FreeTypeFont:
    path = font_path()
    if path:
        return ImageFont.truetype(path, 84)
    return ImageFont.load_default(size=84)


def _draw_stroked_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> None:
    x, y = 40, HEIGHT - 160
    for dx in (-3, 0, 3):
        for dy in (-3, 0, 3):
            if dx or dy:
                draw.text((x + dx, y + dy), text, font=font, fill="black")
    draw.text((x, y), text, font=font, fill="white")
