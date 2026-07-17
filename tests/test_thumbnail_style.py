"""Key-free unit tests for the subject-preserving thumbnail styling: negative-space headline
placement (kicker + one red punch word), auto-fit within a box, and grade/no-grade both run
on a synthetic frame without crashing and preserve size. Pure PIL; no ffmpeg, no network."""

from __future__ import annotations

from PIL import Image

from ai_operator.assembler import thumbnail_style as ts

SIZE = (1280, 720)
BOX = (60, 400, 1220, 680)  # explicit lower-band region (bypasses auto-detect in tests)


def _frame() -> Image.Image:
    return Image.new("RGB", SIZE, (40, 80, 120))


def test_wrap_respects_max_width():
    font = ts._load_font(60)
    lines = ts._wrap("THE DEADLIEST MARITIME DISASTER IN HISTORY", font, max_w=600)
    assert len(lines) >= 2
    assert all(ts._text_w(ln, font) <= 600 for ln in lines)


def test_fit_box_stays_within_width_height_and_lines():
    font, lines = ts._fit_box("DELIVERED THE BOMB THEN VANISHED", max_w=1000, max_h=400)
    assert 1 <= len(lines) <= ts.MAX_LINES
    assert all(ts._text_w(ln, font) <= 1000 for ln in lines)
    assert len(lines) * int(font.size * 1.06) <= 400


def test_stylize_grade_and_nograde_preserve_size_and_mode():
    for grade in (True, False):
        out = ts.stylize(_frame(), grade=grade)
        assert out.size == SIZE and out.mode == "RGB"


def test_draw_title_runs_and_changes_pixels():
    base = ts.stylize(_frame())
    before = base.copy()
    ts.draw_title(base, "Delivered Bomb, Then Vanished", kicker="HALIFAX · 1917")
    assert base.size == SIZE
    assert list(base.getdata()) != list(before.getdata())  # text was actually drawn


def test_draw_title_empty_text_and_kicker_is_noop():
    img = ts.stylize(_frame())
    snapshot = list(img.getdata())
    ts.draw_title(img, "   ", kicker="")
    assert list(img.getdata()) == snapshot


def test_draw_title_two_tone_accent_and_base():
    img = Image.new("RGB", SIZE, (0, 0, 0))
    ts.draw_title(img, "CITY GONE", kicker="", box=BOX)  # lone line -> last word "GONE" red
    colors = {c for _, c in img.getcolors(maxcolors=200000)}
    assert ts.ACCENT_COLOR in colors  # a red punch word
    assert ts.BASE_COLOR in colors    # leading words off-white


def test_accent_targets_red_payoff_rules():
    # multi-line: the whole line bearing the number goes red
    assert ts._accent_targets(["THE WRECK", "SEALED FOR", "26 YEARS"]) == {(2, 0), (2, 1)}
    # lone line with a number: only the number phrase (digit word -> end), never the whole line
    assert ts._accent_targets(["THE WRECK SEALED FOR 26 YEARS"]) == {(0, 4), (0, 5)}
    # no number, multi-line: whole last line
    assert ts._accent_targets(["NEVER", "EXPLAINED"]) == {(1, 0)}
    # no number, lone line: only the last word
    assert ts._accent_targets(["NEVER EXPLAINED"]) == {(0, 1)}


def test_compose_kicker_uses_event_year_when_title_has_none():
    assert ts.compose_kicker("MS Estonia", "MS Estonia: Sealed for 26 Years", event_year=1994) == "MS ESTONIA · 1994"
    assert ts.compose_kicker("RMS Lusitania", "Manifest, 1915", event_year=1900) == "RMS LUSITANIA · 1915"  # title year wins
    assert ts.compose_kicker("SS Eastland", "The Eastland Disaster") == "SS EASTLAND"  # no year anywhere


def test_draw_credit_runs_and_is_noop_when_empty():
    img = Image.new("RGB", SIZE, (30, 30, 30))
    snapshot = list(img.getdata())
    ts.draw_credit(img, "   ")
    assert list(img.getdata()) == snapshot  # empty -> no-op
    ts.draw_credit(img, "Photo: X · Wikimedia Commons · CC BY-SA 4.0")
    assert list(img.getdata()) != snapshot and img.size == SIZE


def test_compose_kicker_prefers_anchor_and_finds_year():
    assert ts.compose_kicker("RMS Lusitania", "Butter — Lusitania's Manifest, 1915") == "RMS LUSITANIA · 1915"
    assert ts.compose_kicker("MS Estonia", "MS Estonia: Why the Wreck Was Sealed") == "MS ESTONIA"  # no year
    assert ts.compose_kicker(None, "The Halifax Explosion: Nine Minutes") == "THE HALIFAX EXPLOSION"  # title fallback
    assert ts.compose_kicker(None, None) == ""


def test_fallback_headline_drops_entity_and_takes_hook():
    got = ts.fallback_headline("MS Estonia: Why the Wreck Was Sealed for 26 Years", "MS Estonia")
    assert got == "Why the Wreck Was Sealed for 26 Years"  # entity + leading ':' stripped, hook kept


def test_fallback_headline_word_boundary_safe():
    # a subject that is a substring of another word must not be gouged out of it
    assert ts.fallback_headline("The Chronology Of Ron", "Ron") == "The Chronology Of"


def test_draw_title_out_of_bounds_box_does_not_crash():
    img = Image.new("RGB", SIZE, (20, 20, 20))
    ts.draw_title(img, "OUT OF BOUNDS", kicker="X · 1", box=(1000, 500, 2400, 1400))  # box past frame
    assert img.size == SIZE


def test_historical_dim_darkens_bright_more_than_dark():
    bright = Image.new("RGB", SIZE, (210, 210, 210))
    dark = Image.new("RGB", SIZE, (40, 40, 40))
    ts._historical_dim(bright)
    ts._historical_dim(dark)
    bright_after = bright.getpixel((10, 10))[0]
    dark_after = dark.getpixel((10, 10))[0]
    assert bright_after < 210 * 0.70          # a bright frame is dimmed substantially (subject too bright)
    assert dark_after >= 40 * 0.92            # an already-dark frame is barely touched


def test_clean_text_uppercases_and_strips_trailing_punctuation():
    assert ts._clean_text("City Gone.") == "CITY GONE"
    assert ts._clean_text(" one mistake!? ") == "ONE MISTAKE"


def test_stylize_duotones_grayscale_frames():
    grey = Image.new("RGB", SIZE, (128, 128, 128))
    out = ts.stylize(grey)
    px = list(out.resize((16, 9)).getdata())
    assert any(abs(r - b) > 15 for r, _, b in px)  # duotone tint applied, no longer neutral grey
