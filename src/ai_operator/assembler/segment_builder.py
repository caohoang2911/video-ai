"""Per-beat segment builder: one 1920x1080@24fps silent MP4 per beat, either motion b-roll or
a Ken Burns still. This is the ONLY 5b-specific piece -- everything downstream (concat, caption
burn, audio mux, encode, cleanup in ffmpeg_encode/video_builder) is unchanged from the 5a path.

A beat uses motion when it has a `video_broll` Asset row AND that file still exists on disk;
otherwise it falls back to Ken Burns on `img/beat_NN.jpg`. Selection is driven by DB rows (not a
`broll/*.mp4` glob) so a stray/orphaned clip without an Asset can never be picked.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select

from ..db.engine import SessionLocal
from ..db.models import Asset
from ..logging_setup import get_logger
from . import kenburns_ffmpeg
from .ffmpeg_encode import FPS, _run

log = get_logger("assembler.segment_builder")

_BEAT_RE = re.compile(r"beat_(\d+)")


def _broll_by_beat(video_id: int) -> dict[int, Path]:
    """beat_id -> normalized b-roll clip path, from `video_broll` Asset rows whose file exists.
    Beat id is parsed from the filename (`broll/beat_NN.mp4`); the Asset table has no beat column."""
    with SessionLocal() as s:
        rows = s.execute(
            select(Asset).where(Asset.video_id == video_id, Asset.kind == "video_broll")
        ).scalars().all()
    out: dict[int, Path] = {}
    for r in rows:
        p = Path(r.url_or_path)
        m = _BEAT_RE.search(p.name)
        if m and p.exists():
            out[int(m.group(1))] = p
    return out


def _broll_segment(src: Path, duration: float, out: Path) -> Path:
    """Fit one normalized b-roll clip to EXACTLY `duration`: `-stream_loop -1` repeats a clip
    shorter than the beat, `-t` trims a longer one. Re-encoded (ultrafast -- it is re-encoded
    again downstream) and silenced; already 1920x1080, so fps/sar are just re-affirmed for concat."""
    cmd = [
        "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(src),
        "-t", f"{duration:.3f}",
        "-vf", f"fps={FPS},setsar=1,format=yuv420p",
        "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS), str(out),
    ]
    _run(cmd)
    return out


def build_segments(
    shot_list: list[dict], durations: list[float], video_id: int, img_dir: Path, out_dir: Path
) -> list[Path]:
    """One segment per beat in shot_list order: motion b-roll where available, else Ken Burns still."""
    img_dir, out_dir = Path(img_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    broll = _broll_by_beat(video_id)
    n_motion = 0

    segments: list[Path] = []
    for i, (beat, duration) in enumerate(zip(shot_list, durations)):
        beat_id = beat["beat_id"]
        out = out_dir / f"seg_{i:02d}.mp4"
        if beat_id in broll:
            _broll_segment(broll[beat_id], duration, out)
            n_motion += 1
        else:
            kenburns_ffmpeg.render_segment(
                img_dir / f"beat_{beat_id:02d}.jpg", duration, out, zoom_in=(i % 2 == 0)
            )
        segments.append(out)

    log.info("video %s: %d/%d beats use motion b-roll (rest Ken Burns stills)", video_id, n_motion, len(segments))
    return segments
