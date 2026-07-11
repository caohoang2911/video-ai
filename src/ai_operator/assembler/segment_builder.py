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

# `beat_NN.mp4` (first/only clip) or `beat_NN_KK.mp4` (extra montage clips); excludes `.raw.mp4`.
_BEAT_RE = re.compile(r"^beat_(\d+)(?:_(\d+))?\.mp4$")
_BEAT_IMG_RE = re.compile(r"^beat_(\d+)\.jpg$")


def _archival_beats(video_id: int) -> set[int]:
    """beat_ids whose still is a Wikimedia archival photo (Asset kind='archival') -- those
    Ken Burns segments get the unifying grade so real photos cut cleanly against generated
    stills. Beat id parsed from the filename (the Asset table has no beat column)."""
    with SessionLocal() as s:
        rows = s.execute(
            select(Asset.url_or_path).where(Asset.video_id == video_id, Asset.kind == "archival")
        ).scalars().all()
    out: set[int] = set()
    for p in rows:
        m = _BEAT_IMG_RE.match(Path(p).name)
        if m:
            out.add(int(m.group(1)))
    return out


def _broll_by_beat(video_id: int) -> dict[int, list[Path]]:
    """beat_id -> ordered list of normalized b-roll clip paths, from `video_broll` Asset rows
    whose file exists. A beat may carry several montage clips; they're ordered by clip index so
    the scene plays them back-to-back. Beat/index are parsed from the filename (the Asset table
    has no beat column)."""
    with SessionLocal() as s:
        rows = s.execute(
            select(Asset).where(Asset.video_id == video_id, Asset.kind == "video_broll")
        ).scalars().all()
    indexed: dict[int, list[tuple[int, Path]]] = {}
    for r in rows:
        p = Path(r.url_or_path)
        m = _BEAT_RE.match(p.name)
        if m and p.exists():
            beat_id, idx = int(m.group(1)), int(m.group(2) or 0)
            indexed.setdefault(beat_id, []).append((idx, p))
    return {b: [p for _, p in sorted(pairs)] for b, pairs in indexed.items()}


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


def _broll_montage_segment(clips: list[Path], duration: float, out: Path) -> Path:
    """Fill a beat with its DISTINCT clips played back-to-back (concat demuxer), looping the
    whole sequence only if the clips together are still shorter than `duration` -- far less
    visible repetition than looping a single short clip. A single-clip beat uses the plain
    loop-and-trim path. Clips are already 1920x1080@24fps (normalized), so concat is safe."""
    if len(clips) == 1:
        return _broll_segment(clips[0], duration, out)
    list_file = out.with_name(f"{out.stem}.concat.txt")
    list_file.write_text("".join(f"file '{c.resolve()}'\n" for c in clips), encoding="utf-8")
    cmd = [
        "ffmpeg", "-y", "-stream_loop", "-1", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-t", f"{duration:.3f}",
        "-vf", f"fps={FPS},setsar=1,format=yuv420p",
        "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS), str(out),
    ]
    try:
        _run(cmd)
    finally:
        list_file.unlink(missing_ok=True)
    return out


def build_segments(
    shot_list: list[dict], durations: list[float], video_id: int, img_dir: Path, out_dir: Path
) -> list[Path]:
    """One segment per beat in shot_list order: motion b-roll where available, else Ken Burns still."""
    img_dir, out_dir = Path(img_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    broll = _broll_by_beat(video_id)
    archival = _archival_beats(video_id)
    n_motion = 0

    segments: list[Path] = []
    for i, (beat, duration) in enumerate(zip(shot_list, durations)):
        beat_id = beat["beat_id"]
        out = out_dir / f"seg_{i:02d}.mp4"
        if beat_id in broll:
            _broll_montage_segment(broll[beat_id], duration, out)
            n_motion += 1
        else:
            kenburns_ffmpeg.render_segment(
                img_dir / f"beat_{beat_id:02d}.jpg", duration, out, zoom_in=(i % 2 == 0),
                # ảnh tư liệu thật đi qua lớp grade đồng nhất để hoà với still SDXL
                extra_vf=kenburns_ffmpeg.ARCHIVAL_GRADE_VF if beat_id in archival else None,
            )
        segments.append(out)

    log.info("video %s: %d/%d beats use motion b-roll (rest Ken Burns stills)", video_id, n_motion, len(segments))
    return segments
