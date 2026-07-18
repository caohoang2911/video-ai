"""White-set / red-gap curiosity headline for the Short's top band.

Renders a 1-3 line headline as an ffmpeg `drawtext` chain (one drawtext per line so each
line self-centers) for `burn_and_mux`'s `post_fx` slot — it runs AFTER zoompan, so the
headline stays static while the image pans under it. The setup line(s) are off-white and the
GAP line burns red: the line carrying the first number, else the last line. Same red-payoff
idea as the poster thumbnail, but line-level (not word-level) because drawtext colors a whole
text node at once — a 2-line headline never needs mid-line color.

Kept out of short_builder so the wrap/fit/color logic is unit-testable without ffmpeg.
"""

from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

from . import branding

OFF_WHITE = "0xF7F7F7"  # setup lines — matches the poster BASE_COLOR (247,247,247)
GAP_RED = "0xD62222"    # the red gap line — matches the poster ACCENT_COLOR (214,34,34)

_MAX_FONT, _MIN_FONT = 120, 54
_BAND_H = 600           # usable top blur band (image sits ~y656 down); block is centred in it
_TOP_FLOOR = 130        # keep the block below the Shorts search / 3-dot UI at the very top
_SIDE_MARGIN = 60       # each side, on a 1080-wide frame

# A heavy display face reads at phone size the way the reference (DailyDoseOfHistoryFacts)
# headline does; fall back to the branded caption / Arial when Impact is absent.
_DISPLAY_FONTS = ("/System/Library/Fonts/Supplemental/Impact.ttf",)


def _display_font() -> str:
    for cand in _DISPLAY_FONTS:
        if Path(cand).exists():
            return cand
    return branding._drawtext_font()  # branded caption / Arial fallback (only when Impact absent)


def split_lines(text: str) -> list[str]:
    """Split a headline into display lines: honor an explicit newline; else break at a
    setup/gap separator (em-dash / colon); else balance the words across two lines."""
    text = text.strip()
    if "\n" in text:
        return [ln.strip() for ln in text.split("\n") if ln.strip()]
    for sep in (" — ", " – ", " -- ", ": "):
        if sep in text:
            # drop an empty side so a leading/trailing separator can't emit a blank line
            # (a blank textfile aborts the filter graph on older ffmpeg)
            parts = [p.strip() for p in text.split(sep, 1) if p.strip()]
            if parts:
                return parts
    words = text.split()
    if len(words) <= 3:
        return [text]
    # pick the word boundary that most evenly balances the two lines' character length
    best: tuple[int, list[str]] | None = None
    for i in range(1, len(words)):
        left, right = " ".join(words[:i]), " ".join(words[i:])
        score = abs(len(left) - len(right))
        if best is None or score < best[0]:
            best = (score, [left, right])
    return best[1] if best else [text]


def red_line_indices(lines: list[str]) -> set[int]:
    """Which line is the red gap: the first line bearing a digit (a number is the hook),
    else the last line. Never more than one — emphasis works by scarcity."""
    for i, ln in enumerate(lines):
        if any(c.isdigit() for c in ln):
            return {i}
    return {len(lines) - 1} if lines else set()


def _wrap_words(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Greedy word-wrap to `max_w` px so no line ever overflows the frame; a single word
    wider than the box still gets its own line (only clips in the degenerate huge-word case)."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if not cur or font.getlength(trial) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def layout(parts: list[str], max_w: int, font_file: str) -> tuple[int, list[str]]:
    """Largest font at which the headline fits the frame width. Honors the setup/gap `parts`
    as preferred breaks but RE-WRAPS any part too wide for `max_w`, so the text can never
    overflow. Prefers 2 total lines; falls back to 3 when the content is too long for 2 at a
    readable size (a 3rd line degrades gracefully — overflow never does)."""
    if not parts:
        return _MIN_FONT, []
    for target in (2, 3):
        for size in range(_MAX_FONT, _MIN_FONT - 1, -4):
            font = ImageFont.truetype(font_file, size)
            lines = [wl for p in parts for wl in _wrap_words(p, font, max_w)]
            if len(lines) <= target:
                return size, lines
    font = ImageFont.truetype(font_file, _MIN_FONT)  # floor: width-safe even if it needs >3 lines
    return _MIN_FONT, [wl for p in parts for wl in _wrap_words(p, font, max_w)]


def build_headline_fx(
    text: str,
    video_dir: Path,
    *,
    case: str = "title",
    width: int = 1080,
) -> str | None:
    """Return a `drawtext` chain for `post_fx`, or None when there is no headline.

    `case`: "upper" uppercases the text; "title" renders it as authored (the generator/
    caller already supplies proper title case, so we never mangle small words with .title()).
    Writes one `hook_<i>.txt` per line into `video_dir` (short_builder cleans them up)."""
    text = (text or "").strip()
    if not text:
        return None
    if case == "upper":
        text = text.upper()

    font_file = _display_font()
    size, lines = layout(split_lines(text), width - 2 * _SIDE_MARGIN, font_file)
    reds = red_line_indices(lines)
    line_h = int(size * 1.14)
    border = max(4, size // 13)
    y0 = max(_TOP_FLOOR, (_BAND_H - len(lines) * line_h) // 2)

    draws: list[str] = []
    for i, line in enumerate(lines):
        # burn_and_mux runs with cwd=video_dir -> textfiles referenced by basename (dodges
        # drawtext's own escaping of commas/apostrophes in the headline)
        txt = video_dir / f"hook_{i}.txt"
        txt.write_text(line, encoding="utf-8")
        color = GAP_RED if i in reds else OFF_WHITE
        draws.append(
            # expansion=none: treat the headline as a literal — a stray "%{...}" must not be
            # expanded to a frame number (textfile dodges option-escaping, not text expansion)
            f"drawtext=fontfile='{font_file}':textfile={txt.name}:expansion=none:"
            f"fontcolor={color}:borderw={border}:bordercolor=black:fontsize={size}:"
            f"x=(w-text_w)/2:y={y0 + i * line_h}"
        )
    return ",".join(draws)
