"""APScheduler jobs: produce drafts, publish approved ones at a randomized cadence, pull
analytics, keep the OAuth token alive.

The ElevenLabs monthly CHARACTER ledger is the hard cap; `WEEKLY_VIDEO_CAP` is only a soft
cadence knob tuned to stay under it. Produce/publish check the char guard FIRST and skip+alert
when the month's quota is spent, rather than generating a video that would just land in
`needs_revoice`. Publish times are randomized (jitter), never fixed slots, to avoid an
algorithmically detectable upload template.
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..config import settings
from ..cost import elevenlabs_char_guard as char_guard
from ..db.engine import SessionLocal
from ..db.models import Video
from ..db.state_machine import VideoState
from ..logging_setup import get_logger
from ..publisher import quota_throttle
from ..publisher.publish import publish
from . import alerting, analytics_puller, job_worker, keepalive, pipeline_runner

log = get_logger("ops.scheduler")

MAX_PUBLISH_JITTER_HOURS = 48  # randomize go-live inside the weekly window (not a fixed daily slot)
_rng = random.Random()         # module-level; tests inject a seeded Random for determinism


def jittered_publish_at(now: datetime, rng: random.Random, max_jitter_hours: int = MAX_PUBLISH_JITTER_HOURS) -> str:
    """A randomized `publishAt` within [now, now+max_jitter_hours], ISO-8601 UTC with a 'Z'."""
    jitter = rng.randint(0, max_jitter_hours * 3600)
    dt = now.astimezone(timezone.utc) + timedelta(seconds=jitter)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def produce_skip_reason() -> str | None:
    """None = ok to produce; else why to skip (monthly ElevenLabs char quota exhausted)."""
    status = char_guard.check_char_quota()
    if status.exhausted:
        return f"ElevenLabs char quota exhausted ({status.chars_used}/{status.quota}) for {status.ym}"
    return None


def publish_skip_reason() -> str | None:
    """None = ok to publish; else why to skip. Publishing an already-voiced video spends NO
    ElevenLabs chars, so publish is deliberately NOT char-gated -- gating it would idle the
    approved backlog at month-end for no saving. Only the weekly cadence cap applies here."""
    if not quota_throttle.throttle_ok():
        return f"weekly cadence cap reached ({quota_throttle.uploads_last_7_days()}/{settings.WEEKLY_VIDEO_CAP} in 7d)"
    return None


def _next_approved_video_id() -> int | None:
    with SessionLocal() as s:
        v = s.scalar(
            select(Video)
            .where(Video.state == VideoState.APPROVED.value, Video.needs_revoice.is_(False))
            .order_by(Video.id)
        )
        return v.id if v else None


def produce_job() -> None:
    reason = produce_skip_reason()
    if reason:
        alerting.alert(f"produce skipped — {reason}")  # quota exhausted: no more videos this month
        return
    try:
        vid = pipeline_runner.run_new()
        log.info("produce: produced video %s", vid) if vid else log.info("produce: no topic available")
    except Exception as exc:  # noqa: BLE001 - a scheduler job must never kill the loop
        log.error("produce job failed: %s", exc)


def publish_job(now: datetime | None = None) -> None:
    reason = publish_skip_reason()
    if reason:
        log.info("publish skipped — %s", reason)  # routine cadence throttle, not an alert
        return
    video_id = _next_approved_video_id()
    if video_id is None:
        log.info("publish: no approved video ready")
        return
    publish_at = jittered_publish_at(now or datetime.now(timezone.utc), _rng)
    try:
        yt = publish(video_id, publish_at_iso=publish_at)
        log.info("publish: video %s -> youtube %s scheduled at %s", video_id, yt, publish_at)
    except Exception as exc:  # noqa: BLE001
        log.error("publish job failed for video %s: %s", video_id, exc)


def analytics_job() -> None:
    try:
        log.info("analytics: updated %d video(s)", analytics_puller.pull_all())
    except Exception as exc:  # noqa: BLE001
        log.error("analytics job failed: %s", exc)


def keepalive_job() -> None:
    try:
        keepalive.refresh_token()
    except Exception as exc:  # noqa: BLE001
        # A dead refresh token silently breaks every future upload -- alert loudly, not just log.
        alerting.alert(f"OAuth keepalive FAILED (uploads will break until re-auth): {exc}")


def build_scheduler():
    """BackgroundScheduler with all jobs wired at their cadences. Jobs self-guard on missing
    config, so starting unconfigured is a safe no-op loop."""
    from apscheduler.schedulers.background import BackgroundScheduler

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(produce_job, "interval", days=2, id="produce")     # keep a review backlog stocked
    sched.add_job(publish_job, "interval", hours=6, id="publish")    # frequent scan; char/cap gate the rate
    sched.add_job(analytics_job, "interval", days=1, id="analytics")
    sched.add_job(keepalive_job, "interval", days=25, id="keepalive")  # well under the 6-month token expiry
    # Drain the control-panel job queue frequently; max_instances=1 keeps jobs sequential (one
    # writer) and coalesce collapses ticks that pile up behind a long-running job.
    sched.add_job(job_worker.drain_jobs, "interval", seconds=20, id="jobs", max_instances=1, coalesce=True)
    return sched


def run_scheduler() -> None:
    """Foreground blocking run: start the scheduler and idle until interrupted."""
    job_worker.requeue_orphaned_jobs()  # recover any job interrupted by a prior crash/restart
    sched = build_scheduler()
    sched.start()
    log.info("scheduler started (produce/publish/analytics/keepalive/jobs) — Ctrl-C to stop")
    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()
        log.info("scheduler stopped")
