"""Key-free unit tests for the ops pipeline runner: a topic that fails to generate is marked
used (so the produce loop can't jam on it), and re-running past the review gate does not
re-notify. No network, no API keys; DB steps and the notify boundary are stubbed."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_operator.db.base import Base
from ai_operator.db.models import Topic, Video
from ai_operator.db.state_machine import VideoState
from ai_operator.ops import pipeline_runner as pr


def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


# --------------------------------------------------------------------------------------
# H1: a failing topic is advanced out of the produce queue
# --------------------------------------------------------------------------------------


def test_run_new_marks_topic_used_when_generation_fails(monkeypatch):
    topic = Topic(id=5, title="weak topic", angle="a", status="backlog")
    monkeypatch.setattr(pr.topic_backlog, "pick_next", lambda: topic)

    def _boom(_topic):
        raise ValueError("payoff gate rejected")

    monkeypatch.setattr(pr.script_generator, "generate", _boom)
    marked: list[int] = []
    monkeypatch.setattr(pr.topic_backlog, "mark_used", lambda tid: marked.append(tid))

    assert pr.run_new() is None            # did not proceed to a broken video
    assert marked == [5]                   # topic advanced so pick_next won't re-pick it forever


# --------------------------------------------------------------------------------------
# M3: re-running past the review gate does not re-notify
# --------------------------------------------------------------------------------------


def _stub_steps(monkeypatch, Session):
    for name in ("gen_audio", "gen_visuals"):
        monkeypatch.setattr(pr.media_commands, name, lambda **k: None)
    monkeypatch.setattr(pr, "assemble_video", lambda vid: None)
    monkeypatch.setattr(pr, "generate_thumbnails", lambda vid: None)
    monkeypatch.setattr(pr, "SessionLocal", Session)
    monkeypatch.setattr(pr.settings, "TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setattr(pr.settings, "TELEGRAM_CHAT_ID", "123")
    sent: list[int] = []
    monkeypatch.setattr(pr, "notify", lambda vid: sent.append(vid))
    return sent


def test_run_video_notifies_a_rendered_video(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    sent = _stub_steps(monkeypatch, Session)
    with Session() as s:
        s.add(Video(id=1, idempotency_key="k1", state=VideoState.RENDERED.value, video_path="x"))
        s.commit()

    pr.run_video(1)
    assert sent == [1]  # RENDERED can enter review -> notified


def test_run_video_does_not_renotify_past_the_gate(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    sent = _stub_steps(monkeypatch, Session)
    with Session() as s:
        s.add(Video(id=2, idempotency_key="k2", state=VideoState.APPROVED.value, video_path="x"))
        s.commit()

    pr.run_video(2)
    assert sent == []  # APPROVED is past the gate -> no crash, no duplicate notify
