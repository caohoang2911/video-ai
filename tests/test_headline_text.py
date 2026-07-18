"""Unit tests for the Short top-band white-set / red-gap headline renderer (pure logic,
no ffmpeg): line splitting, red-gap selection, font fit, and the drawtext chain shape."""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_operator.assembler import headline_text as ht


# --- split_lines -----------------------------------------------------------------
def test_split_honors_explicit_newline():
    assert ht.split_lines("How Germany Conquered\nHalf of Europe in Just 2 Years") == [
        "How Germany Conquered",
        "Half of Europe in Just 2 Years",
    ]


def test_split_at_em_dash_and_colon():
    assert ht.split_lines("The Life Vests That Crumbled — General Slocum 1904") == [
        "The Life Vests That Crumbled",
        "General Slocum 1904",
    ]
    assert ht.split_lines("Little Germany: Erased in One Afternoon") == [
        "Little Germany",
        "Erased in One Afternoon",
    ]


def test_split_balances_long_headline_into_two_lines():
    lines = ht.split_lines("The Neighborhood That Vanished in One Afternoon")
    assert len(lines) == 2
    assert " ".join(lines).split() == "The Neighborhood That Vanished in One Afternoon".split()


def test_split_short_headline_stays_one_line():
    assert ht.split_lines("One Boat Sank") == ["One Boat Sank"]


def test_split_drops_empty_side_on_leading_separator():
    # a leading separator must not emit a blank first line (blank textfile aborts old ffmpeg)
    assert ht.split_lines(": 1,021 Dead") == ["1,021 Dead"]
    assert all(ln for ln in ht.split_lines("— Nobody Charged"))


# --- red_line_indices ------------------------------------------------------------
def test_red_is_the_line_with_the_first_number():
    assert ht.red_line_indices(["How Germany Conquered", "Half of Europe in Just 2 Years"]) == {1}
    assert ht.red_line_indices(["1,021 Kids", "One Boat"]) == {0}


def test_red_falls_to_last_line_without_a_number():
    assert ht.red_line_indices(["The Warning Chicago Buried", "Nobody Was Ever Charged"]) == {1}


def test_red_empty_is_safe():
    assert ht.red_line_indices([]) == set()


# --- fit_fontsize ----------------------------------------------------------------
def test_fit_fontsize_within_bounds_and_shrinks_for_long_lines():
    font = ht._display_font()
    short = ht.fit_fontsize(["War"], 900, font)
    long = ht.fit_fontsize(["An Extremely Long Uninterrupted Single Display Line Here"], 900, font)
    assert ht._MIN_FONT <= long <= short <= ht._MAX_FONT
    assert long < short  # more text on a line -> smaller font to fit the same width


def test_fit_fontsize_empty_is_safe():
    assert ht.fit_fontsize([], 900, ht._display_font()) == ht._MIN_FONT


# --- build_headline_fx -----------------------------------------------------------
def test_blank_headline_returns_none(tmp_path: Path):
    assert ht.build_headline_fx("", tmp_path) is None
    assert ht.build_headline_fx("   \n  ", tmp_path) is None


def test_build_fx_two_tone_and_writes_line_files(tmp_path: Path):
    fx = ht.build_headline_fx("How Germany Conquered\nHalf of Europe in Just 2 Years", tmp_path)
    assert fx is not None
    assert fx.count("drawtext=") == 2
    assert ht.OFF_WHITE in fx and ht.GAP_RED in fx      # both setup-white and gap-red present
    assert "expansion=none" in fx                        # literal text, no %{...} expansion
    assert (tmp_path / "hook_0.txt").exists() and (tmp_path / "hook_1.txt").exists()
    assert (tmp_path / "hook_1.txt").read_text() == "Half of Europe in Just 2 Years"


def test_build_fx_upper_case(tmp_path: Path):
    ht.build_headline_fx("How Germany Conquered\nHalf of Europe", tmp_path, case="upper")
    assert (tmp_path / "hook_0.txt").read_text() == "HOW GERMANY CONQUERED"


def test_build_fx_title_case_is_verbatim(tmp_path: Path):
    # "title" renders as authored (never .title() — that would capitalize small words)
    ht.build_headline_fx("How Germany Conquered\nHalf of Europe in Just 2 Years", tmp_path, case="title")
    assert (tmp_path / "hook_1.txt").read_text() == "Half of Europe in Just 2 Years"


def test_special_chars_go_through_textfile(tmp_path: Path):
    # commas/apostrophes must land in the textfile, not the filter option string
    ht.build_headline_fx("They Never Spoke\n1,021 Souls, One Captain's Choice", tmp_path)
    assert (tmp_path / "hook_1.txt").read_text() == "1,021 Souls, One Captain's Choice"
