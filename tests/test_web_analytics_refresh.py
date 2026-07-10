"""The analytics refresh button enqueues a pull-analytics job (no network)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ai_operator.db.engine import SessionLocal
from ai_operator.db.models_ops import Job
from ai_operator.web.app import create_app


@pytest.fixture
def client(temp_db, tmp_path):
    return TestClient(create_app(output_dir=tmp_path / "media"))


def test_refresh_enqueues_pull_analytics(client):
    r = client.post("/api/analytics/refresh")
    assert r.status_code == 200 and r.json()["command"] == "pull-analytics"
    assert r.json()["status"] == "pending"
    with SessionLocal() as s:
        jobs = s.query(Job).filter_by(command="pull-analytics").all()
    assert len(jobs) == 1 and jobs[0].status == "pending"


def test_analytics_page_renders_with_chart(client):
    r = client.get("/analytics")
    assert r.status_code == 200 and "<svg" in r.text
    assert client.get("/api/analytics").headers["content-type"].startswith("application/json")
