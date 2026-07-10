"""POST /videos/{id}/regenerate-shorts: enqueues gen-shorts(force) for a main, 400 for a short."""

import pytest
from fastapi.testclient import TestClient

from ai_operator.db.engine import SessionLocal
from ai_operator.db.models import Video
from ai_operator.db.models_ops import Job
from ai_operator.db.state_machine import VideoState
from ai_operator.web.app import create_app


@pytest.fixture
def client(temp_db):
    return TestClient(create_app())


def _seed(kind: str, parent_id: int | None = None) -> int:
    with SessionLocal() as s:
        v = Video(
            state=VideoState.PUBLISHED.value, kind=kind, parent_id=parent_id,
            idempotency_key=f"seed:{kind}:{parent_id}",
        )
        s.add(v)
        s.commit()
        return v.id


def test_regenerate_enqueues_forced_gen_shorts_for_main(client):
    main_id = _seed("main")
    r = client.post(f"/videos/{main_id}/regenerate-shorts", headers={"accept": "application/json"})
    assert r.status_code in (200, 303)
    with SessionLocal() as s:
        job = s.query(Job).filter_by(command="gen-shorts", video_id=main_id).one()
        assert job.params.get("force") is True


def test_regenerate_rejected_for_short(client):
    main_id = _seed("main")
    short_id = _seed("short", parent_id=main_id)
    r = client.post(f"/videos/{short_id}/regenerate-shorts")
    assert r.status_code == 400


def test_regenerate_404_for_missing_video(client):
    assert client.post("/videos/99999/regenerate-shorts").status_code == 404
