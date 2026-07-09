"""Ken Burns effect pre-rendered via FFmpeg `zoompan` (subprocess), one MP4 segment per
beat. MoviePy's native zoom re-rasterizes every frame in Python and is CPU-heavy at scale;
shelling out to FFmpeg's compiled zoompan filter is far cheaper for a batch of 10-30 stills.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..logging_setup import get_logger

log = get_logger("assembler.kenburns")

# ONE project-wide fps. Ken Burns stills, b-roll normalize, branding cards, and every concat
# boundary all run at 24 so mixed segments never inflate the timeline or desync burned captions.
FPS = 24
WIDTH, HEIGHT = 1920, 1080
MAX_ZOOM = 1.3
ZOOM_STEP = 0.0015


def render_segment(image_path: str | Path, duration: float, out_path: str | Path, zoom_in: bool) -> Path:
    """Render one Ken Burns MP4 segment from a still image.

    `zoom_in=True` zooms 1.0 -> MAX_ZOOM over the clip; `False` zooms MAX_ZOOM -> 1.0.
    Alternating direction per beat (caller's job) avoids every shot in the video zooming
    the same way, which reads as visually monotonous over a 10-minute runtime.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"beat image not found: {image_path}")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    frames = max(1, int(round(duration * FPS)))
    if zoom_in:
        zoom_expr = f"min(zoom+{ZOOM_STEP},{MAX_ZOOM})"
    else:
        # start already zoomed-in on frame 1, then relax back out to 1.0
        zoom_expr = f"if(eq(on,1),{MAX_ZOOM},max(zoom-{ZOOM_STEP},1.0))"

    # Upscale 2x before zoompan so the filter has sub-pixel headroom to pan/zoom without
    # visible stair-stepping on the final 1080p output.
    vf = (
        f"scale={WIDTH * 2}:{HEIGHT * 2},"
        f"zoompan=z='{zoom_expr}':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"
    )
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", str(image_path),
        "-vf", vf,
        # ultrafast + near-lossless crf: this segment is an intermediate the encode pass re-reads
        # and re-encodes, so spend no time on its compression -- keep quality (crf 18) but not speed.
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-t", f"{duration:.3f}", "-r", str(FPS), "-pix_fmt", "yuv420p", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("ffmpeg zoompan failed for %s: %s", image_path, result.stderr[-2000:])
        raise RuntimeError(f"ffmpeg zoompan failed for {image_path} (rc={result.returncode})")
    return out_path


def render_segments(
    shot_list: list[dict], durations: list[float], img_dir: str | Path, out_dir: str | Path
) -> list[Path]:
    """Render every beat's image into a Ken Burns segment, in shot_list order."""
    img_dir = Path(img_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    segments = []
    for i, (beat, duration) in enumerate(zip(shot_list, durations)):
        image_path = img_dir / f"beat_{beat['beat_id']:02d}.jpg"
        out_path = out_dir / f"seg_{i:02d}.mp4"
        render_segment(image_path, duration, out_path, zoom_in=(i % 2 == 0))
        segments.append(out_path)
    return segments
