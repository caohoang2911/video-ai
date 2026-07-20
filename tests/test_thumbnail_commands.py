"""Unit tests for the `thumbs` CLI helpers: regenerating an older video's thumbnails must
never destroy the variants it just backed up (they may be live on YouTube)."""

from __future__ import annotations

from ai_operator.assembler import commands


def _write_variants(video_dir, marker):
    video_dir.mkdir(parents=True, exist_ok=True)
    for letter in "abc":
        (video_dir / f"thumb_{letter}.jpg").write_text(f"{marker}-{letter}")


def test_backup_variants_copies_every_variant(monkeypatch, tmp_path):
    monkeypatch.setattr(commands, "OUTPUT_DIR", tmp_path)
    _write_variants(tmp_path / "5", "ORIGINAL")

    saved = commands._backup_variants(5)

    assert len(saved) == 3
    assert sorted(p.read_text() for p in saved) == ["ORIGINAL-a", "ORIGINAL-b", "ORIGINAL-c"]


def test_two_backups_in_the_same_minute_do_not_overwrite(monkeypatch, tmp_path):
    """Iterating on a thumbnail (`thumbs --same-hero`, then `thumbs`) can finish inside one
    wall-clock minute; a minute-resolution folder name would let the second run overwrite the
    originals the first run saved."""
    monkeypatch.setattr(commands, "OUTPUT_DIR", tmp_path)
    video_dir = tmp_path / "5"

    _write_variants(video_dir, "ORIGINAL")
    first = commands._backup_variants(5)
    _write_variants(video_dir, "REGENERATED")
    second = commands._backup_variants(5)

    assert first[0].parent != second[0].parent
    assert sorted(p.read_text() for p in first) == ["ORIGINAL-a", "ORIGINAL-b", "ORIGINAL-c"]


def test_backup_variants_is_a_noop_without_existing_thumbnails(monkeypatch, tmp_path):
    monkeypatch.setattr(commands, "OUTPUT_DIR", tmp_path)
    (tmp_path / "5").mkdir()

    assert commands._backup_variants(5) == []
    assert list((tmp_path / "5").iterdir()) == []  # no empty backup folder left behind
