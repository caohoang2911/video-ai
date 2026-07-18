"""Synthesize the end-screen outro card: a 12s dark card with a headline + teaser in the top
third, leaving the lower area clear for YouTube's interactive end-screen elements (next-video
+ subscribe), which are added once in Studio and re-applied per upload via "Import from video".

Elements may only run in the last 5-20s of a video and YouTube overlays them itself. This card
draws NO outline guides — it keeps the headline + teaser in the top third so the text never
collides with the next-video / subscribe elements YouTube renders below.

Audio: the body's music bed fades out over its own last 1.5s (see ffmpeg_encode), so this
card fades the same track back in at bed level -- it reads as an outro sting, and no
sample-accurate seam matching is needed at the concat boundary. Without a music path the
card carries silence (the pre-end-screen behaviour). An optional spoken outro (the seal->
point handoff, brand narrator voice) is voiced over the card -- the music bed ducks under it
like the body mux, and the card stretches to cover the speech up to the 20s element cap.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

from ..logging_setup import get_logger
from . import kenburns_ffmpeg
from .ffmpeg_encode import FPS, MUSIC_BED_GAIN, _run, probe_duration, video_encode_args

log = get_logger("assembler.endscreen_outro")

WIDTH, HEIGHT = 1920, 1080
# Elements may run 5-20s; 10-15s is the retention sweet spot (long enough to click,
# short enough that the tail of the retention graph doesn't crater).
OUTRO_SECONDS = 12.0
# A spoken outro can push the card longer, but YouTube shows end-screen elements for at most
# 20s; keep the card inside that window, with a tail so the music breathes out after the words.
OUTRO_MAX_SECONDS = 20.0
OUTRO_VOICE_TAIL = 2.0
BG_HEX = "0x140a0a"

# Copy deliberately avoids goodbye phrasing ("thanks for watching") -- a sign-off tells
# the viewer the session is over; an invitation hands them the next story instead.
# HEADLINE is inlined into the drawtext filter string: it must stay free of ffmpeg
# filter metacharacters (apostrophes, colons, commas, %) or go through a textfile.
HEADLINE = "The story continues..."
# Empty-field default: mirrors the script prompt's seal-then-open teaser shape -- one
# forgotten story closes, the next is already waiting (evergreen, never a specific video).
FALLBACK_TEASER = "One forgotten story closes - another is already waiting."
_TEASER_WRAP_COLS = 56
_FADE_IN, _FADE_OUT = 1.0, 2.5
# Documentary backdrop for the closing still (the last beat's image): darken for text contrast,
# reuse the body's archival grade (desaturate + fine grain) so it matches the film, soften to a
# backdrop, plus a gentle brightness breathe. Text fades in over its first second.
_BACKDROP_DARKEN = -0.28
_BACKDROP_BLUR = 5
_GLOW = "eq=eval=frame:brightness='0.015*sin(2*PI*t/1.9)+0.010*sin(2*PI*t/0.53)'"
_TEXT_FADE_IN = "alpha='if(lt(t,1),t,1)'"


def _decodable_image(path: str | Path) -> bool:
    """Fast decode gate before the backdrop render. A corrupt/partial image makes
    render_segment's `-loop 1` SPIN (not error), which would hang the whole assemble -- and the
    outro renders before the body segments, so it's the first to hit a bad beat image. ffprobe
    alone is too lenient (it reports a stream for garbage named `.jpg`), so actually decode one
    frame -- WITHOUT `-loop`, so a bad file fails fast -- turning a hang into a flat-dark fallback."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "null", "-"],
            capture_output=True, timeout=15,
        )
        return r.returncode == 0
    except Exception:  # noqa: BLE001 - decode failure/timeout => treat as undecodable, fall back
        return False


def build_endscreen_outro(
    out: Path,
    *,
    font: str,
    teaser: str | None = None,
    music: str | Path | None = None,
    voice: str | Path | None = None,
    backdrop_image: str | Path | None = None,
) -> Path:
    """Render the outro card at the exact concat spec (1920x1080, 24fps CFR, yuv420p,
    stereo AAC 44100) so the final stream-copy join never re-encodes video.

    With `voice` (the spoken seal->point handoff) the card grows to cover the speech -- up to
    YouTube's 20s element ceiling -- and the music bed ducks under the voice exactly like the
    body mux; without it the card keeps its fixed 12s of music-or-silence.

    With `backdrop_image` (the closing beat's still) the card plays that image Ken-Burns'd and
    archival-graded + darkened under the text -- a documentary closing frame instead of a flat
    black screen. Best-effort: an unreadable image falls back to the flat dark card."""
    out = Path(out)
    music_path = Path(music) if music and Path(music).exists() else None
    voice_path = Path(voice) if voice and Path(voice).exists() else None

    # A silent card is a flat 12s; a spoken one stretches to fit the voice (plus a tail so the
    # music breathes back in after the last word), never past the 20s end-screen ceiling.
    seconds = OUTRO_SECONDS
    if voice_path:
        try:
            seconds = min(OUTRO_MAX_SECONDS, max(OUTRO_SECONDS, probe_duration(voice_path) + OUTRO_VOICE_TAIL))
        except Exception as exc:  # noqa: BLE001 - an unreadable/corrupt voice must not abort the render
            log.warning("outro voice unreadable (%s) — rendering the card without the spoken outro", exc)
            voice_path = None
    if music_path:
        # Gate the bed the same way: a 0-byte/corrupt music file fed to ffmpeg aborts the whole
        # render, so probe it first and drop it to a silent card rather than crash.
        try:
            probe_duration(music_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("outro music unreadable (%s) — rendering the card without the music bed", exc)
            music_path = None
    fade_out_st = max(0.0, seconds - _FADE_OUT)

    # Documentary backdrop: the closing still, Ken-Burns'd + archival-graded + darkened, so the
    # card reads like the film's final frame instead of a dead black screen. Best-effort -- any
    # render failure (unreadable image, ffmpeg error) falls back to the flat dark card.
    backdrop: Path | None = None
    if backdrop_image and Path(backdrop_image).exists() and not _decodable_image(backdrop_image):
        log.warning("outro backdrop image not decodable (%s) — flat dark card", backdrop_image)
    elif backdrop_image and Path(backdrop_image).exists():
        candidate = out.parent / f"{out.stem}_backdrop.mp4"
        try:
            kenburns_ffmpeg.render_segment(
                backdrop_image, seconds, candidate, motion="zoom_in",
                extra_vf=(
                    f"eq=brightness={_BACKDROP_DARKEN},{kenburns_ffmpeg.ARCHIVAL_GRADE_VF},"
                    f"gblur=sigma={_BACKDROP_BLUR},vignette,{_GLOW}"
                ),
            )
            backdrop = candidate
        except Exception as exc:  # noqa: BLE001 - a backdrop is polish, never a render blocker
            log.warning("outro backdrop render failed (%s) — flat dark card", exc)
            candidate.unlink(missing_ok=True)

    # drawtext reads the teaser from files (like the branding cards) to dodge ffmpeg
    # filter-escaping of arbitrary LLM copy; resolved by basename via cwd=out.parent.
    # One file per wrapped line: drawtext left-aligns lines inside a multi-line block,
    # so each line is drawn separately to keep the whole teaser visually centered.
    lines = textwrap.wrap((teaser or "").strip() or FALLBACK_TEASER, _TEASER_WRAP_COLS)[:2]
    teaser_files: list[Path] = []
    for i, line in enumerate(lines):
        f = out.parent / f"{out.stem}_teaser{i}.txt"
        f.write_text(line, encoding="utf-8")
        teaser_files.append(f)

    # Headline + teaser only — no next-video / subscribe outline guides (YouTube overlays the
    # real interactive elements itself; the drawn boxes were removed).
    video_chain = ",".join(
        [
            f"drawtext=fontfile='{font}':text='{HEADLINE}':fontcolor=white:borderw=3:"
            f"bordercolor=black:fontsize=60:x=(w-text_w)/2:y=130:{_TEXT_FADE_IN}",
            *(
                f"drawtext=fontfile='{font}':textfile={f.name}:fontcolor=0xe6e6e6:borderw=2:"
                f"bordercolor=black:fontsize=38:x=(w-text_w)/2:y={215 + i * 54}:{_TEXT_FADE_IN}"
                for i, f in enumerate(teaser_files)
            ),
        ]
    )
    # A backdrop rendered from a JPEG is full-range (yuvj420p); the concat spec (and the body/intro)
    # is limited-range yuv420p, and the final stream-copy join needs matching pix_fmt -- so convert
    # the range on the backdrop path. The flat color source is already limited yuv420p.
    if backdrop is not None:
        video_chain += f",scale={WIDTH}:{HEIGHT}:out_range=tv,format=yuv420p"

    # Input 0 = the graded documentary backdrop clip when present, else a flat dark color source.
    if backdrop is not None:
        cmd = ["ffmpeg", "-y", "-i", str(backdrop)]
    else:
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={BG_HEX}:s={WIDTH}x{HEIGHT}:r={FPS}"]
    next_input = 1
    music_i = voice_i = None
    if music_path:
        cmd += ["-i", str(music_path)]
        music_i = next_input
        next_input += 1
    if voice_path:
        cmd += ["-i", str(voice_path)]
        voice_i = next_input
        next_input += 1

    # Same leveling chain as the body bed: strip the silent lead-in, level frame-by-frame, set
    # at swell loudness, fade in/out. When a voice is present the bed is ducked under it below.
    bed = (
        f"[{music_i}:a]silenceremove=start_periods=1:start_threshold=-40dB,"
        f"aloop=loop=-1:size=2000000000,atrim=0:{seconds:.3f},"
        f"dynaudnorm=f=500:g=31:m=30,volume={MUSIC_BED_GAIN},"
        f"afade=t=in:d={_FADE_IN:.3f},afade=t=out:st={fade_out_st:.3f}:d={_FADE_OUT:.3f}"
    ) if music_i is not None else None

    if voice_i is not None:
        # The voice is mono at natural speech level; pad it out to the whole card so amix lines
        # up and the bed can swell back after the words end. Fade only the trailing tail (the
        # padded silence after the last word), never the speech itself -- so the closing CTA
        # lands at full level. The bed keeps its own longer 2.5s musical fade below.
        vox_fade_st = max(0.0, seconds - OUTRO_VOICE_TAIL)
        vox = (
            f"[{voice_i}:a]aresample=44100,apad,atrim=0:{seconds:.3f},"
            f"afade=t=out:st={vox_fade_st:.3f}:d={OUTRO_VOICE_TAIL:.3f}"
        )
        if bed is not None:
            audio_chain = (
                f"{bed}[bed];"
                f"{vox},asplit=2[vmix][vsc];"
                # duck the bed under the voice (same feel as the body mux), blend, cap peaks
                f"[bed][vsc]sidechaincompress=threshold=0.04:ratio=6:attack=80:release=600:makeup=1[duck];"
                f"[vmix][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                f"alimiter=limit=0.891[aout]"
            )
        else:
            audio_chain = f"{vox}[aout]"
        filter_complex = f"[0:v]{video_chain}[vout];{audio_chain}"
        maps = ["-map", "[vout]", "-map", "[aout]"]
    elif bed is not None:
        filter_complex = f"[0:v]{video_chain}[vout];{bed}[aout]"
        maps = ["-map", "[vout]", "-map", "[aout]"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        filter_complex = f"[0:v]{video_chain}[vout]"
        maps = ["-map", "[vout]", "-map", f"{next_input}:a"]

    cmd += [
        "-filter_complex", filter_complex, *maps, "-t", f"{seconds}",
        *video_encode_args(), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", str(out),
    ]
    try:
        _run(cmd, cwd=out.parent)
    finally:
        for f in teaser_files:
            f.unlink(missing_ok=True)
        if backdrop is not None:
            backdrop.unlink(missing_ok=True)
    return out
