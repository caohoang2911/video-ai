"""Read views render from the live DB (HTML) and negotiate JSON under /api. No network:
the temp_db fixture rebinds SessionLocal; create_app's media mount points at tmp_path."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ai_operator.db.engine import SessionLocal
from ai_operator.db.models import Video
from ai_operator.db.state_machine import VideoState
from ai_operator.web.app import create_app


@pytest.fixture
def client(temp_db, tmp_path):
    return TestClient(create_app(output_dir=tmp_path / "media"))


def _seed_video(**kw) -> int:
    with SessionLocal() as s:
        v = Video(idempotency_key=kw.pop("idempotency_key", "k1"), **kw)
        s.add(v)
        s.commit()
        return v.id


def test_html_pages_render(client):
    for path in ["/", "/videos", "/topics", "/jobs", "/costs", "/analytics"]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("text/html")


def test_api_variants_return_json(client):
    for path in ["/api/", "/api/videos", "/api/jobs", "/api/costs", "/api/analytics", "/api/topics"]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("application/json"), path


def test_video_shows_in_list_and_detail(client):
    vid = _seed_video(state=VideoState.PENDING_REVIEW.value, title="hello world")

    listing = client.get("/api/videos").json()
    assert any(v["id"] == vid and v["title"] == "hello world" for v in listing["videos"])

    detail = client.get(f"/api/videos/{vid}").json()
    assert detail["video"]["id"] == vid
    assert "assets" in detail and "costs" in detail and "decisions" in detail
    # PENDING_REVIEW can legally transition to POLICY_OK -> PASS_POLICY offered
    assert "PASS_POLICY" in detail["allowed_decisions"]

    assert client.get(f"/videos/{vid}").status_code == 200      # HTML detail renders


def test_missing_video_is_404(client):
    assert client.get("/api/videos/424242").status_code == 404


def test_state_filter(client):
    _seed_video(idempotency_key="a", state=VideoState.APPROVED.value)
    _seed_video(idempotency_key="b", state=VideoState.DRAFT.value)
    approved = client.get("/api/videos?state=approved").json()["videos"]
    assert approved and all(v["state"] == "approved" for v in approved)
