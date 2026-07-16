"""retention_view read-layer: panel shape for the video-detail page — sparkline points,
hook-zone readouts at 2/5/10s, sibling-shorts overlay, and the explicit empty states
(never uploaded -> None; uploaded but no curve rows -> points None, not a blank chart)."""

from __future__ import annotations

from datetime import date

import pytest

from ai_operator.db.engine import SessionLocal
from ai_operator.db.models import Upload, Video
from ai_operator.db.models_ops import Analytics, RetentionCurve
from ai_operator.db.state_machine import VideoState
from ai_operator.web.retention_view import retention_panel


def _mk_video(s, *, kind="main", parent_id=None, title=None, key: str = "k") -> int:
    v = Video(state=VideoState.PUBLISHED.value, idempotency_key=f"rv:{key}", kind=kind,
              parent_id=parent_id, title=title)
    s.add(v)
    s.commit()
    return v.id


def _mk_upload(s, video_id: int, yt_id: str) -> None:
    s.add(Upload(video_id=video_id, youtube_video_id=yt_id, status="published"))
    s.commit()


def _mk_curve(s, yt_id: str, ratios_watch: list[tuple[float, float]]) -> None:
    s.add_all(RetentionCurve(youtube_video_id=yt_id, elapsed_ratio=r, watch_ratio=w)
              for r, w in ratios_watch)
    s.commit()


def test_panel_none_for_video_never_uploaded(temp_db):
    with SessionLocal() as s:
        vid = _mk_video(s, key="nou")
    assert retention_panel(vid, 600) is None


def test_panel_reports_no_curve_yet_for_uploaded_video_without_rows(temp_db):
    with SessionLocal() as s:
        vid = _mk_video(s, key="empty")
        _mk_upload(s, vid, "ytA")
    panel = retention_panel(vid, 600)
    assert panel is not None
    assert panel["points"] is None and panel["hook_zone"] == [] and panel["siblings"] == []


def test_panel_points_hook_zone_and_views(temp_db):
    with SessionLocal() as s:
        vid = _mk_video(s, key="full")
        _mk_upload(s, vid, "ytB")
        # 100s video: buckets at 2%,5%,10% map to seconds 2,5,10 exactly
        _mk_curve(s, "ytB", [(0.0, 1.0), (0.02, 0.9), (0.05, 0.7), (0.10, 0.55), (1.0, 0.2)])
        s.add(Analytics(youtube_video_id="ytB", as_of_date=date(2026, 7, 14), views=800))
        s.add(Analytics(youtube_video_id="ytB", as_of_date=date(2026, 7, 15), views=1000))
        s.commit()
    panel = retention_panel(vid, 100)
    assert panel["views"] == 1000  # newest snapshot
    assert panel["points"].startswith("0.0,")
    assert len(panel["points"].split()) == 5
    assert panel["hook_zone"] == [
        {"sec": 2, "pct": 90.0}, {"sec": 5, "pct": 70.0}, {"sec": 10, "pct": 55.0},
    ]


def test_hook_zone_empty_without_duration(temp_db):
    with SessionLocal() as s:
        vid = _mk_video(s, key="nodur")
        _mk_upload(s, vid, "ytC")
        _mk_curve(s, "ytC", [(0.0, 1.0)])
    assert retention_panel(vid, None)["hook_zone"] == []


def test_watch_ratio_above_axis_cap_is_clamped_in_points(temp_db):
    with SessionLocal() as s:
        vid = _mk_video(s, key="loop")
        _mk_upload(s, vid, "ytD")
        _mk_curve(s, "ytD", [(0.0, 2.0)])  # heavy-loop short: ratio > axis max
    y = float(retention_panel(vid, 30)["points"].split(",")[1])
    assert y == 0.0  # clamped to the top of the chart, not a negative overflow


def test_sibling_shorts_with_curves_are_overlaid(temp_db):
    with SessionLocal() as s:
        parent = _mk_video(s, key="par")
        _mk_upload(s, parent, "ytP")
        _mk_curve(s, "ytP", [(0.0, 1.0)])
        s1 = _mk_video(s, kind="short", parent_id=parent, title="Angle one", key="s1")
        _mk_upload(s, s1, "ytS1")
        _mk_curve(s, "ytS1", [(0.0, 1.0), (1.0, 0.6)])
        s2 = _mk_video(s, kind="short", parent_id=parent, title="Angle two (no curve)", key="s2")
        _mk_upload(s, s2, "ytS2")  # uploaded but no curve rows yet -> excluded from overlay
        _mk_video(s, kind="short", parent_id=parent, key="s3")  # never uploaded -> excluded
    sibs = retention_panel(parent, 600)["siblings"]
    assert [x["video_id"] for x in sibs] == [s1]
    assert sibs[0]["title"] == "Angle one"
    assert " " in sibs[0]["points"]
