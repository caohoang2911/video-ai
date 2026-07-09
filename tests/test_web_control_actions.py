"""Control POSTs: web decision == direct record_decision (parity), stale transition handled
gracefully, enqueue POST creates a pending job, EDIT_* applies metadata in one request."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ai_operator.db.engine import SessionLocal
from ai_operator.db.models import Decision, Video
from ai_operator.db.models_ops import Job
from ai_operator.db.state_machine import VideoState
from ai_operator.web.app import create_app


@pytest.fixture
def client(temp_db, tmp_path):
    return TestClient(create_app(output_dir=tmp_path / "media"))


def _seed(state: str, **kw) -> int:
    with SessionLocal() as s:
        v = Video(idempotency_key=kw.pop("idempotency_key", "k1"), state=state, **kw)
        s.add(v)
        s.commit()
        return v.id


def test_decision_matches_direct_record_decision(client):
    vid = _seed(VideoState.PENDING_REVIEW.value)
    r = client.post(f"/api/videos/{vid}/decision", data={"code": "PASS_POLICY"})
    assert r.status_code == 200 and r.json()["state"] == "policy_ok"

    with SessionLocal() as s:
        v = s.get(Video, vid)
        decisions = s.query(Decision).filter_by(video_id=vid).all()
    assert v.state == VideoState.POLICY_OK.value                 # same state the bot would set
    assert len(decisions) == 1 and decisions[0].decision_code == "PASS_POLICY"  # same audit row


def test_stale_decision_is_409_not_500(client):
    vid = _seed(VideoState.PENDING_REVIEW.value)
    client.post(f"/api/videos/{vid}/decision", data={"code": "PASS_POLICY"})
    again = client.post(f"/api/videos/{vid}/decision", data={"code": "PASS_POLICY"})
    assert again.status_code == 409                              # graceful, not a crash


def test_unknown_decision_code_is_400(client):
    vid = _seed(VideoState.PENDING_REVIEW.value)
    assert client.post(f"/api/videos/{vid}/decision", data={"code": "NONSENSE"}).status_code == 400


def test_other_code_requires_reason(client):
    vid = _seed(VideoState.PENDING_REVIEW.value)
    r = client.post(f"/api/videos/{vid}/decision", data={"code": "REJECT_POLICY_OTHER"})
    assert r.status_code == 400


def test_edit_applies_metadata_in_one_request(client):
    vid = _seed(VideoState.POLICY_OK.value)
    r = client.post(
        f"/api/videos/{vid}/decision",
        data={"code": "EDIT_OTHER", "reason": "tighten", "title": "NEW", "tags": "x, y"},
    )
    assert r.status_code == 200 and r.json()["state"] == "editing"
    with SessionLocal() as s:
        v = s.get(Video, vid)
    assert v.title == "NEW" and v.tags == ["x", "y"]


def test_enqueue_post_creates_pending_job(client):
    vid = _seed(VideoState.APPROVED.value)
    r = client.post(f"/api/videos/{vid}/enqueue/publish")
    assert r.status_code == 200 and r.json()["status"] == "pending"
    with SessionLocal() as s:
        jobs = s.query(Job).filter_by(command="publish", video_id=vid).all()
    assert len(jobs) == 1 and jobs[0].status == "pending"


def test_enqueue_rejects_non_video_command(client):
    vid = _seed(VideoState.APPROVED.value)
    assert client.post(f"/api/videos/{vid}/enqueue/gen-topics").status_code == 400


def test_generic_enqueue_rejects_unknown_command(client):
    assert client.post("/api/jobs", data={"command": "wipe-everything"}).status_code == 400


def test_enqueue_missing_video_is_400_not_500(temp_db_fk, tmp_path):
    # FK enforcement on: enqueueing against a video that doesn't exist must be a clean 400,
    # not a leaked IntegrityError 500.
    c = TestClient(create_app(output_dir=tmp_path / "media"))
    r = c.post("/api/videos/999999/enqueue/publish")
    assert r.status_code == 400
    r = c.post("/api/jobs", data={"command": "publish", "video_id": 999999})
    assert r.status_code == 400
    r = c.post("/api/topics/999999/produce")
    assert r.status_code == 400
