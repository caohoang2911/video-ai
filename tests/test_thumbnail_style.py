"""Key-free unit tests for the bold-documentary thumbnail styling: word-wrap + auto-fit stay
within the 2-line / width budget, and stylize()/draw_title() run on a synthetic frame without
crashing and preserve size. Pure PIL; no ffmpeg, no network, no API key."""

from __future__ import annotations

from PIL import Image

from ai_operator.assembler import thumbnail_style as ts

SIZE = (1280, 720)


def _frame() -> Image.Image:
    return Image.new("RGB", SIZE, (40, 80, 120))


def test_wrap_respects_max_width():
    font = ts._load_font(60)
    lines = ts._wrap("THE DEADLIEST MARITIME DISASTER IN HISTORY", font, max_w=600)
    assert len(lines) >= 2
    assert all(ts._text_w(ln, font) <= 600 for ln in lines)


def test_fit_stays_within_two_lines():
    font, lines = ts._fit("DELIVERED THE BOMB THEN VANISHED", max_w=SIZE[0] - 2 * ts.MARGIN)
    assert 1 <= len(lines) <= ts.MAX_LINES
    assert all(ts._text_w(ln, font) <= SIZE[0] - 2 * ts.MARGIN for ln in lines)


def test_stylize_preserves_size_and_mode():
    out = ts.stylize(_frame())
    assert out.size == SIZE
    assert out.mode == "RGB"


def test_draw_title_runs_and_changes_pixels():
    base = ts.stylize(_frame())
    before = base.copy()
    ts.draw_title(base, "Delivered Bomb, Then Vanished")
    assert base.size == SIZE
    assert list(base.getdata()) != list(before.getdata())  # text was actually drawn


def test_draw_title_empty_is_noop():
    img = ts.stylize(_frame())
    snapshot = list(img.getdata())
    ts.draw_title(img, "   ")
    assert list(img.getdata()) == snapshot
