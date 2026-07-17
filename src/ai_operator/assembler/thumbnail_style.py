"""Bold-documentary thumbnail styling: cinematic grade + vignette, then a movie-poster
headline laid down the frame's NEGATIVE-SPACE edge (never buried in the subject). A small
brass kicker with an underline rule sits above a big left-aligned Impact headline whose
numeric payoff line (or last line/word) burns red — a directional gradient darkens only the
text edge so the subject keeps breathing. Kept apart from thumbnail_generator so the generator
stays a thin orchestrator and this pure-PIL styling is unit-testable alone.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from . import thumbnail_layout
from .branding import font_path

KICKER_COLOR = (206, 168, 98)   # brass — SUBJECT·YEAR eyebrow above the headline
BASE_COLOR = (247, 247, 247)    # headline words, off-white for contrast against the red
ACCENT_COLOR = (214, 34, 34)    # the red payoff — a numeric line, else the last line/word
STROKE_COLOR = (0, 0, 0)
MAX_LINES = 4
_MAX_FONT, _MIN_FONT = 156, 44
_KICKER_TRACKING = 0.16  # letter-spacing as a fraction of the kicker font size

# Heavy display faces make a headline read at phone size; PIL's bitmap default does not.
_THUMB_FONTS = (
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
)

# Duotone ramp for near-grayscale archival photos: deep navy shadows -> warm highlights.
_DUO_SHADOW = (10, 16, 38)
_DUO_HIGHLIGHT = (255, 214, 140)
_GRAYSCALE_SATURATION = 40  # mean HSV saturation below which a frame is treated as B&W

_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")  # a 4-digit year 1500-2099
_measure = ImageDraw.Draw(Image.new("RGB", (8, 8)))  # scratch canvas for text metrics


def stylize(img: Image.Image, *, grade: bool = True) -> Image.Image:
    """Edge vignette so the center subject stands out, plus a colour/duotone grade unless
    `grade=False` (used when a Kontext-enhanced hero is already cinematically graded — a
    second push would clip it)."""
    img = img.convert("RGB")
    if grade:
        if _is_near_grayscale(img):
            img = _duotone(img)
        else:
            img = ImageEnhance.Contrast(img).enhance(1.3)
            img = ImageEnhance.Color(img).enhance(1.4)
        img = img.filter(ImageFilter.UnsharpMask(radius=3, percent=120, threshold=2))
    return _vignette(img)


def draw_title(
    img: Image.Image,
    text: str,
    kicker: str = "",
    box: tuple[int, int, int, int] | None = None,
) -> Image.Image:
    """Lay the headline (`text`) down the frame's negative-space edge with the brass `kicker`
    (a ready SUBJECT·YEAR eyebrow + underline rule) above it and a red payoff. A directional
    gradient darkens ONLY the text edge so the subject keeps breathing. Mutates + returns.

    `box` overrides the auto-detected region (test hook). No-op when both text+kicker empty.
    """
    headline = _clean_text(text)
    kicker = (kicker or "").strip().upper()
    if not headline and not kicker:
        return img

    region, needs_bar = (box, True) if box else thumbnail_layout.text_region(img)
    side = _region_side(region, img.size)
    # Moody, historical whole-frame dim (subject included) so the thick-stroked title reads
    # WITHOUT a drop shadow — heavier when the frame is bright, barely on an already-dark one.
    _historical_dim(img)
    _gradient_scrim(img, region, side, peak=_scrim_peak(img, region, needs_bar))

    x0, y0, x1, y1 = region
    pad = int((x1 - x0) * 0.04)
    ix0, iy0, ix1, iy1 = x0 + pad, y0 + pad, x1 - pad, y1 - pad
    inner_w = ix1 - ix0
    draw = ImageDraw.Draw(img)
    y = iy0

    if kicker:
        kfont = _fit_kicker(kicker, inner_w, base=max(24, min(50, int(inner_w * 0.072))))
        kstroke = max(2, kfont.size // 13)
        x_end = _draw_spaced(draw, (ix0, y), kicker, kfont, KICKER_COLOR, stroke=kstroke)
        rule_y = y + int(kfont.size * 1.20)
        rule_h = max(3, kfont.size // 9)
        draw.rectangle([ix0, rule_y, min(x_end, ix1), rule_y + rule_h], fill=KICKER_COLOR)
        y = rule_y + rule_h + int(kfont.size * 0.55)

    if headline:
        avail_h = max(iy1 - y, int(_MIN_FONT * 1.04))  # if the kicker ate the budget, keep >=1 line
        font, lines = _fit_box(headline, inner_w, avail_h)
        line_h = int(font.size * 1.04)
        lines = lines[: max(1, (iy1 - y) // line_h)]  # never spill lines below the box over the subject
        red = _accent_targets(lines)
        stroke = max(6, font.size // 9)  # heavy outline carries legibility now that there is no shadow
        for i, line in enumerate(lines):
            _draw_line(draw, (ix0, y), line, font, stroke, {j for (li, j) in red if li == i})
            y += line_h
    return img


def compose_kicker(subject: str | None, title: str | None) -> str:
    """`SUBJECT · YEAR` eyebrow. Prefers the clean entity `subject` (the archive anchor, e.g.
    "RMS Lusitania") over parsing the raw title, so a hook-phrase title never becomes a
    rambling kicker; the year is the first found in the title or subject. Degrades cleanly to
    subject-only, or a title split when no subject is given, or '' when both are absent."""
    entity = (subject or "").strip()
    if not entity and title:  # no anchor -> fall back to the title's pre-colon/dash segment
        entity = re.split(r":| — | – | -- ", title.strip(), maxsplit=1)[0].strip()
    entity = entity.upper().rstrip(".,!?…:;")
    if not entity:
        return ""
    year = _YEAR_RE.search(f"{title or ''} {subject or ''}")
    return f"{entity} · {year.group(0)}" if year else entity


def fallback_headline(title: str | None, subject: str | None) -> str:
    """A headline for videos whose script carries no `thumbnail_text`: the title's hook clause
    (after the entity ':'/'—'), with the entity + year removed so the kicker isn't echoed."""
    h = title or ""
    if subject:  # \b so a subject that is a substring of a word ("Ron" in "Chronology") isn't mangled
        h = re.sub(rf"\b{re.escape(subject)}\b", "", h, flags=re.IGNORECASE)
    h = re.split(r":| — | – | -- ", h, maxsplit=1)[-1]  # the hook clause after the entity
    h = re.sub(r"\s+", " ", _YEAR_RE.sub("", h)).strip(" ,:—–-").strip()  # collapse the gaps left behind
    return h or (title or "")


def _accent_targets(lines: list[str]) -> set[tuple[int, int]]:
    """`(line, word)` coords to paint red — the red payoff. A NUMBER is the hook: on a multi-
    line headline the whole line bearing the first number goes red (e.g. "26 YEARS" on its own
    line); on a LONE line only the number phrase (first digit word -> end of line) does, so a
    one-liner is never entirely red. With no number: the whole last line of a multi-line
    headline, else just the last word of a lone line."""
    for i, ln in enumerate(lines):
        words = ln.split()
        for j, w in enumerate(words):
            if any(c.isdigit() for c in w):
                span = range(len(words)) if len(lines) > 1 else range(j, len(words))
                return {(i, k) for k in span}
    if len(lines) > 1:
        last = len(lines) - 1
        return {(last, k) for k in range(len(lines[last].split()))}
    lone = lines[0].split() if lines else []
    return {(0, len(lone) - 1)} if lone else set()


def _region_side(box: tuple[int, int, int, int], size: tuple[int, int]) -> str:
    """Which edge the text box hugs — drives the gradient scrim direction."""
    w, h = size
    x0, y0, x1, y1 = box
    if (x1 - x0) < w * 0.72:  # a side column
        return "left" if (x0 + x1) / 2 < w / 2 else "right"
    return "bottom" if (y0 + y1) / 2 > h / 2 else "top"


def _clean_text(text: str) -> str:
    """Uppercase and drop trailing punctuation — a period wastes width at thumbnail scale."""
    return (text or "").strip().upper().rstrip(".,!?…:;")


def _is_near_grayscale(img: Image.Image) -> bool:
    sat = np.asarray(img.resize((160, 90)).convert("HSV"))[:, :, 1]
    return float(sat.mean()) < _GRAYSCALE_SATURATION


def _duotone(img: Image.Image) -> Image.Image:
    lum = np.asarray(img.convert("L"), dtype=np.float32) / 255.0
    lum = np.clip((lum - 0.5) * 1.3 + 0.5, 0.0, 1.0)  # S-ish contrast push around midtones
    shadow = np.array(_DUO_SHADOW, dtype=np.float32)
    highlight = np.array(_DUO_HIGHLIGHT, dtype=np.float32)
    ramp = shadow + (highlight - shadow) * lum[:, :, None]
    return Image.fromarray(ramp.astype(np.uint8), "RGB")


def _vignette(img: Image.Image, strength: float = 0.5) -> Image.Image:
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse([-w * 0.2, -h * 0.25, w * 1.2, h * 1.25], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(w * 0.10))
    darkened = ImageEnhance.Brightness(img).enhance(1 - strength)
    return Image.composite(img, darkened, mask)  # center=img, edges=darkened


def _gradient_scrim(img: Image.Image, box: tuple[int, int, int, int], side: str, *, peak: float) -> None:
    """Darken `box` with a one-directional ramp (darkest at the text edge -> transparent at the
    far edge) so the headline is legible while the subject side stays clear. Mutates in place."""
    w, h = img.size
    x0, y0, x1, y1 = box
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)  # clip: an out-of-bounds box must not crash
    bw, bh = x1 - x0, y1 - y0
    if bw <= 0 or bh <= 0:
        return
    alpha = np.zeros((h, w), dtype=np.float32)
    if side in ("left", "right"):
        t = np.linspace(0.0, 1.0, bw, dtype=np.float32)
        ramp = peak * (1.0 - t) if side == "left" else peak * t
        alpha[y0:y1, x0:x1] = np.tile(ramp, (bh, 1))
    else:
        t = np.linspace(0.0, 1.0, bh, dtype=np.float32)
        ramp = peak * t if side == "bottom" else peak * (1.0 - t)
        alpha[y0:y1, x0:x1] = np.tile(ramp[:, None], (1, bw))
    feather = max(6, int(w * 0.02))
    mask = Image.fromarray((alpha * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(feather))
    img.paste(Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), img, mask), (0, 0))


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for cand in (font_path(), *_THUMB_FONTS):
        if cand and Path(cand).exists():
            return ImageFont.truetype(cand, size)
    return ImageFont.load_default(size=size)


def _text_w(text: str, font: ImageFont.FreeTypeFont) -> int:
    return int(_measure.textlength(text, font=font))


def _spaced_w(text: str, font: ImageFont.FreeTypeFont) -> int:
    gap = int(font.size * _KICKER_TRACKING)
    return sum(_text_w(ch, font) + gap for ch in text)


def _fit_kicker(text: str, max_w: int, base: int) -> ImageFont.FreeTypeFont:
    """Shrink the kicker until its letter-spaced width fits the column."""
    size = base
    while size > 16 and _spaced_w(text, _load_font(size)) > max_w:
        size -= 2
    return _load_font(size)


def _draw_spaced(draw, xy, text, font, color, *, stroke) -> int:
    """Letter-spaced single line (the eyebrow kicker); returns the ending x."""
    x, y = xy
    gap = int(font.size * _KICKER_TRACKING)
    for ch in text:
        draw.text((x, y), ch, font=font, fill=color, stroke_width=stroke, stroke_fill=STROKE_COLOR)
        x += _text_w(ch, font) + gap
    return x


def _draw_line(draw, xy, line, font, stroke, red_cols) -> None:
    """Left-aligned line; words whose index is in `red_cols` burn accent red, the rest off-white."""
    x, y = xy
    for j, word in enumerate(line.split()):
        color = ACCENT_COLOR if j in red_cols else BASE_COLOR
        draw.text((x, y), word, font=font, fill=color, stroke_width=stroke, stroke_fill=STROKE_COLOR)
        x += _text_w(word + " ", font)


def _historical_dim(img: Image.Image) -> None:
    """Darken the WHOLE frame (subject included) toward a moody, historical tone — heavily when
    the frame is bright ('nếu chủ thể quá sáng'), barely when it is already dark — so the thick-
    stroked title reads without a drop shadow. Mutates `img` in place."""
    # 65th-percentile luminance, not the mean, so a bright SUBJECT on a dark ground (white ship
    # on black) still reads as "too bright" and gets dimmed — the mean would hide it.
    bright = float(np.percentile(np.asarray(img.convert("L")), 65)) / 255.0
    factor = min(0.95, max(0.45, 0.98 - 1.4 * max(0.0, bright - 0.30)))  # ~0.60@0.57, 0.74@0.47, 0.9@0.35
    if factor < 0.99:
        img.paste(ImageEnhance.Brightness(img).enhance(factor))


def _scrim_peak(img: Image.Image, box: tuple[int, int, int, int], needs_bar: bool) -> float:
    """A LIGHT extra darkening of the text edge on top of the whole-frame historical dim — just
    enough to bias the poster's text side; scaled to the (already-dimmed) region brightness."""
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return 0.5
    arr = np.asarray(img.crop((x0, y0, x1, y1)).convert("L"), dtype=np.float32) / 255.0
    lum = float(arr.mean())
    contrast = min(1.0, float(arr.std()) / 0.22)  # local busyness/contrast, normalized ~0..1
    return min(0.80, 0.34 + 0.34 * lum + 0.12 * contrast + (0.08 if needs_bar else 0.0))


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


def _fit_box(text: str, max_w: int, max_h: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Largest font whose wrap fits `max_w` wide, `max_h` tall and <= MAX_LINES. Never clips:
    at the floor it truncates line COUNT but keeps shrinking until each line fits the width."""
    for size in range(_MAX_FONT, _MIN_FONT - 1, -6):
        font = _load_font(size)
        lines = _wrap(text, font, max_w)
        fits_w = all(_text_w(ln, font) <= max_w for ln in lines)
        fits_h = len(lines) * int(size * 1.04) <= max_h
        if fits_w and fits_h and len(lines) <= MAX_LINES:
            return font, lines
    font = _load_font(_MIN_FONT)
    return font, _wrap(text, font, max_w)[:MAX_LINES]
