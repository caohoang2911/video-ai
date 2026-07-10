"""Enqueue side of the DB job queue: allowlist, idempotency-key stability, double-click dedup."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from ai_operator.db.models_ops import Job
from ai_operator.web import job_queue
from ai_operator.web.job_queue import JOB_COMMANDS, enqueue


def test_unknown_command_raises():
    with pytest.raises(ValueError):
        enqueue("rm-rf-slash")


def test_idem_key_is_stable_and_scoped():
    a = job_queue._idem_key("gen-audio", 1, None, None)
    b = job_queue._idem_key("gen-audio", 1, None, None)
    assert a == b                                   # deterministic
    assert a != job_queue._idem_key("gen-audio", 2, None, None)   # video scopes it
    assert a != job_queue._idem_key("gen-visuals", 1, None, None)  # command scopes it
    # param order must not matter (sorted json)
    assert job_queue._idem_key("produce", None, 3, {"motion": True, "n": 1}) == \
        job_queue._idem_key("produce", None, 3, {"n": 1, "motion": True})


def test_enqueue_inserts_one_pending_row(temp_db):
    res = enqueue("gen-audio", video_id=1)
    assert res["created"] is True and res["status"] == "pending"
    from ai_operator.db.engine import SessionLocal
    with SessionLocal() as s:
        rows = s.scalars(select(Job)).all()
    assert len(rows) == 1 and rows[0].command == "gen-audio" and rows[0].video_id == 1


def test_double_click_while_in_flight_is_deduped(temp_db):
    first = enqueue("assemble", video_id=7)
    second = enqueue("assemble", video_id=7)          # same fingerprint, still pending
    assert first["id"] == second["id"]
    assert second["created"] is False
    from ai_operator.db.engine import SessionLocal
    with SessionLocal() as s:
        assert len(s.scalars(select(Job)).all()) == 1   # no duplicate row


def test_different_params_are_distinct_jobs(temp_db):
    a = enqueue("gen-visuals", video_id=3, params={"motion": True})
    b = enqueue("gen-visuals", video_id=3, params={"motion": False})
    assert a["id"] != b["id"]


def test_allowlist_matches_expected_surface():
    assert JOB_COMMANDS == frozenset({
        "produce", "gen-topics", "gen-audio", "gen-visuals",
        "revoice", "assemble", "publish", "pull-analytics", "gen-shorts",
    })
