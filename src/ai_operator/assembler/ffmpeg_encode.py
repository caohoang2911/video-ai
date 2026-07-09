"""ffmpeg-native encode: concat body segments, burn captions + mux ducked audio, join
intro/outro. Replaces MoviePy `write_videofile` (a documented ~10x regression in 2.x) with a
hardware `h264_videotoolbox` pass on Apple Silicon (libx264 fallback via env).

Body-first ordering matters: `captions.srt` and `narration.mp3` are narration-relative (t=0 =
first body beat). We burn/mux them onto the body ALONE, then stream-copy-concat the pre-built
intro/outro around the finished body -- so the intro's length never shifts the whole track.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..logging_setup import get_logger

log = get_logger("assembler.ffmpeg_encode")

FPS = 24
MUSIC_VOLUME = 0.2
FADE_SECONDS = 1.5
# ASS override: white text, black outline, bottom-centre, clear of the lower edge.
_SUB_STYLE = "FontSize=22,Outline=2,Shadow=0,BorderStyle=1,Alignment=2,MarginV=50,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000"


def _run(cmd: list[str], *, cwd: str | Path | None = None) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    if result.returncode != 0:
        log.error("ffmpeg failed (rc=%d): %s", result.returncode, result.stderr[-2000:])
        raise RuntimeError(f"ffmpeg failed (rc={result.returncode}); tail: {result.stderr[-400:]}")


def video_encode_args() -> list[str]:
    """Encoder args: M1 hardware `h264_videotoolbox` by default, `libx264` when
    `AI_OPERATOR_ENCODER=libx264` (CI / non-Apple / quality A-B)."""
    if os.environ.get("AI_OPERATOR_ENCODER", "").lower() == "libx264":
        return ["-c:v", "libx264", "-preset", "fast", "-crf", "20"]
    return ["-c:v", "h264_videotoolbox", "-b:v", "8M"]


def probe_duration(path: str | Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def concat_copy(inputs: list[Path], out: Path) -> Path:
    """Stream-copy concat (no re-encode) of same-spec MP4s via the concat demuxer. Inputs must
    share codec/pix_fmt/fps -- guaranteed here because every producer targets one 24fps spec."""
    out = Path(out)
    listing = out.parent / f"{out.stem}_concat.txt"
    listing.write_text("".join(f"file '{Path(p).resolve()}'\n" for p in inputs), encoding="utf-8")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)])
    listing.unlink(missing_ok=True)
    return out


def burn_and_mux(base: Path, srt: Path, narration: Path, music: str | Path | None, out: Path) -> Path:
    """ONE pass over the body: burn `srt` captions and mux narration (+ ducked, looped music)
    onto `base`, preserving base's own t=0. Runs with cwd=out.parent so the subtitles filter
    resolves the srt by basename (dodges libav path-escaping)."""
    base, srt, narration, out = Path(base), Path(srt), Path(narration), Path(out)
    dur = probe_duration(narration)
    fade = min(FADE_SECONDS, dur / 4) if dur else FADE_SECONDS
    vfilter = f"[0:v]subtitles={srt.name}:force_style='{_SUB_STYLE}'[vout]"

    cmd = ["ffmpeg", "-y", "-i", str(base), "-i", str(narration)]
    if music:
        cmd += ["-i", str(music)]
        afilter = (
            f"[2:a]aloop=loop=-1:size=2000000000,atrim=0:{dur:.3f},"
            f"volume={MUSIC_VOLUME},afade=t=in:d={fade:.3f},afade=t=out:st={max(0.0, dur - fade):.3f}:d={fade:.3f}[mus];"
            f"[1:a][mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        )
        filter_complex = f"{vfilter};{afilter}"
        amap = "[aout]"
    else:
        filter_complex = vfilter
        amap = "1:a"

    cmd += [
        "-filter_complex", filter_complex, "-map", "[vout]", "-map", amap,
        *video_encode_args(), "-r", str(FPS), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out),
    ]
    _run(cmd, cwd=out.parent)
    return out
