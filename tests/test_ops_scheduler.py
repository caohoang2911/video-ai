"""Key-free unit tests for the ops scheduler decision logic: publish-time jitter stays inside
the weekly window (frozen clock + seeded rng), and produce/publish skip+alert when the monthly
ElevenLabs char quota is exhausted or the weekly cadence cap is hit. No APScheduler run, no
network, no API keys."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from ai_operator.cost import elevenlabs_char_guard as char_guard
from ai_operator.ops import scheduler


def _status(*, exhausted=False, used=0) -> char_guard.CharQuotaStatus:
    quota = char_guard.CREATOR_TIER_MONTHLY_CHAR_QUOTA
    return char_guard.CharQuotaStatus(
        ym="2026-07", chars_used=used, quota=quota, pct_used=used / quota,
        alert=used >= quota * char_guard.ALERT_THRESHOLD_PCT, exhausted=exhausted,
    )


def _parse(z: str) -> datetime:
    return datetime.fromisoformat(z.replace("Z", "+00:00"))


# --------------------------------------------------------------------------------------
# publish-time jitter
# --------------------------------------------------------------------------------------


def test_jitter_stays_within_the_weekly_window_across_seeds():
    now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
    window_h = 48
    for seed in range(200):
        dt = _parse(scheduler.jittered_publish_at(now, random.Random(seed), max_jitter_hours=window_h))
        assert now <= dt <= now + timedelta(hours=window_h)


def test_jitter_is_deterministic_for_a_given_seed():
    now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
    a = scheduler.jittered_publish_at(now, random.Random(7))
    b = scheduler.jittered_publish_at(now, random.Random(7))
    assert a == b


def test_jitter_is_not_a_fixed_slot():
    now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
    times = {scheduler.jittered_publish_at(now, random.Random(s)) for s in range(20)}
    assert len(times) > 1  # varied publish times, not one fixed slot


# --------------------------------------------------------------------------------------
# produce / publish skip reasons
# --------------------------------------------------------------------------------------


def test_produce_skips_when_char_quota_exhausted(monkeypatch):
    monkeypatch.setattr(scheduler.char_guard, "check_char_quota", lambda: _status(exhausted=True, used=100_000))
    assert "exhausted" in (scheduler.produce_skip_reason() or "")


def test_produce_ok_when_quota_healthy(monkeypatch):
    monkeypatch.setattr(scheduler.char_guard, "check_char_quota", lambda: _status(used=10_000))
    assert scheduler.produce_skip_reason() is None


def test_publish_skips_when_char_quota_exhausted(monkeypatch):
    monkeypatch.setattr(scheduler.char_guard, "check_char_quota", lambda: _status(exhausted=True, used=100_000))
    monkeypatch.setattr(scheduler.quota_throttle, "throttle_ok", lambda: True)
    assert "exhausted" in (scheduler.publish_skip_reason() or "")


def test_publish_skips_when_weekly_cadence_cap_reached(monkeypatch):
    monkeypatch.setattr(scheduler.char_guard, "check_char_quota", lambda: _status(used=10_000))
    monkeypatch.setattr(scheduler.quota_throttle, "throttle_ok", lambda: False)
    monkeypatch.setattr(scheduler.quota_throttle, "uploads_last_7_days", lambda: 3)
    assert "cadence cap" in (scheduler.publish_skip_reason() or "")


def test_publish_ok_when_under_cap_and_quota(monkeypatch):
    monkeypatch.setattr(scheduler.char_guard, "check_char_quota", lambda: _status(used=10_000))
    monkeypatch.setattr(scheduler.quota_throttle, "throttle_ok", lambda: True)
    assert scheduler.publish_skip_reason() is None


def test_produce_job_does_not_produce_when_exhausted(monkeypatch):
    monkeypatch.setattr(scheduler, "produce_skip_reason", lambda: "quota exhausted")
    called = []
    monkeypatch.setattr(scheduler.pipeline_runner, "run_new", lambda *a, **k: called.append(True))
    scheduler.produce_job()
    assert called == []  # skipped: never entered production


def test_publish_job_does_not_publish_when_exhausted(monkeypatch):
    monkeypatch.setattr(scheduler, "publish_skip_reason", lambda: "quota exhausted")
    published = []
    monkeypatch.setattr(scheduler, "publish", lambda *a, **k: published.append(True))
    scheduler.publish_job()
    assert published == []
