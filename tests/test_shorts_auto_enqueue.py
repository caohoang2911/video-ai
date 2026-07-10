"""Publishing a MAIN auto-enqueues exactly one gen-shorts job; shorts and re-publishes don't."""

import pytest

from ai_operator.db.engine import SessionLocal
from ai_operator.db.models import Video
from ai_operator.db.models_ops import Job
from ai_operator.db.state_machine import VideoState
from ai_operator.publisher.publish import _try_enqueue_shorts


@pytest.fixture
def db(temp_db):
    return temp_db


def _seed(kind: str, parent_id: int | None = None) -> int:
    with SessionLocal() as s:
        v = Video(
            state=VideoState.PUBLISHED.value, kind=kind, parent_id=parent_id,
            idempotency_key=f"seed:{kind}:{parent_id}",
        )
        s.add(v)
        s.commit()
        return v.id


def _jobs(video_id: int) -> list[Job]:
    with SessionLocal() as s:
        return s.query(Job).filter_by(command="gen-shorts", video_id=video_id).all()


def test_published_main_enqueues_one_gen_shorts(db):
    main_id = _seed("main")
    _try_enqueue_shorts(main_id)
    assert len(_jobs(main_id)) == 1
    _try_enqueue_shorts(main_id)  # double-publish/retry: queue dedup keeps it at one
    assert len(_jobs(main_id)) == 1


def test_published_short_enqueues_nothing(db):
    main_id = _seed("main")
    short_id = _seed("short", parent_id=main_id)
    _try_enqueue_shorts(short_id)
    assert _jobs(short_id) == []


def test_main_with_existing_children_enqueues_nothing(db):
    main_id = _seed("main")
    _seed("short", parent_id=main_id)
    _try_enqueue_shorts(main_id)
    assert _jobs(main_id) == []
