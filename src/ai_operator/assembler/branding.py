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
from .ffmpeg_encode import FPS, _run, video_encode_args

log = get_logger("assembler.branding")

BRANDING_DIR = Path(__file__).resolve().parents[3] / "assets" / "branding"
CARD_SECONDS = 3.0
WIDTH, HEIGHT = 1920, 1080
_WRAP_COLS = 26
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


def make_intro(title: str, out: str | Path) -> Path:
    src = BRANDING_DIR / "intro.mp4"
    if src.exists():
        return _normalize_user_clip(src, Path(out))
    log.info("assets/branding/intro.mp4 missing -> synthesizing a title card")
    return _synth_card(title or "", "0x0a0a14", Path(out))


def make_outro(out: str | Path, subscribe_text: str = "Thanks for watching -- subscribe for more") -> Path:
    src = BRANDING_DIR / "outro.mp4"
    if src.exists():
        return _normalize_user_clip(src, Path(out))
    log.info("assets/branding/outro.mp4 missing -> synthesizing an end card")
    return _synth_card(subscribe_text, "0x140a0a", Path(out))
