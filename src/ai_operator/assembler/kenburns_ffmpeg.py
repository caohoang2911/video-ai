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

# Motion vocabulary cycled per beat: only gentle push-in / pull-back, alternated so
# adjacent shots differ. `zoom_in` starts on the FULL frame then eases in (reveal-first);
# `zoom_out` ends on the full frame (pull-back-to-reveal) -- either way the whole
# composition is on screen at one end of every beat. Lateral pans (pan_lr/pan_rl) are still
# implemented in `_motion_exprs` but deliberately OUT of the default rotation: a sideways
# pan never shows the full image and, on a long beat, travels far enough that the subject
# slides off frame -- the "never see the whole picture" complaint.
MOTIONS = ("zoom_in", "zoom_out")
# Professional documentary practice zooms archival stills only ~10% over a shot (1.0->1.10);
# the old 1.28/1.38 pushed so hard that a long beat cropped the subject out. Portrait (Shorts)
# keeps a touch more since subtle motion reads as frozen on a small phone screen.
TARGET_ZOOM = 1.12
TARGET_ZOOM_PORTRAIT = 1.18

# Zoom anchors the image center; the zoompan default (x=0,y=0) pins the top-left corner,
# which drifts the subject off-frame on portraits and reads as sloppy framing.
_CENTER_X = "iw/2-(iw/zoom/2)"
_CENTER_Y = "ih/2-(ih/zoom/2)"


# Unifying treatment for archival photographs: gentle desaturation + contrast lift + fine
# grain so a real 1910s photo and a stylized generated still cut together without a visual
# jolt. Applied at RENDER time only -- the downloaded original stays untouched on disk as
# the licensing/audit copy.
ARCHIVAL_GRADE_VF = "hue=s=0.35,eq=contrast=1.06:brightness=0.02,noise=alls=6:allf=t"


def motion_for_index(i: int) -> str:
    """Per-beat motion variant. Callers pass the beat index; alternating the cycle
    guarantees adjacent beats move in opposite directions (push-in vs pull-back)."""
    return MOTIONS[i % len(MOTIONS)]


# Dip-to-black fade length applied at a beat boundary (fade out end of one image, fade in
# start of the next). Short enough to read as a breath between scenes, not a slideshow.
DIP_FADE_SECONDS = 0.2


def _motion_exprs(motion: str, frames: int, target: float) -> tuple[str, str, str]:
    """(zoom, x, y) zoompan expressions for one segment.

    The zoom step derives from the segment's own frame count so motion spans 100% of the
    clip regardless of duration. A fixed global step would hit the zoom target after a
    constant wall-time (~8s at the old 0.0015/frame) and freeze for the rest of any
    longer beat -- the "dead photo" tail on long-form videos.
    """
    n = max(frames - 1, 1)
    step = (target - 1.0) / n
    # Zoom is a pure function of the output frame index `on`, NOT the stateful `zoom` var.
    # The old zoom_out used `if(eq(on,1),target,max(zoom-step,1.0))`: frame 0 (on=0) fell to
    # the else branch and rendered at zoom 1.0 (wide), then frame 1 snapped to `target` --
    # a 1-frame "flash wide then punch in" at the start of every zoom-out beat. A linear
    # function of `on` starts cleanly at the right zoom with no snap.
    if motion == "zoom_in":
        return f"min(1.0+{step:.8f}*on,{target})", _CENTER_X, _CENTER_Y
    if motion == "zoom_out":
        return f"max({target}-{step:.8f}*on,1.0)", _CENTER_X, _CENTER_Y
    # Pans: constant zoom, x sweeps the hidden width; min/max clamp keeps x valid if -t
    # rounds the output a frame past `n`.
    span = "(iw-iw/zoom)"
    if motion == "pan_lr":
        return f"{target}", f"min({span}*on/{n},{span})", _CENTER_Y
    if motion == "pan_rl":
        return f"{target}", f"max({span}*(1-on/{n}),0)", _CENTER_Y
    raise ValueError(f"unknown motion {motion!r} (expected one of {MOTIONS})")


def render_segment(
    image_path: str | Path,
    duration: float,
    out_path: str | Path,
    motion: str = "zoom_in",
    size: tuple[int, int] = (WIDTH, HEIGHT),
    extra_vf: str | None = None,
    target_zoom: float | None = None,
    fade_in: bool = False,
    fade_out: bool = False,
) -> Path:
    """Render one Ken Burns MP4 segment from a still image.

    `motion` is one of MOTIONS (see `motion_for_index` for the per-beat cycle).
    `size` defaults to landscape; the Shorts builder passes 1080x1920 -- portrait output
    automatically gets the stronger TARGET_ZOOM_PORTRAIT unless `target_zoom` overrides.
    `extra_vf` appends a filter chain after zoompan (e.g. ARCHIVAL_GRADE_VF).
    `fade_in`/`fade_out` add a short black dip at the head/tail (beat-boundary transition).
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"beat image not found: {image_path}")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    w, h = size
    frames = max(1, int(round(duration * FPS)))
    target = target_zoom if target_zoom else (TARGET_ZOOM if w >= h else TARGET_ZOOM_PORTRAIT)
    z_expr, x_expr, y_expr = _motion_exprs(motion, frames, target)

    # Upscale 2x before zoompan so the filter has sub-pixel headroom to pan/zoom without
    # visible stair-stepping on the final output. Sources arrive in mixed aspects (square
    # SDXL, tall archival scans), so cover-crop to the target aspect and pin SAR=1: a bare
    # `scale` would instead compensate SAR to preserve the source aspect, and that flag —
    # carried through zoompan into the concat — makes players letterbox the whole video
    # (e.g. a 16:9 main displayed as a square with black side bars).
    vf = (
        f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,"
        f"crop={w * 2}:{h * 2},setsar=1,"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={frames}:s={w}x{h}:fps={FPS}"
    )
    if extra_vf:
        vf += f",{extra_vf}"
    # Dip-to-black runs LAST so it darkens the final framed+graded image. fade-out anchors to
    # the real clip length so the black lands exactly on the cut.
    if fade_in:
        vf += f",fade=t=in:st=0:d={DIP_FADE_SECONDS}"
    if fade_out:
        vf += f",fade=t=out:st={max(0.0, duration - DIP_FADE_SECONDS):.3f}:d={DIP_FADE_SECONDS}"
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
        render_segment(image_path, duration, out_path, motion=motion_for_index(i))
        segments.append(out_path)
    return segments
