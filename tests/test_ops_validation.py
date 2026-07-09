"""Key-free unit tests for the P0 validation harness: the window aggregates correctly and
each classification boundary (window-fill, KILL retention/views/trend, strong vs marginal
PASS, policy strikes) flips at the documented threshold. No network, no API keys — a seeded
in-memory analytics dataset drives every case; the module's SessionLocal is swapped for it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_operator.db.base import Base
from ai_operator.db.models import Upload
from ai_operator.db.models_ops import Analytics, AppState
from ai_operator.ops import validation as v

_BASE = datetime(2026, 6, 1, tzinfo=timezone.utc)
_AS_OF = date(2026, 7, 1)


def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'val.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _seed(Session, specs, *, strikes: int | None = None):
    """specs: list of (views, retention, ctr), OLDEST first. One upload+analytics row each."""
    with Session() as s:
        for i, (views, ret, ctr) in enumerate(specs):
            yt = f"yt{i:03d}"
            s.add(Upload(video_id=i + 1, youtube_video_id=yt, created_at=_BASE + timedelta(days=i)))
            s.add(Analytics(youtube_video_id=yt, as_of_date=_AS_OF,
                            views=views, avg_view_pct=ret, ctr=ctr))
        if strikes is not None:
            s.add(AppState(key=v.STRIKES_KEY, value=str(strikes)))
        s.commit()


def _run(tmp_path, monkeypatch, specs, *, window=20, strikes=None):
    Session = _session_factory(tmp_path)
    _seed(Session, specs, strikes=strikes)
    monkeypatch.setattr(v, "SessionLocal", Session)
    return v.evaluate(window=window)


# --------------------------------------------------------------------------------------
# window-fill guard
# --------------------------------------------------------------------------------------


def test_insufficient_data_below_min_window(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, [(6000, 40, 5)] * (v.MIN_WINDOW - 1))
    assert r.decision == v.INSUFFICIENT
    assert r.filled == v.MIN_WINDOW - 1


def test_exactly_min_window_is_decidable(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, [(6000, 40, 5)] * v.MIN_WINDOW)
    assert r.decision != v.INSUFFICIENT
    assert r.filled == v.MIN_WINDOW


def test_videos_without_analytics_are_not_counted(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    _seed(Session, [(6000, 40, 5)] * v.MIN_WINDOW)
    with Session() as s:  # a published video with no analytics row yet -> not "measured"
        s.add(Upload(video_id=999, youtube_video_id="pending", created_at=_BASE + timedelta(days=99)))
        s.commit()
    monkeypatch.setattr(v, "SessionLocal", Session)
    assert v.evaluate().filled == v.MIN_WINDOW


# --------------------------------------------------------------------------------------
# KILL_P0
# --------------------------------------------------------------------------------------


def test_kill_on_flat_low_views_low_retention(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, [(1000, 20, 1)] * 12)
    assert r.decision == v.KILL
    assert not r.upward_trend


def test_upward_trend_blocks_kill(tmp_path, monkeypatch):
    # low views + low retention, but the later half out-views the earlier half -> not dead yet
    specs = [(500, 20, 1)] * 6 + [(1500, 20, 1)] * 6
    r = _run(tmp_path, monkeypatch, specs)
    assert r.upward_trend is True
    assert r.decision == v.PASS


def test_retention_at_kill_boundary_does_not_kill(tmp_path, monkeypatch):
    # retention == KILL_RETENTION_PCT is NOT < threshold -> no kill signal
    r = _run(tmp_path, monkeypatch, [(1000, v.KILL_RETENTION_PCT, 1)] * 12)
    assert r.decision == v.PASS


def test_views_at_kill_boundary_does_not_kill(tmp_path, monkeypatch):
    # avg_views == KILL_AVG_VIEWS is NOT < threshold -> no kill signal
    r = _run(tmp_path, monkeypatch, [(v.KILL_AVG_VIEWS, 20, 1)] * 12)
    assert r.decision == v.PASS


# --------------------------------------------------------------------------------------
# PASS_P0 — strong vs marginal
# --------------------------------------------------------------------------------------


def test_strong_pass_when_all_targets_met(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, [(6000, 40, 5)] * 12)
    assert r.decision == v.PASS
    assert r.strong_pass is True
    assert r.breakout_count == 12


def test_pass_boundaries_inclusive(tmp_path, monkeypatch):
    # retention/ctr/views exactly at the PASS thresholds still counts as a strong pass
    r = _run(tmp_path, monkeypatch,
             [(v.BREAKOUT_VIEWS, v.PASS_RETENTION_PCT, v.PASS_CTR_PCT)] * 12)
    assert r.decision == v.PASS
    assert r.strong_pass is True


def test_uncollected_ctr_does_not_block_strong_pass(tmp_path, monkeypatch):
    # ctr is not populated by the analytics puller yet -> an all-zero CTR must NOT be read as
    # a real 0% and sink the strong pass (otherwise strong_pass is unreachable in production)
    r = _run(tmp_path, monkeypatch, [(6000, 40, 0)] * 12)
    assert r.decision == v.PASS
    assert r.strong_pass is True
    assert "ctr" not in r.rationale


def test_marginal_pass_when_ctr_below_target(tmp_path, monkeypatch):
    # high views (no kill) + good retention, but CTR under target -> pass, not strong
    r = _run(tmp_path, monkeypatch, [(6000, 40, 2)] * 12)
    assert r.decision == v.PASS
    assert r.strong_pass is False
    assert "ctr" in r.rationale


def test_no_breakout_makes_pass_marginal(tmp_path, monkeypatch):
    # decent retention/ctr and enough views to dodge kill, but nothing breaks out
    r = _run(tmp_path, monkeypatch, [(3000, 40, 5)] * 12)
    assert r.decision == v.PASS
    assert r.strong_pass is False
    assert r.breakout_count == 0


def test_policy_strike_blocks_strong_pass(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, [(6000, 40, 5)] * 12, strikes=1)
    assert r.decision == v.PASS
    assert r.strong_pass is False
    assert r.strikes == 1
    assert "strike" in r.rationale


def test_missing_strike_key_defaults_to_zero(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, [(6000, 40, 5)] * 12)
    assert r.strikes == 0


# --------------------------------------------------------------------------------------
# aggregation details
# --------------------------------------------------------------------------------------


def test_latest_analytics_snapshot_wins(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    _seed(Session, [(6000, 40, 5)] * v.MIN_WINDOW)
    with Session() as s:  # add a newer, better snapshot for one video -> it must win
        s.add(Analytics(youtube_video_id="yt000", as_of_date=date(2026, 7, 15),
                        views=99_000, avg_view_pct=80, ctr=9))
        s.commit()
    monkeypatch.setattr(v, "SessionLocal", Session)
    r = v.evaluate()
    assert r.avg_views > 6000  # the 99k snapshot pulled the average up


def test_window_caps_to_most_recent(tmp_path, monkeypatch):
    # 15 videos but window=10 -> only the 10 newest are measured
    r = _run(tmp_path, monkeypatch, [(6000, 40, 5)] * 15, window=10)
    assert r.filled == 10


def test_render_shows_decision(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, [(6000, 40, 5)] * 12)
    out = v.render(r)
    assert "DECISION" in out and r.decision in out
