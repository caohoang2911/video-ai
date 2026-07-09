"""Bold-documentary thumbnail styling: cinematic grade + vignette + dark lower band, then a
big yellow stroked title (<=2 lines, auto-sized to fit). Kept apart from thumbnail_generator
so the generator stays a thin orchestrator and this pure-PIL styling is unit-testable alone.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .branding import font_path

TEXT_COLOR = (255, 212, 0)   # punchy documentary yellow
STROKE_COLOR = (0, 0, 0)
MARGIN = 60
MAX_LINES = 2
_MAX_FONT, _MIN_FONT = 120, 46

_measure = ImageDraw.Draw(Image.new("RGB", (8, 8)))  # scratch canvas for text metrics


def stylize(img: Image.Image) -> Image.Image:
    """Contrast + saturation boost, an edge vignette, and a dark bottom band so text pops."""
    img = img.convert("RGB")
    img = ImageEnhance.Contrast(img).enhance(1.25)
    img = ImageEnhance.Color(img).enhance(1.2)
    img = _vignette(img)
    return _bottom_band(img)


def draw_title(img: Image.Image, text: str) -> Image.Image:
    """Draw `text` (uppercased, <=2 auto-sized lines) centered in the lower third, yellow with
    a thick black stroke. No-op for empty text. Mutates + returns `img`."""
    if not text.strip():
        return img
    w, h = img.size
    font, lines = _fit(text.upper(), w - 2 * MARGIN)
    draw = ImageDraw.Draw(img)
    line_h = font.size + 12
    y = h - MARGIN - line_h * len(lines)
    stroke = max(4, font.size // 12)
    for line in lines:
        x = (w - _text_w(line, font)) // 2
        draw.text((x, y), line, font=font, fill=TEXT_COLOR, stroke_width=stroke, stroke_fill=STROKE_COLOR)
        y += line_h
    return img


def _vignette(img: Image.Image, strength: float = 0.5) -> Image.Image:
    """Darken the edges toward the corners so the center subject stands out."""
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse([-w * 0.2, -h * 0.25, w * 1.2, h * 1.25], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(w * 0.10))
    darkened = ImageEnhance.Brightness(img).enhance(1 - strength)
    return Image.composite(img, darkened, mask)  # center=img, edges=darkened


def _bottom_band(img: Image.Image, height_frac: float = 0.45, opacity: float = 0.65) -> Image.Image:
    """Fade a black band up from the bottom for caption legibility."""
    w, h = img.size
    band_h = int(h * height_frac)
    column = Image.new("L", (1, band_h))
    for yy in range(band_h):
        column.putpixel((0, yy), int(255 * opacity * (yy / band_h)))  # 0 at top -> opacity at bottom
    mask = Image.new("L", (w, h), 0)
    mask.paste(column.resize((w, band_h)), (0, h - band_h))
    return Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), img, mask)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    path = font_path()
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size=size)


def _text_w(text: str, font: ImageFont.FreeTypeFont) -> int:
    return int(_measure.textlength(text, font=font))


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Greedy word-wrap; a single word wider than max_w still gets its own line."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if not cur or _text_w(trial, font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _fit(text: str, max_w: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Largest font (<= _MAX_FONT) whose wrap is <= MAX_LINES and each line fits max_w."""
    for size in range(_MAX_FONT, _MIN_FONT - 1, -6):
        font = _load_font(size)
        lines = _wrap(text, font, max_w)
        if len(lines) <= MAX_LINES and all(_text_w(ln, font) <= max_w for ln in lines):
            return font, lines
    font = _load_font(_MIN_FONT)
    return font, _wrap(text, font, max_w)[:MAX_LINES]
