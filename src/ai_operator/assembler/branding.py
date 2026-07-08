"""Intro/outro branding clips + shared caption font lookup.

Real assets (a short intro/outro clip, a licensed caption font) are supplied once,
manually, and dropped into `assets/branding/` -- see the README there for what to add and
the royalty-free/licensing requirement. If they are missing (e.g. a fresh checkout before
branding is finalized) we synthesize a plain title/end card so the render pipeline never
blocks on a missing asset.
"""

from __future__ import annotations

from pathlib import Path

from moviepy import ColorClip, CompositeVideoClip, TextClip, VideoFileClip

from ..logging_setup import get_logger

log = get_logger("assembler.branding")

BRANDING_DIR = Path(__file__).resolve().parents[3] / "assets" / "branding"
CARD_SECONDS = 3.0
WIDTH, HEIGHT = 1920, 1080


def font_path() -> str | None:
    """Shared branded caption font, or None to fall back to the library default."""
    ttf = BRANDING_DIR / "caption.ttf"
    return str(ttf) if ttf.exists() else None


def _synthetic_card(text: str, bg_color: tuple[int, int, int]) -> CompositeVideoClip:
    bg = ColorClip(size=(WIDTH, HEIGHT), color=bg_color, duration=CARD_SECONDS)
    txt = TextClip(
        text=text, font=font_path(), font_size=72, color="white",
        method="caption", size=(1600, None), duration=CARD_SECONDS,
    ).with_position("center")
    return CompositeVideoClip([bg, txt], size=(WIDTH, HEIGHT))


def load_intro(title: str):
    intro_path = BRANDING_DIR / "intro.mp4"
    if intro_path.exists():
        return VideoFileClip(str(intro_path))
    log.info("assets/branding/intro.mp4 missing -> synthesizing a title card")
    return _synthetic_card(title or "", bg_color=(10, 10, 20))


def load_outro(subscribe_text: str = "Thanks for watching -- subscribe for more"):
    outro_path = BRANDING_DIR / "outro.mp4"
    if outro_path.exists():
        return VideoFileClip(str(outro_path))
    log.info("assets/branding/outro.mp4 missing -> synthesizing an end card")
    return _synthetic_card(subscribe_text, bg_color=(20, 10, 10))
