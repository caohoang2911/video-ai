"""Bold-documentary thumbnail styling: duotone/cinematic grade + vignette + dark lower band,
then a big two-tone stroked title (<=2 lines, auto-sized, punch word in accent yellow). Kept
apart from thumbnail_generator so the generator stays a thin orchestrator and this pure-PIL
styling is unit-testable alone.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .branding import font_path

ACCENT_COLOR = (255, 212, 0)   # punchy documentary yellow — the final "punch" word
BASE_COLOR = (255, 255, 255)   # remaining words stay white for contrast against the accent
STROKE_COLOR = (0, 0, 0)
MARGIN = 60
BOTTOM_MARGIN = 84  # lifted above YouTube's duration badge / progress-bar strip
MAX_LINES = 2
_MAX_FONT, _MIN_FONT = 150, 52

# Duotone ramp for near-grayscale archival photos: deep navy shadows -> warm highlights.
# Grey B&W scans vanish between saturated feed thumbnails; this makes them read as "graded
# documentary" while keeping the photo's authenticity.
_DUO_SHADOW = (10, 16, 38)
_DUO_HIGHLIGHT = (255, 214, 140)
# Mean HSV saturation (0-255) below which a frame is treated as "B&W". Yellowed archival
# scans measure ~28-30 while genuinely coloured frames sit at 55+, so 40 splits the two.
_GRAYSCALE_SATURATION = 40

_measure = ImageDraw.Draw(Image.new("RGB", (8, 8)))  # scratch canvas for text metrics


def stylize(img: Image.Image) -> Image.Image:
    """Grade + edge vignette + dark bottom band so text pops. Near-grayscale frames get the
    duotone ramp; colour frames get a strong contrast/saturation push. Both get sharpened."""
    img = img.convert("RGB")
    if _is_near_grayscale(img):
        img = _duotone(img)
    else:
        img = ImageEnhance.Contrast(img).enhance(1.35)
        img = ImageEnhance.Color(img).enhance(1.45)
    img = img.filter(ImageFilter.UnsharpMask(radius=3, percent=120, threshold=2))
    img = _vignette(img)
    return _bottom_band(img)


def draw_title(img: Image.Image, text: str) -> Image.Image:
    """Draw `text` (uppercased, trailing punctuation stripped, <=2 auto-sized lines) centered
    in the lower third: white words with the final punch word in accent yellow, all with a
    thick black stroke. No-op for empty text. Mutates + returns `img`."""
    text = _clean_text(text)
    if not text:
        return img
    w, h = img.size
    font, lines = _fit(text, w - 2 * MARGIN)
    draw = ImageDraw.Draw(img)
    line_h = font.size + 12
    y = h - BOTTOM_MARGIN - line_h * len(lines)
    stroke = max(4, font.size // 12)
    words_left = sum(len(ln.split()) for ln in lines)
    for line in lines:
        x = (w - _text_w(line, font)) // 2
        for word in line.split():
            words_left -= 1
            color = ACCENT_COLOR if words_left == 0 else BASE_COLOR
            draw.text((x, y), word, font=font, fill=color, stroke_width=stroke, stroke_fill=STROKE_COLOR)
            x += _text_w(word + " ", font)
        y += line_h
    return img


def _clean_text(text: str) -> str:
    """Uppercase and drop trailing punctuation — a period wastes width at thumbnail scale."""
    return text.strip().upper().rstrip(".,!?…:;")


def _is_near_grayscale(img: Image.Image) -> bool:
    """True when mean HSV saturation is low enough that colour grading would do nothing."""
    sat = np.asarray(img.resize((160, 90)).convert("HSV"))[:, :, 1]
    return float(sat.mean()) < _GRAYSCALE_SATURATION


def _duotone(img: Image.Image) -> Image.Image:
    """Map luminance onto the shadow->highlight ramp with a mild S-curve for extra contrast."""
    lum = np.asarray(img.convert("L"), dtype=np.float32) / 255.0
    lum = np.clip((lum - 0.5) * 1.3 + 0.5, 0.0, 1.0)  # S-ish contrast push around midtones
    shadow = np.array(_DUO_SHADOW, dtype=np.float32)
    highlight = np.array(_DUO_HIGHLIGHT, dtype=np.float32)
    ramp = shadow + (highlight - shadow) * lum[:, :, None]
    return Image.fromarray(ramp.astype(np.uint8), "RGB")


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
    """Largest font (<= _MAX_FONT) whose wrap is <= MAX_LINES and each line fits max_w.
    At _MIN_FONT we give up on the line count (truncate) but never on width: an unbreakable
    word wider than max_w keeps shrinking (down to 24px) instead of clipping at the edges."""
    for size in range(_MAX_FONT, 23, -6):
        font = _load_font(size)
        lines = _wrap(text, font, max_w)
        fits_width = all(_text_w(ln, font) <= max_w for ln in lines)
        if fits_width and len(lines) <= MAX_LINES:
            return font, lines
        if fits_width and size <= _MIN_FONT:
            return font, lines[:MAX_LINES]
    font = _load_font(24)
    return font, _wrap(text, font, max_w)[:MAX_LINES]
