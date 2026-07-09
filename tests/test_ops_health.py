"""Key-free unit tests for the health snapshot helpers: log tailing for recent errors,
output/ disk usage per child, state counts + latest-per-video analytics averages over a
seeded DB, and that render() surfaces the key fields. No network, no API keys."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_operator.db.base import Base
from ai_operator.db.models import Upload, Video
from ai_operator.db.models_ops import Analytics
from ai_operator.db.state_machine import VideoState
from ai_operator.ops import health


def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'health.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


# --------------------------------------------------------------------------------------
# recent_errors — tail the rotating log for ERROR/ALERT
# --------------------------------------------------------------------------------------


def test_recent_errors_returns_only_error_and_alert_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "LOG_DIR", tmp_path)
    (tmp_path / "operator.log").write_text(
        "2026-07-09 INFO operator:x | started\n"
        "2026-07-09 ERROR operator:y | publish job failed for video 3\n"
        "2026-07-09 INFO operator:z | producing\n"
        "2026-07-09 WARNING ops.alerting:a | ALERT: OAuth keepalive FAILED\n"
    )
    errs = health.recent_errors(limit=5)
    assert len(errs) == 2
    assert "publish job failed" in errs[0]
    assert "ALERT" in errs[1]


def test_recent_errors_respects_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "LOG_DIR", tmp_path)
    (tmp_path / "operator.log").write_text("".join(f"ERROR line {i}\n" for i in range(10)))
    errs = health.recent_errors(limit=3)
    assert errs == ["ERROR line 7", "ERROR line 8", "ERROR line 9"]


def test_recent_errors_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "LOG_DIR", tmp_path)  # no operator.log written
    assert health.recent_errors() == []


# --------------------------------------------------------------------------------------
# disk_usage — total + per immediate child
# --------------------------------------------------------------------------------------


def test_disk_usage_reports_total_and_per_child(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "OUTPUT_DIR", tmp_path)
    (tmp_path / "1").mkdir()
    (tmp_path / "1" / "final.mp4").write_bytes(b"x" * 100)
    (tmp_path / "2").mkdir()
    (tmp_path / "2" / "body.mp4").write_bytes(b"y" * 50)
    (tmp_path / "loose.txt").write_bytes(b"z" * 10)

    usage = health.disk_usage()
    assert usage["total_bytes"] == 160
    assert usage["per_dir"] == {"1": 100, "2": 50}


def test_disk_usage_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "OUTPUT_DIR", tmp_path / "nope")
    assert health.disk_usage() == {"total_bytes": 0, "per_dir": {}}


def test_disk_usage_tolerates_broken_symlink(tmp_path, monkeypatch):
    # a dangling entry (e.g. a tree deleted mid-scan by the always-on cleanup) must be skipped,
    # not crash the read-only health snapshot
    import os

    monkeypatch.setattr(health, "OUTPUT_DIR", tmp_path)
    (tmp_path / "1").mkdir()
    (tmp_path / "1" / "final.mp4").write_bytes(b"x" * 100)
    os.symlink(tmp_path / "gone", tmp_path / "dangling")  # points at a nonexistent target

    usage = health.disk_usage()
    assert usage["total_bytes"] == 100
    assert usage["per_dir"] == {"1": 100}


# --------------------------------------------------------------------------------------
# DB aggregates — state counts + latest-per-video analytics averages
# --------------------------------------------------------------------------------------


def test_state_counts_group_by_state(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    with Session() as s:
        s.add(Video(idempotency_key="a", state=VideoState.DRAFT.value))
        s.add(Video(idempotency_key="b", state=VideoState.DRAFT.value))
        s.add(Video(idempotency_key="c", state=VideoState.PUBLISHED.value))
        s.commit()
    monkeypatch.setattr(health, "SessionLocal", Session)
    assert health._state_counts() == {"draft": 2, "published": 1}


def test_analytics_averages_use_latest_snapshot_per_video(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    with Session() as s:
        # two daily snapshots for the same video -> only the newest counts
        s.add(Analytics(youtube_video_id="v1", as_of_date=date(2026, 7, 1), views=100, avg_view_pct=20, ctr=2))
        s.add(Analytics(youtube_video_id="v1", as_of_date=date(2026, 7, 2), views=300, avg_view_pct=40, ctr=6))
        s.add(Analytics(youtube_video_id="v2", as_of_date=date(2026, 7, 2), views=500, avg_view_pct=50, ctr=4))
        s.commit()
    monkeypatch.setattr(health, "SessionLocal", Session)
    avg = health._analytics_averages()
    assert avg["videos"] == 2
    assert avg["avg_views"] == 400.0            # (300 + 500) / 2, older 100 ignored
    assert avg["avg_retention_pct"] == 45.0     # (40 + 50) / 2
    assert avg["avg_ctr"] == 5.0                # (6 + 4) / 2


def test_analytics_averages_empty(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    monkeypatch.setattr(health, "SessionLocal", Session)
    assert health._analytics_averages() == {
        "videos": 0, "avg_views": 0.0, "avg_retention_pct": 0.0, "avg_ctr": 0.0
    }


def test_last_publish_picks_most_recent_upload(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    with Session() as s:
        s.add(Upload(video_id=1, youtube_video_id="old", created_at=datetime(2026, 7, 1, tzinfo=timezone.utc)))
        s.add(Upload(video_id=2, youtube_video_id="new", created_at=datetime(2026, 7, 5, tzinfo=timezone.utc)))
        s.add(Upload(video_id=3, youtube_video_id=None, created_at=datetime(2026, 7, 9, tzinfo=timezone.utc)))
        s.commit()
    monkeypatch.setattr(health, "SessionLocal", Session)
    assert health._last_publish().startswith("2026-07-05")  # newest *confirmed* upload


def test_last_publish_none_when_no_uploads(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    monkeypatch.setattr(health, "SessionLocal", Session)
    assert health._last_publish() is None


# --------------------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------------------


def test_render_contains_key_sections():
    snap = {
        "generated_at": "2026-07-09T00:00:00+00:00",
        "states": {"draft": 2, "published": 1},
        "budget": {"ym": "2026-07", "spent": 12.5, "monthly_budget": 500.0, "remaining": 487.5},
        "char_quota": {"ym": "2026-07", "used": 70000, "quota": 100000, "pct_used": 70.0,
                       "alert": True, "exhausted": False},
        "yt_quota": {"used_today": 1600, "remaining": 8400},
        "last_publish": "2026-07-05T00:00:00+00:00",
        "analytics": {"videos": 3, "avg_views": 4200.0, "avg_retention_pct": 38.0, "avg_ctr": 4.5},
        "recent_errors": ["ERROR boom"],
        "disk": {"total_bytes": 1048576, "per_dir": {"1": 1048576}},
    }
    out = health.render(snap)
    for token in ("pipeline", "budget", "chars(11L)", "ALERT", "last pub", "analytics", "disk", "ERROR boom"):
        assert token in out
    assert "ctr=4.5%" in out


def test_render_shows_ctr_na_when_uncollected():
    snap = {
        "generated_at": "2026-07-09T00:00:00+00:00",
        "states": {},
        "budget": {"ym": "2026-07", "spent": 0.0, "monthly_budget": 500.0, "remaining": 500.0},
        "char_quota": {"ym": "2026-07", "used": 0, "quota": 100000, "pct_used": 0.0,
                       "alert": False, "exhausted": False},
        "yt_quota": {"used_today": 0, "remaining": 10000},
        "last_publish": None,
        "analytics": {"videos": 2, "avg_views": 300.0, "avg_retention_pct": 40.0, "avg_ctr": 0},
        "recent_errors": [],
        "disk": {"total_bytes": 0, "per_dir": {}},
    }
    assert "ctr=n/a" in health.render(snap)
