"""Live job/render status: the Jobs page self-polls and surfaces a running job's elapsed time
+ the video's pipeline position; _fmt_elapsed tolerates tz-naive timestamps from SQLite."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from ai_operator.db.engine import SessionLocal
from ai_operator.db.models import Video
from ai_operator.db.models_ops import Job
from ai_operator.db.state_machine import VideoState
from ai_operator.web import routes_ops
from ai_operator.web.app import create_app


@pytest.fixture
def client(temp_db, tmp_path):
    return TestClient(create_app(output_dir=tmp_path / "media"))


def test_fmt_elapsed_handles_naive_and_aware():
    now = datetime(2026, 7, 9, 12, 2, 0, tzinfo=timezone.utc)
    assert routes_ops._fmt_elapsed(None, now) is None
    naive = datetime(2026, 7, 9, 12, 0, 30)                 # tz-naive (as SQLite may return)
    assert routes_ops._fmt_elapsed(naive, now) == "1m 30s"
    aware = datetime(2026, 7, 9, 12, 1, 50, tzinfo=timezone.utc)
    assert routes_ops._fmt_elapsed(aware, now) == "10s"


def test_jobs_page_shows_running_strip_and_polls(client):
    with SessionLocal() as s:
        s.add(Video(id=1, idempotency_key="k", state=VideoState.VOICED.value, title="x"))
        s.add(Job(command="assemble", video_id=1, status="running", idempotency_key="j",
                  started_at=datetime.now(timezone.utc) - timedelta(seconds=95)))
        s.commit()
    html = client.get("/jobs").text
    assert 'hx-trigger="every 3s"' in html          # self-poll wired
    assert 'class="card ok"' in html                 # running-summary section only renders when a job runs
    assert 'class="pill running">assemble' in html   # the running job surfaced
    assert "1m" in html                              # elapsed surfaced

    data = client.get("/api/jobs").json()
    assert any(j["status"] == "running" and j["elapsed"] for j in data["jobs"])
