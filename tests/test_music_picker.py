"""Key-free unit tests for the music bed picker: mood-bucket selection, deterministic
rotation across videos, CC-BY credit persisted into script.json, the license-audit Asset
row, and safe no-ops when the library or script is missing. Temp DB + temp library."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ai_operator.assembler import music_picker as mp
from ai_operator.db.base import Base
from ai_operator.db.models import Asset


def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'music.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _setup(tmp_path, monkeypatch, moods, tracks=("somber-a.mp3", "somber-b.mp3", "tense-x.mp3")):
    lib = tmp_path / "music"
    lib.mkdir()
    for t in tracks:
        (lib / t).write_bytes(b"mp3")
    monkeypatch.setattr(mp, "MUSIC_DIR", lib)
    monkeypatch.setattr(mp, "SessionLocal", _session_factory(tmp_path))
    vdir = tmp_path / "out"
    vdir.mkdir()
    (vdir / "script.json").write_text(json.dumps(
        {"shot_list": [{"beat_id": i + 1, "mood": m} for i, m in enumerate(moods)]}
    ))
    return vdir


def test_somber_script_gets_somber_bed_and_credit(tmp_path, monkeypatch):
    vdir = _setup(tmp_path, monkeypatch, ["somber", "tragic", "reflective", "tense"])
    picked = mp.pick_for_video(1, vdir)
    assert picked and Path(picked).name.startswith("somber-")
    script = json.loads((vdir / "script.json").read_text())
    assert "Kevin MacLeod" in script["music_credit"]          # CC-BY attribution persisted
    with mp.SessionLocal() as s:                               # audit row registered
        row = s.scalar(select(Asset).where(Asset.video_id == 1, Asset.kind == "music"))
    assert row is not None and "CC BY" in row.license


def test_tense_majority_selects_tense_bucket(tmp_path, monkeypatch):
    vdir = _setup(tmp_path, monkeypatch, ["tense", "ominous", "chaotic", "desperate", "somber"])
    picked = mp.pick_for_video(2, vdir)
    assert Path(picked).name.startswith("tense-")


def test_rotation_varies_by_video_id(tmp_path, monkeypatch):
    vdir = _setup(tmp_path, monkeypatch, ["somber"] * 4)
    a = mp.pick_for_video(0, vdir)
    b = mp.pick_for_video(1, vdir)
    assert a != b  # consecutive videos don't share one bed


def test_no_library_returns_none(tmp_path, monkeypatch):
    vdir = _setup(tmp_path, monkeypatch, ["somber"])
    monkeypatch.setattr(mp, "MUSIC_DIR", tmp_path / "missing")
    assert mp.pick_for_video(1, vdir) is None


def test_missing_script_returns_none(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, ["somber"])
    empty = tmp_path / "empty"
    empty.mkdir()
    assert mp.pick_for_video(1, empty) is None


def test_prefers_track_long_enough_to_avoid_loop_seam(tmp_path, monkeypatch):
    """A bed shorter than the video loops with an audible restart — the picker must prefer a
    track that covers the whole runtime and only fall back to the longest otherwise."""
    vdir = _setup(tmp_path, monkeypatch, ["somber"] * 3)
    (vdir / "narration.mp3").write_bytes(b"mp3")  # 460s video (mocked below)
    durations = {"narration.mp3": 460.0, "somber-a.mp3": 180.0, "somber-b.mp3": 600.0, "tense-x.mp3": 150.0}
    monkeypatch.setattr(mp, "_safe_duration", lambda p: durations.get(p.name, 0.0))

    for vid in range(4):  # every rotation lands on the only seam-free candidate
        assert Path(mp.pick_for_video(vid, vdir)).name == "somber-b.mp3"


def test_falls_back_to_longest_when_nothing_covers_runtime(tmp_path, monkeypatch):
    vdir = _setup(tmp_path, monkeypatch, ["somber"] * 3)
    (vdir / "narration.mp3").write_bytes(b"mp3")
    durations = {"narration.mp3": 900.0, "somber-a.mp3": 180.0, "somber-b.mp3": 600.0, "tense-x.mp3": 150.0}
    monkeypatch.setattr(mp, "_safe_duration", lambda p: durations.get(p.name, 0.0))
    assert Path(mp.pick_for_video(0, vdir)).name == "somber-b.mp3"  # longest = fewest seams


def test_description_uses_per_track_credit():
    from ai_operator.publisher import metadata_builder as mb
    script = {"description": "Hook.", "music_credit": 'Music: "Dark Times" by Kevin MacLeod (incompetech.com), licensed under CC BY 4.0 (creativecommons.org/licenses/by/4.0)'}
    desc = mb.build_description(script)
    assert "Dark Times" in desc and mb.DEFAULT_MUSIC_CREDIT not in desc
