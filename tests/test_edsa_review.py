"""Key-free unit tests for the EDSA review gate: the inline checklist surfaces the EDSA
(who/what/when/where/why-in-narration) + hook + payoff rows, a caption warns when a video
needs re-voice, and `handle_callback` hard-blocks a PASS_* approval tap on a needs_revoice
video with exactly ONE alert-answer and no state transition.

Telegram is never contacted -- the callback query is an AsyncMock; the DB is an isolated
sqlite file. handle_callback is driven via asyncio.run so no pytest-asyncio plugin is needed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_operator.db.base import Base
from ai_operator.db.models import Video
from ai_operator.db.state_machine import VideoState
from ai_operator.review import callbacks, caption
from ai_operator.review import decision_codes as dc
from ai_operator.review.keyboards import CHECKLIST_ITEMS, checklist_keyboard

_CHAT_ID = "123456"


def _make_session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _make_query(data: str):
    query = MagicMock()
    query.data = data
    query.message.chat.id = _CHAT_ID
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    return update, query


# --------------------------------------------------------------------------------------
# EDSA checklist rows
# --------------------------------------------------------------------------------------


def test_checklist_includes_edsa_hook_payoff_rows():
    assert {"edsa5w", "hook", "payoff"}.issubset(set(CHECKLIST_ITEMS))


def test_checklist_keyboard_renders_edsa_label_and_short_callback():
    kb = checklist_keyboard(7, {"edsa5w": True})
    buttons = [b for row in kb.inline_keyboard for b in row]
    edsa = next(b for b in buttons if "WHO/WHAT/WHEN/WHERE/WHY" in b.text)
    assert edsa.text.startswith("✅")                 # toggle state renders
    assert edsa.callback_data == "CHK_EDSA5W:7"       # short key, well under Telegram's 64 bytes
    assert any("hook present" in b.text for b in buttons)
    assert any("payoff present" in b.text for b in buttons)


# --------------------------------------------------------------------------------------
# caption re-voice warning
# --------------------------------------------------------------------------------------


def test_caption_shows_revoice_warning_only_when_flagged(tmp_path, monkeypatch):
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(caption, "SessionLocal", Session)

    flagged = Video(id=1, idempotency_key="k1", title="X", needs_revoice=True)
    clean = Video(id=2, idempotency_key="k2", title="Y", needs_revoice=False)

    assert "NEEDS RE-VOICE" in caption.build_caption(flagged)
    assert "NEEDS RE-VOICE" not in caption.build_caption(clean)


# --------------------------------------------------------------------------------------
# handle_callback needs_revoice block
# --------------------------------------------------------------------------------------


def _seed(monkeypatch, tmp_path, *, needs_revoice: bool, state=VideoState.PENDING_REVIEW):
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(callbacks, "SessionLocal", Session)
    monkeypatch.setattr(callbacks.settings, "TELEGRAM_CHAT_ID", _CHAT_ID)
    finalize = AsyncMock()
    monkeypatch.setattr(callbacks, "finalize_decision", finalize)
    with Session() as s:
        s.add(Video(id=5, idempotency_key="k-5", state=state.value, needs_revoice=needs_revoice))
        s.commit()
    return Session, finalize


@pytest.mark.parametrize("code", [dc.PASS_POLICY, dc.PASS_QUALITY])
def test_pass_tap_blocked_on_needs_revoice_video(tmp_path, monkeypatch, code):
    Session, finalize = _seed(monkeypatch, tmp_path, needs_revoice=True)
    update, query = _make_query(f"{code}:5")

    asyncio.run(callbacks.handle_callback(update, MagicMock()))

    query.answer.assert_awaited_once()                       # exactly one answer() for the query
    assert query.answer.await_args.kwargs.get("show_alert") is True
    finalize.assert_not_awaited()                            # no state change
    with Session() as s:
        assert s.get(Video, 5).state == VideoState.PENDING_REVIEW.value


def test_pass_tap_allowed_when_not_needs_revoice(tmp_path, monkeypatch):
    Session, finalize = _seed(monkeypatch, tmp_path, needs_revoice=False)
    update, query = _make_query(f"{dc.PASS_POLICY}:5")

    asyncio.run(callbacks.handle_callback(update, MagicMock()))

    query.answer.assert_awaited_once()                       # the general spinner-clear answer
    assert query.answer.await_args.kwargs.get("show_alert") is None
    finalize.assert_awaited_once()                           # normal terminal dispatch proceeds


def test_malformed_callback_data_clears_spinner_without_finalize(tmp_path, monkeypatch):
    """A non-int video id still clears the tap spinner (single plain answer) and never
    dispatches -- even on a needs_revoice video, parsing fails before the block is reached."""
    Session, finalize = _seed(monkeypatch, tmp_path, needs_revoice=True)
    update, query = _make_query("PASS_POLICY:not-an-int")

    asyncio.run(callbacks.handle_callback(update, MagicMock()))

    query.answer.assert_awaited_once()
    assert query.answer.await_args.kwargs.get("show_alert") is None
    finalize.assert_not_awaited()


def test_non_approval_tap_never_blocked_on_needs_revoice_video(tmp_path, monkeypatch):
    """Only PASS_* is gated; a menu-open tap (Reject picker) on the same video still works."""
    Session, finalize = _seed(monkeypatch, tmp_path, needs_revoice=True)
    update, query = _make_query("REJECT_POLICY:5")  # opens the reason picker -- no DB, no finalize

    asyncio.run(callbacks.handle_callback(update, MagicMock()))

    query.answer.assert_awaited_once()
    assert query.answer.await_args.kwargs.get("show_alert") is None
    query.edit_message_reply_markup.assert_awaited_once()    # picker rendered
    finalize.assert_not_awaited()
