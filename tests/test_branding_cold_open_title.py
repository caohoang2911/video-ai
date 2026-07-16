"""Cold-open title overlay: the default main-video opening is beat 1 + narration at t=0
with the title fading in the top band — never a synthesized silent black card."""

from __future__ import annotations

import pytest

from ai_operator.assembler import branding


@pytest.fixture
def font_stub(monkeypatch):
    monkeypatch.setattr(branding, "_drawtext_font", lambda: "font.ttf")


def test_empty_title_yields_no_overlay(tmp_path, font_stub):
    assert branding.cold_open_title_fx("   ", tmp_path) is None


def test_overlay_fades_and_wraps_one_drawtext_per_line(tmp_path, font_stub):
    fx = branding.cold_open_title_fx(
        "The Collision That Erased Halifax in Nine Minutes", tmp_path
    )
    assert fx.count("drawtext=") == 2          # 50 chars wrap into two self-centering lines
    assert fx.count("alpha='if(") == 2         # fade in/out rides every line
    assert (tmp_path / "coldopen_0.txt").exists() and (tmp_path / "coldopen_1.txt").exists()


def test_user_intro_only_when_bumper_file_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(branding, "BRANDING_DIR", tmp_path)
    assert branding.user_intro() is None
    (tmp_path / "intro.mp4").write_bytes(b"stub")
    assert branding.user_intro() == tmp_path / "intro.mp4"
