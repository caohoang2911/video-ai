"""Key-free unit tests for the content-quality gates: scored payoff-node reject, and the
`script.json` on-the-wire shape (`title_options` = `{title, thumbnail_text}` dicts,
`payoff_nodes` = `{text, surprise_score}` dicts) round-tripping cleanly through every disk
consumer -- metadata_builder, thumbnail_generator, ab_variants, and publish().

This is the exact bug class the red-team flagged (a consumer attribute-accessing a
disk-loaded dict, or publish.py injecting bare strings into a `list[dict]` field): the
round-trip below drives publish's own no-script fallback + DB-title overlay end-to-end and
asserts the shape every downstream reader agrees on. No network/API calls are made.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ai_operator.assembler import thumbnail_generator
from ai_operator.content import script_generator as sg
from ai_operator.content.schema import ScriptOutput
from ai_operator.db.base import Base
from ai_operator.db.models import Upload, Video
from ai_operator.db.state_machine import VideoState
from ai_operator.publisher import ab_variants, metadata_builder

# publisher/__init__ shadows the `publish` submodule with the function -- pull the real
# module object from sys.modules so monkeypatch targets its own globals (same trick as
# test_voice_revoice).
import ai_operator.publisher.publish  # noqa: F401

pub_mod = sys.modules["ai_operator.publisher.publish"]


def _make_session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _sample_script(*, strong_scores=(5, 4, 3, 2, 1)) -> ScriptOutput:
    """A schema-valid ScriptOutput with 3 title/thumbnail pairs and 5 scored payoff nodes."""
    return ScriptOutput(
        narration="A concrete opening line about the wreck. And a second sentence.",
        hooks=[
            {"variant_id": i, "pattern_interrupt": "p", "context_teaser": "c", "text_overlay": "o"}
            for i in (1, 2)
        ],
        pattern="mystery",
        payoff_nodes=[{"text": f"beat {i}", "surprise_score": s} for i, s in enumerate(strong_scores)],
        shot_list=[
            {"beat_id": i, "narration_span": "s", "keywords": ["k"], "mood": "m"} for i in range(10)
        ],
        title_options=[
            {"title": "The Ship That Vanished", "thumbnail_text": "GONE IN MINUTES"},
            {"title": "60 Souls, No Trace", "thumbnail_text": "NO SURVIVORS"},
            {"title": "The Wreck Nobody Searched For", "thumbnail_text": "FORGOTTEN"},
        ],
        description="A short description.",
        tags=["maritime", "history"],
        sources=["s1", "s2"],
        citations=[{"claim": "c", "source": "s", "verified": True}] * 3,
        research_depth="Med",
    )


# --------------------------------------------------------------------------------------
# script.json on-the-wire shape
# --------------------------------------------------------------------------------------


def test_scriptjson_serializes_title_and_payoff_as_dicts(tmp_path):
    path = tmp_path / "script.json"
    path.write_text(json.dumps(_sample_script().model_dump()), encoding="utf-8")

    disk = json.loads(path.read_text(encoding="utf-8"))
    assert disk["title_options"][0] == {"title": "The Ship That Vanished", "thumbnail_text": "GONE IN MINUTES"}
    assert disk["payoff_nodes"][0] == {"text": "beat 0", "surprise_score": 5}


def test_disk_consumers_use_dict_access(tmp_path, capsys):
    """metadata_builder + thumbnail_generator + ab_variants all read the disk dict shape."""
    script_dir = tmp_path / "42"
    script_dir.mkdir()
    script_path = script_dir / "script.json"
    script_path.write_text(json.dumps(_sample_script().model_dump()), encoding="utf-8")
    disk = json.loads(script_path.read_text(encoding="utf-8"))

    # metadata_builder: title comes from options[0]["title"], not the raw dict repr
    assert metadata_builder.pick_title(disk) == "The Ship That Vanished"
    body = metadata_builder.build_upload_body(disk, publish_at_iso="2026-07-08T00:00:00Z", category_id="27")
    assert body["snippet"]["title"] == "The Ship That Vanished"

    # thumbnail_generator: overlays are the per-title thumbnail_text (uppercased), 3 of them
    overlays = thumbnail_generator._overlay_texts(script_path)
    assert overlays == ["GONE IN MINUTES", "NO SURVIVORS", "FORGOTTEN"]

    # ab_variants: the Studio checklist prints titles, never a `{'title': ...}` dict repr
    ab_variants._print_checklist(42, disk["title_options"], ["thumb_a.jpg"])
    printed = capsys.readouterr().out
    assert "The Ship That Vanished" in printed
    assert "{'title'" not in printed


# --------------------------------------------------------------------------------------
# payoff-node reject gate
# --------------------------------------------------------------------------------------


def test_payoff_gate_rejects_weak_script(tmp_path, monkeypatch):
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(sg, "SessionLocal", Session)
    with Session() as s:
        s.add(Video(id=1, idempotency_key="k-weak", state=VideoState.DRAFT.value))
        s.commit()

    weak = _sample_script(strong_scores=(2, 2, 1, 1, 1))  # zero nodes score >= 3
    with pytest.raises(ValueError, match="weak payoff"):
        sg._enforce_payoff_gate(1, weak)

    with Session() as s:
        v = s.get(Video, 1)
        assert v.state == VideoState.FAILED.value
        assert "weak payoff" in (v.reject_reason or "")


def test_payoff_gate_accepts_strong_well_paced_script(tmp_path, monkeypatch):
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(sg, "SessionLocal", Session)
    with Session() as s:
        s.add(Video(id=2, idempotency_key="k-ok", state=VideoState.DRAFT.value))
        s.commit()

    # 4 strong nodes, avg 3.6, exactly one weak node -> passes all three checks
    ok = _sample_script(strong_scores=(5, 4, 3, 4, 2))
    sg._enforce_payoff_gate(2, ok)  # must not raise

    with Session() as s:
        assert s.get(Video, 2).state == VideoState.DRAFT.value  # untouched


def test_payoff_gate_rejects_low_average(tmp_path, monkeypatch):
    """Three strong nodes are not enough if filler drags the average down (flat overall)."""
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(sg, "SessionLocal", Session)
    with Session() as s:
        s.add(Video(id=3, idempotency_key="k-avg", state=VideoState.DRAFT.value))
        s.commit()

    flat = _sample_script(strong_scores=(3, 3, 3, 1, 1, 1))  # strong=3 but avg=2.0
    with pytest.raises(ValueError, match="average surprise"):
        sg._enforce_payoff_gate(3, flat)


def test_payoff_gate_rejects_mid_video_sag(tmp_path, monkeypatch):
    """Two+ filler nodes (score <= 2) = the mid-video retention sag, even with a good average."""
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(sg, "SessionLocal", Session)
    with Session() as s:
        s.add(Video(id=4, idempotency_key="k-sag", state=VideoState.DRAFT.value))
        s.commit()

    saggy = _sample_script(strong_scores=(5, 5, 4, 2, 2))  # avg 3.6, strong=3, but 2 weak nodes
    with pytest.raises(ValueError, match="filler node"):
        sg._enforce_payoff_gate(4, saggy)


# --------------------------------------------------------------------------------------
# publish(): no-script fallback + DB-title overlay both emit dict-shaped title_options
# --------------------------------------------------------------------------------------


def _publish_happy_path_mocks(tmp_path, monkeypatch):
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(pub_mod, "SessionLocal", Session)
    monkeypatch.setattr(pub_mod.checkpoint, "artifacts_of", lambda vid, step: None)
    monkeypatch.setattr(pub_mod.checkpoint, "write", lambda *a, **k: None)
    for name in ("ensure_can_publish", "reserve_insert", "reserve_thumbnail"):
        monkeypatch.setattr(pub_mod.quota_throttle, name, lambda *a, **k: None)
    monkeypatch.setattr(pub_mod, "build_service", lambda: object())
    monkeypatch.setattr(pub_mod.thumbnail_setter, "set_thumbnail", lambda *a, **k: False)

    captured: dict = {}

    def _fake_upload(service, path, body):
        captured["body"] = body
        return "yt-xyz"

    def _fake_submit(vid, title_options, thumbs):
        captured["ab_titles"] = title_options

    monkeypatch.setattr(pub_mod.youtube_uploader, "upload", _fake_upload)
    # capture exactly what publish hands to the A/B consumer (must be list[dict])
    monkeypatch.setattr(pub_mod.ab_variants, "discover_thumb_variants", lambda path: [])
    monkeypatch.setattr(pub_mod.ab_variants, "submit", _fake_submit)
    return Session, captured


def test_publish_no_script_fallback_builds_dict_title_options(tmp_path, monkeypatch, temp_db):
    # temp_db: publish()'s gen-shorts auto-enqueue writes through the SHARED sessionmaker
    # (job_queue), not the patched pub_mod one — without temp_db those rows leaked into the
    # developer's real data/*.db and the live scheduler executed them.
    Session, captured = _publish_happy_path_mocks(tmp_path, monkeypatch)
    with Session() as s:
        s.add(Video(
            id=10, idempotency_key="k-10", state=VideoState.APPROVED.value,
            video_path="output/10/final.mp4", title="DB Only Title", needs_revoice=False,
        ))  # script_path is None -> exercises the no-script fallback
        s.commit()

    yt_id = pub_mod.publish(10)

    assert yt_id == "yt-xyz"
    assert captured["body"]["snippet"]["title"] == "DB Only Title"
    assert captured["ab_titles"] == [{"title": "DB Only Title", "thumbnail_text": ""}]  # dict, not bare string
    with Session() as s:
        assert s.get(Video, 10).state == VideoState.PUBLISHED.value
        assert s.scalar(select(Upload).where(Upload.video_id == 10)) is not None


def test_publish_db_title_overlay_promotes_and_dedups_dict_shape(tmp_path, monkeypatch, temp_db):
    # temp_db: same shared-sessionmaker reason as the fallback test above
    Session, captured = _publish_happy_path_mocks(tmp_path, monkeypatch)
    script_dir = tmp_path / "11"
    script_dir.mkdir()
    script_path = script_dir / "script.json"
    script_path.write_text(json.dumps(_sample_script().model_dump()), encoding="utf-8")

    with Session() as s:
        s.add(Video(
            id=11, idempotency_key="k-11", state=VideoState.APPROVED.value,
            video_path="output/11/final.mp4", title="60 Souls, No Trace",  # matches an existing option
            script_path=str(script_path), needs_revoice=False,
        ))
        s.commit()

    pub_mod.publish(11)

    # operator-edited title promoted to front as a dict; no duplicate of the same title; the
    # other original options survive (still dicts). Never a bare string in the field.
    ab_titles = captured["ab_titles"]
    assert all(isinstance(o, dict) and "title" in o for o in ab_titles)
    assert ab_titles[0] == {"title": "60 Souls, No Trace", "thumbnail_text": ""}
    assert [o["title"] for o in ab_titles].count("60 Souls, No Trace") == 1
    assert captured["body"]["snippet"]["title"] == "60 Souls, No Trace"
