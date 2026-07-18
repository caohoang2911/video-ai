"""Intro/outro branding cards + shared caption font lookup.

The render path is pure ffmpeg (no MoviePy), so intro/outro are synthesized as real MP4 cards
(`color` background + `drawtext` + silent `anullsrc`) at the EXACT segment spec -- 1920x1080,
24fps CFR, yuv420p, setsar=1, stereo AAC -- so the final stream-copy concat around the body
never re-encodes and never hits a spec mismatch. A user-supplied intro.mp4/outro.mp4 (dropped
in assets/branding/) is normalized through the same filter chain instead.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

from ..logging_setup import get_logger
from . import endscreen_outro
from .ffmpeg_encode import FPS, _run, video_encode_args

log = get_logger("assembler.branding")

BRANDING_DIR = Path(__file__).resolve().parents[3] / "assets" / "branding"
CARD_SECONDS = 3.0
WIDTH, HEIGHT = 1920, 1080
_WRAP_COLS = 26
# Cold-open title overlay: how long the title rides the opening of the BODY (narration
# already speaking underneath) before it is fully gone. Short fades so the hook image is
# never covered for long.
COLD_OPEN_TITLE_SECONDS = 4.5
_COLD_OPEN_FADE_IN = 0.6
_COLD_OPEN_FADE_OUT = 0.8
_COLD_OPEN_WRAP_COLS = 34
_MACOS_FONTS = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)


def font_path() -> str | None:
    """Shared branded caption font, or None to fall back to the library default."""
    ttf = BRANDING_DIR / "caption.ttf"
    return str(ttf) if ttf.exists() else None


def _drawtext_font() -> str:
    """A concrete TTF for ffmpeg drawtext (unlike libass, drawtext needs an explicit file)."""
    for cand in (font_path(), *_MACOS_FONTS):
        if cand and Path(cand).exists():
            return cand
    raise RuntimeError("no usable TTF for drawtext (add assets/branding/caption.ttf)")


def _has_audio(path: Path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "a", "-show_entries", "stream=index",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return bool(out.stdout.strip())


def _normalize_spec_vf() -> str:
    return (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,fps={FPS},setsar=1"
    )


def _synth_card(
    text: str,
    bg_hex: str,
    out: Path,
    *,
    size: tuple[int, int] = (WIDTH, HEIGHT),
    seconds: float = CARD_SECONDS,
    fontsize: int = 64,
    wrap_cols: int = _WRAP_COLS,
) -> Path:
    """A title/end card: solid background + centered wrapped text + silent stereo AAC.
    Defaults are the landscape spec; the Shorts builder passes portrait size + tighter wrap."""
    out = Path(out)
    w, h = size
    card_txt = out.parent / f"{out.stem}_text.txt"
    # Wrap per input line: textwrap.wrap alone would collapse explicit line breaks, which
    # card copy uses deliberately (fragment / fragment / CTA).
    wrapped = "\n".join(
        line for para in text.split("\n") for line in (textwrap.wrap(para, wrap_cols) or [""])
    ).strip("\n") or " "
    card_txt.write_text(wrapped, encoding="utf-8")
    drawtext = (
        f"drawtext=fontfile='{_drawtext_font()}':textfile={card_txt.name}:"
        f"fontcolor=white:fontsize={fontsize}:line_spacing=16:x=(w-text_w)/2:y=(h-text_h)/2"
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c={bg_hex}:s={w}x{h}:r={FPS}",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-vf", drawtext, "-t", f"{seconds}",
        *video_encode_args(), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-ar", "44100", "-ac", "2", str(out),
    ]
    _run(cmd, cwd=out.parent)
    card_txt.unlink(missing_ok=True)
    return out


def _normalize_user_clip(src: Path, out: Path) -> Path:
    """Re-encode a user intro/outro.mp4 to the exact concat spec (adds silent audio if none)."""
    out = Path(out)
    cmd = ["ffmpeg", "-y", "-i", str(src)]
    if not _has_audio(src):
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest"]
    cmd += [
        "-vf", _normalize_spec_vf(), *video_encode_args(), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", str(out),
    ]
    _run(cmd)
    return out


def user_intro() -> Path | None:
    """The operator's hand-made bumper clip, or None. Its absence means COLD OPEN — the
    body starts at t=0 with the title overlaid on the first beats — never a synthesized
    black card: 3 silent static seconds at t=0 is exactly where browse viewers bail."""
    src = BRANDING_DIR / "intro.mp4"
    return src if src.exists() else None


def cold_open_title_fx(title: str, workdir: Path) -> str | None:
    """drawtext chain that pins the title over the opening seconds of the body: fade in,
    hold, fully gone by COLD_OPEN_TITLE_SECONDS. Placed in the TOP band so it never
    collides with the caption zone at the bottom. One drawtext per wrapped line so each
    line centers itself. Returned as a `burn_and_mux` post_fx (renders above captions);
    textfiles are written to `workdir` because burn_and_mux runs with cwd there."""
    if not title.strip():
        return None
    hold_until = COLD_OPEN_TITLE_SECONDS - _COLD_OPEN_FADE_OUT
    alpha = (
        f"'if(lt(t,{_COLD_OPEN_FADE_IN}),t/{_COLD_OPEN_FADE_IN},"
        f"if(lt(t,{hold_until}),1,"
        f"max(0,({COLD_OPEN_TITLE_SECONDS}-t)/{_COLD_OPEN_FADE_OUT})))'"
    )
    lines = textwrap.wrap(title, _COLD_OPEN_WRAP_COLS) or [" "]
    draws = []
    for i, line in enumerate(lines):
        txt = Path(workdir) / f"coldopen_{i}.txt"
        txt.write_text(line, encoding="utf-8")
        draws.append(
            f"drawtext=fontfile='{_drawtext_font()}':textfile={txt.name}:"
            f"fontcolor=white:borderw=5:bordercolor=black:fontsize=76:"
            f"x=(w-text_w)/2:y={110 + i * 96}:alpha={alpha}"
        )
    return ",".join(draws)


def make_intro(title: str, out: str | Path) -> Path:
    src = user_intro()
    if src is not None:
        return _normalize_user_clip(src, Path(out))
    log.info("assets/branding/intro.mp4 missing -> synthesizing a title card")
    return _synth_card(title or "", "0x0a0a14", Path(out))


def make_outro(
    out: str | Path,
    *,
    teaser: str | None = None,
    music: str | Path | None = None,
    voice: str | Path | None = None,
    backdrop_image: str | Path | None = None,
) -> Path:
    """End-screen outro card: reserved zones for YouTube's next-video/subscribe elements,
    a per-video teaser line, the video's music bed fading back in (when given), an optional
    spoken outro (`voice`) in the brand narrator voice, and an optional documentary backdrop
    (`backdrop_image`, the closing still) graded under the text."""
    src = BRANDING_DIR / "outro.mp4"
    if src.exists():
        # A hand-made outro is used as-is (its own layout and audio) -- keeping its
        # element zones clear is the responsibility of whoever authored the clip.
        return _normalize_user_clip(src, Path(out))
    log.info("assets/branding/outro.mp4 missing -> synthesizing an end-screen outro card")
    return endscreen_outro.build_endscreen_outro(
        Path(out), font=_drawtext_font(), teaser=teaser, music=music, voice=voice,
        backdrop_image=backdrop_image,
    )
