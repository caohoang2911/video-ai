"""ffmpeg batch-normalize downloaded b-roll to ONE uniform format so the assembler can concat
clips without seams.

Source stock clips arrive at mixed fps (23.976/25/29.97/30), mixed resolution (720p-4K), and
mixed aspect ratios. They all emerge here at 1920x1080, 24fps CFR, yuv420p, square pixels,
with audio stripped -- b-roll audio is never used (narration + ducked music are muxed later),
so dropping it avoids stray audio streams tripping up the concat step. One project fps (24)
is locked here to match the stills/Ken Burns path and prevent concat-boundary duration drift.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..logging_setup import get_logger

log = get_logger("video_normalize")

TARGET_W, TARGET_H, TARGET_FPS = 1920, 1080, 24

# decrease-scale into the frame, then letterbox-pad to exactly 1920x1080 (never up-stretch or
# crop), force CFR 24fps, and square the pixel aspect so downstream concat sees identical specs.
_VF = (
    f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
    f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2,"
    f"fps={TARGET_FPS},setsar=1"
)


def normalize(src: Path, dst: Path, *, crf: int = 20) -> Path:
    """Re-encode `src` to 1920x1080@24fps CFR, audio stripped, -> `dst`; raises on ffmpeg error.

    Uses libx264 (portable, deterministic) for this intermediate pass -- the final publish
    encode picks its own codec. `dst` is written atomically enough for the pipeline: a failed
    run raises before any caller records the asset, so a half-written file is never persisted.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-vf", _VF,
        "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-an", str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg normalize failed for {src.name}: {result.stderr[-500:]}")
    return dst
