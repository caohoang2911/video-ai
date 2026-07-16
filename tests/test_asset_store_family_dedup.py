"""asset_store md5 dedup scope: a main video dedups against its own assets only; a short
dedups against its whole FAMILY (parent + siblings). Sibling shorts refetch from the same
Commons pool with near-identical queries — self-scoped dedup let them all save the same
top-ranked photos (shorts 25/27 shipped with 5/6 identical stills)."""

from __future__ import annotations

from ai_operator.db.engine import SessionLocal
from ai_operator.db.models import Asset, Video
from ai_operator.db.state_machine import VideoState
from ai_operator.media import asset_store


def _add_video(key: str, kind: str = "main", parent_id: int | None = None) -> int:
    with SessionLocal() as s:
        v = Video(state=VideoState.DRAFT.value, idempotency_key=key, kind=kind, parent_id=parent_id)
        s.add(v)
        s.commit()
        return v.id


def _add_asset(video_id: int, md5: str) -> None:
    with SessionLocal() as s:
        s.add(Asset(video_id=video_id, kind="archival", source="wikimedia",
                    url_or_path="x.jpg", license="PD", md5=md5))
        s.commit()


def test_short_dedups_against_parent_and_every_sibling(temp_db):
    parent = _add_video("main:family")
    sibling = _add_video("short:family:0", kind="short", parent_id=parent)
    fresh = _add_video("short:family:1", kind="short", parent_id=parent)
    _add_asset(parent, "md5-parent-still")
    _add_asset(sibling, "md5-sibling-still")

    # the fresh short has NO rows of its own, yet must see the whole family's images
    assert asset_store._existing_md5s(fresh) == {"md5-parent-still", "md5-sibling-still"}


def test_main_dedup_scope_stays_self_only(temp_db):
    mine = _add_video("main:mine")
    unrelated = _add_video("main:unrelated")
    _add_asset(mine, "md5-own")
    _add_asset(unrelated, "md5-unrelated")

    assert asset_store._existing_md5s(mine) == {"md5-own"}
