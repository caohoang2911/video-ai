"""A short's archival anchor must come from its PARENT's event title, not the short's own
hook title. Short titles put the entity after an em-dash ("Butter... — Lusitania, 1915"),
which the ':'-split anchor logic can't parse -- anchoring on the parent keeps Commons
queries clean so the short gets real archival photos instead of falling through to SDXL."""

from ai_operator.media import visual_fetcher as vf
from ai_operator.db.engine import SessionLocal
from ai_operator.db.models import Video
from ai_operator.db.state_machine import VideoState


def test_short_anchors_on_parent_event_title(temp_db):
    with SessionLocal() as s:
        parent = Video(state=VideoState.PUBLISHED.value, idempotency_key="m:1", kind="main",
                       title="RMS Lusitania: The Cargo Manifest Britain Hid")
        s.add(parent)
        s.commit()
        pid = parent.id
        child = Video(state=VideoState.DRAFT.value, idempotency_key="s:1:0", kind="short",
                      parent_id=pid, title="Butter, Cheese, and Ammunition — Lusitania's Manifest, 1915")
        s.add(child)
        s.commit()
        cid = child.id

    assert vf._archival_anchor(cid) == "RMS Lusitania"   # parent's clean entity, not the hook
    assert vf._archival_anchor(pid) == "RMS Lusitania"   # main unchanged


def test_main_without_colon_returns_full_title(temp_db):
    with SessionLocal() as s:
        v = Video(state=VideoState.DRAFT.value, idempotency_key="m:2", kind="main",
                  title="The Halifax Explosion")
        s.add(v)
        s.commit()
        vid = v.id
    assert vf._archival_anchor(vid) == "The Halifax Explosion"
