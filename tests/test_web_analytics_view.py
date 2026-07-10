"""Analytics read-layer: overview() builds channel totals, top ranking, cumulative trend, and
freshness from seeded rows; and health.latest_analytics_per_video is the single dedup source."""

from __future__ import annotations

import json
from datetime import date, timedelta

from ai_operator.db.engine import SessionLocal
from ai_operator.db.models_ops import Analytics, AppState
from ai_operator.ops import health
from ai_operator.web import analytics_view


def _seed():
    d0, d1 = date.today() - timedelta(days=3), date.today()
    rows = {"A": (1000, 3000), "B": (500, 900), "C": (200, 2200)}
    with SessionLocal() as s:
        for vid, (v0, v1) in rows.items():
            s.add(Analytics(youtube_video_id=vid, as_of_date=d0, views=v0, avg_view_pct=50.0, ctr=5.0))
            s.add(Analytics(youtube_video_id=vid, as_of_date=d1, views=v1, avg_view_pct=50.0, ctr=5.0))
        s.add(AppState(key="channel_stats", value=json.dumps(
            {"subscribers": 1234, "total_views": 56789, "video_count": 12, "fetched_at": "2026-07-09T00:00:00+00:00"})))
        s.commit()
    return d0, d1


def test_overview_top_ranked_by_views(temp_db):
    _seed()
    o = analytics_view.overview()
    assert o["top"][0]["youtube_video_id"] == "A"       # 3000 highest
    assert o["top"][0]["views"] == 3000
    assert [v["youtube_video_id"] for v in o["top"]] == ["A", "C", "B"]  # 3000, 2200, 900


def test_overview_channel_and_freshness(temp_db):
    _seed()
    o = analytics_view.overview()
    assert o["channel"]["subscribers"] == 1234
    assert o["freshness"]["last_pull"] is not None
    assert o["freshness"]["channel_fetched_at"] == "2026-07-09T00:00:00+00:00"


def test_trend_is_cumulative_sum_per_date(temp_db):
    d0, d1 = _seed()
    trend = analytics_view.trend_series()
    assert trend["dates"] == [d0.isoformat(), d1.isoformat()]   # sorted, unique
    assert trend["views"] == [1700, 6100]                        # 1000+500+200, 3000+900+2200


def test_empty_db_gives_empty_series_no_crash(temp_db):
    o = analytics_view.overview()
    assert o["per_video"] == [] and o["top"] == [] and o["trend"]["dates"] == []
    assert o["channel"] is None


def test_latest_per_video_is_one_row_each(temp_db):
    _seed()
    latest = health.latest_analytics_per_video()
    assert len(latest) == 3                                       # deduped to newest per video
    assert all(a.as_of_date == date.today() for a in latest)      # the newest date
