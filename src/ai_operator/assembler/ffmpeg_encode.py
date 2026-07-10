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
# Library tracks vary wildly in intrinsic loudness and some open with a long fade-in from
# digital silence, so a fixed gain (or a slow one-pass loudnorm) leaves the bed inaudible for
# the whole first minute. The bed chain instead: strips the silent lead-in, levels the track
# frame-by-frame (dynaudnorm converges from t=0), sets it at swell level, then sidechain-ducks
# it under the voice. Narration sits ~-18 dB RMS; 0.35 puts the leveled bed right at that level
# in narration rests (the reflective swell), and the duck (~8-12 dB whenever the voice is
# present) tucks it behind the speech the rest of the time.
MUSIC_BED_GAIN = 0.35
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


def concat_copy(inputs: list[Path], out: Path, *, audio_reencode: bool = False) -> Path:
    """Concat same-spec MP4s via the concat demuxer. Video is always stream-copied (no re-encode,
    no quality loss). `audio_reencode` re-encodes the audio to one uniform stereo AAC track --
    used for the final intro+body+outro join, where independently-encoded AAC segments otherwise
    carry per-segment encoder-priming that stream-copy can't reconcile (non-monotonic DTS at the
    boundaries). Inputs must share video codec/pix_fmt/fps (guaranteed: every producer targets 24fps)."""
    out = Path(out)
    listing = out.parent / f"{out.stem}_concat.txt"
    listing.write_text("".join(f"file '{Path(p).resolve()}'\n" for p in inputs), encoding="utf-8")
    codec = (
        ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "44100"]
        if audio_reencode else ["-c", "copy"]
    )
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), *codec, str(out)])
    listing.unlink(missing_ok=True)
    return out


def ambient_glow_fx(duration: float, size: tuple[int, int]) -> str:
    """`pre_fx` fragment for burn_and_mux: subtle life over stills-based footage — a slow
    drifting warm light-wash (animated gradients, screen blend at low opacity) plus a gentle
    two-frequency brightness flicker. Reads as haze and lamplight rather than a static frame."""
    w, h = size
    return (
        f"gradients=s={w}x{h}:c0=0x1a1206:c1=0xcdb37e:speed=0.02:d={duration + 1:.3f}[glow];"
        f"[0:v][glow]blend=all_mode=screen:all_opacity=0.10:shortest=1,"
        f"eq=eval=frame:brightness='0.015*sin(2*PI*t/1.9)+0.010*sin(2*PI*t/0.53)',"
        f"format=yuv420p[vpre]"
    )


def burn_and_mux(
    base: Path,
    srt: Path,
    narration: Path,
    music: str | Path | None,
    out: Path,
    *,
    sub_style: str = _SUB_STYLE,
    pre_fx: str | None = None,
    post_fx: str | None = None,
) -> Path:
    """ONE pass over the body: burn `srt` captions and mux narration (+ ducked, looped music)
    onto `base`, preserving base's own t=0. Runs with cwd=out.parent so the subtitles filter
    resolves the srt by basename (dodges libav path-escaping).

    `pre_fx`: optional filter_complex fragment applied UNDER the captions (ambient effects) —
    must consume `[0:v]` and label its output `[vpre]`; may instantiate lavfi sources.
    `post_fx`: optional filter chain applied ON TOP of the captions (e.g. a pinned title);
    plain chain body without labels. Both default off — the landscape path is unchanged."""
    base, srt, narration, out = Path(base), Path(srt), Path(narration), Path(out)
    dur = probe_duration(narration)
    fade = min(FADE_SECONDS, dur / 4) if dur else FADE_SECONDS
    # A speechless narration yields an empty SRT; the subtitles filter aborts on a 0-byte file,
    # so only burn captions when there are cues -- otherwise pass the base video straight through.
    has_caps = srt.exists() and srt.stat().st_size > 0

    parts: list[str] = []
    vin, vmap = "[0:v]", "0:v"
    if pre_fx:
        parts.append(pre_fx)
        vin = vmap = "[vpre]"
    if has_caps:
        parts.append(f"{vin}subtitles={srt.name}:force_style='{sub_style}'[vcap]")
        vin = vmap = "[vcap]"
    if post_fx:
        parts.append(f"{vin}{post_fx}[vout]")
        vmap = "[vout]"

    cmd = ["ffmpeg", "-y", "-i", str(base), "-i", str(narration)]
    if music:
        cmd += ["-i", str(music)]
        parts.append(
            f"[1:a]asplit=2[nmix][nsc];"
            # silent lead-in must go BEFORE the loop, or every loop pass replays the gap
            f"[2:a]silenceremove=start_periods=1:start_threshold=-40dB,"
            f"aloop=loop=-1:size=2000000000,atrim=0:{dur:.3f},"
            f"dynaudnorm=f=500:g=31:m=30,volume={MUSIC_BED_GAIN},"
            f"afade=t=in:d={fade:.3f},afade=t=out:st={max(0.0, dur - fade):.3f}:d={fade:.3f}[bed];"
            # duck the bed under the voice; in narration rests it swells back over ~0.6s
            f"[bed][nsc]sidechaincompress=threshold=0.04:ratio=6:attack=80:release=600:makeup=1[duck];"
            f"[nmix][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            # swelled bed peaks higher than the old fixed-gain one; cap rare coincident peaks
            f"alimiter=limit=0.891[aout]"
        )
        amap = "[aout]"
    else:
        amap = "1:a"

    if parts:
        cmd += ["-filter_complex", ";".join(parts)]
    cmd += [
        "-map", vmap, "-map", amap,
        *video_encode_args(), "-r", str(FPS), "-pix_fmt", "yuv420p",
        # Narration is mono; force stereo 44100 so the body matches the intro/outro cards exactly
        # and the final stream-copy concat produces a spec-conformant MP4 (YouTube ingest).
        "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "44100",
        "-movflags", "+faststart", str(out),
    ]
    _run(cmd, cwd=out.parent)
    return out
