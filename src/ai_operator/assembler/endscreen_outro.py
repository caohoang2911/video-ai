"""Synthesize the end-screen outro card: a 12s dark card whose layout reserves the exact
zones where YouTube overlays its interactive end-screen elements (elements are added once
in Studio, then re-applied per upload via "Import from video").

Geometry is YouTube's fixed 1080p element footprint: the next-video element renders at
~615x345 and the round subscribe element inside a ~294x294 box, and elements may only run
in the last 5-20s of a video. Faint outline boxes are drawn so the Studio elements can be
dragged onto them pixel-close one time. Text sits in the top third; everything below the
zones stays clear of the progress-bar / caption strip.

Audio: the body's music bed fades out over its own last 1.5s (see ffmpeg_encode), so this
card fades the same track back in at bed level -- it reads as an outro sting, and no
sample-accurate seam matching is needed at the concat boundary. Without a music path the
card carries silence (the pre-end-screen behaviour).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from .ffmpeg_encode import FPS, MUSIC_BED_GAIN, _run, video_encode_args

WIDTH, HEIGHT = 1920, 1080
# Elements may run 5-20s; 10-15s is the retention sweet spot (long enough to click,
# short enough that the tail of the retention graph doesn't crater).
OUTRO_SECONDS = 12.0
BG_HEX = "0x140a0a"

# YouTube's fixed element footprint at 1080p, kept inside a ~96px safe margin:
# (x, y, w, h). SUB_ZONE is the bounding box of the round subscribe element.
VIDEO_ZONE = (192, 390, 615, 345)
SUB_ZONE = (1393, 413, 294, 294)

# Copy deliberately avoids goodbye phrasing ("thanks for watching") -- a sign-off tells
# the viewer the session is over; an invitation hands them the next story instead.
# HEADLINE is inlined into the drawtext filter string: it must stay free of ffmpeg
# filter metacharacters (apostrophes, colons, commas, %) or go through a textfile.
HEADLINE = "The story continues..."
FALLBACK_TEASER = "Another forgotten story is waiting - right here."
_TEASER_WRAP_COLS = 56
_FADE_IN, _FADE_OUT = 1.0, 2.5


def _label(text: str, cx: int, y: int, font: str) -> str:
    """A small caption centered on x=cx, pointing the eye at a reserved zone."""
    return (
        f"drawtext=fontfile='{font}':text='{text}':fontcolor=white@0.85:fontsize=30:"
        f"x={cx}-text_w/2:y={y}"
    )


def build_endscreen_outro(
    out: Path, *, font: str, teaser: str | None = None, music: str | Path | None = None
) -> Path:
    """Render the outro card at the exact concat spec (1920x1080, 24fps CFR, yuv420p,
    stereo AAC 44100) so the final stream-copy join never re-encodes video."""
    out = Path(out)
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

    vx, vy, vw, vh = VIDEO_ZONE
    sx, sy, sw, sh = SUB_ZONE
    video_chain = ",".join(
        [
            f"drawbox=x={vx}:y={vy}:w={vw}:h={vh}:color=white@0.25:t=3",
            f"drawbox=x={sx}:y={sy}:w={sw}:h={sh}:color=white@0.25:t=3",
            f"drawtext=fontfile='{font}':text='{HEADLINE}':fontcolor=white:fontsize=60:"
            "x=(w-text_w)/2:y=130",
            *(
                f"drawtext=fontfile='{font}':textfile={f.name}:fontcolor=0xd0d0d0:"
                f"fontsize=38:x=(w-text_w)/2:y={215 + i * 54}"
                for i, f in enumerate(teaser_files)
            ),
            _label("WATCH NEXT", vx + vw // 2, vy - 52, font),
            _label("SUBSCRIBE", sx + sw // 2, sy - 52, font),
        ]
    )

    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={BG_HEX}:s={WIDTH}x{HEIGHT}:r={FPS}"]
    if music and Path(music).exists():
        cmd += ["-i", str(music)]
        # Same leveling chain as the body bed (minus the voice duck -- there is no voice)
        # so the outro sits at the familiar swell loudness, then eases out before the end.
        audio_chain = (
            "[1:a]silenceremove=start_periods=1:start_threshold=-40dB,"
            f"aloop=loop=-1:size=2000000000,atrim=0:{OUTRO_SECONDS:.3f},"
            f"dynaudnorm=f=500:g=31:m=30,volume={MUSIC_BED_GAIN},"
            f"afade=t=in:d={_FADE_IN:.3f},"
            f"afade=t=out:st={OUTRO_SECONDS - _FADE_OUT:.3f}:d={_FADE_OUT:.3f}[aout]"
        )
        filter_complex = f"[0:v]{video_chain}[vout];{audio_chain}"
        maps = ["-map", "[vout]", "-map", "[aout]"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        filter_complex = f"[0:v]{video_chain}[vout]"
        maps = ["-map", "[vout]", "-map", "1:a"]

    cmd += [
        "-filter_complex", filter_complex, *maps, "-t", f"{OUTRO_SECONDS}",
        *video_encode_args(), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", str(out),
    ]
    try:
        _run(cmd, cwd=out.parent)
    finally:
        for f in teaser_files:
            f.unlink(missing_ok=True)
    return out
