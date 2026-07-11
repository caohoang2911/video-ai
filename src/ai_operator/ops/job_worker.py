"""Consumer side of the DB job queue.

The web control panel enqueues `pending` rows (web.job_queue); this worker — driven by the
scheduler every ~20s — atomically claims one job at a time and dispatches it to the *existing*
pipeline callables. Zero pipeline logic lives here: DISPATCH is the only place a command string
binds to a function, so the queue stays a thin transport over code the CLI already runs.

Single-worker + guarded claim (`max_instances=1` on the scheduler side) means jobs run
sequentially in id order, each exactly once — no SQLite writer contention, no double-execute.
A handler that raises marks its own job `failed` (with the error text) and never propagates,
so one bad job can't kill the drain loop or the scheduler.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select, update

from ..assembler.thumbnail_generator import generate as generate_thumbnails
from ..assembler.video_builder import assemble_video
from ..content import topic_backlog
from ..db.engine import SessionLocal
from ..db.models_ops import Job
from ..logging_setup import get_logger
from ..media import commands as media_commands
from ..publisher.publish import publish
from . import analytics_puller, pipeline_runner

log = get_logger("ops.job_worker")

_MAX_DRAIN_PER_TICK = 5  # cap iterations so one tick can't loop forever draining a hot backlog
_rng = random.Random()   # publish jitter; module-level so tests can seed it


def _param(job: Job, key: str, default: Any = None) -> Any:
    return (job.params or {}).get(key, default)


def _require_video(job: Job) -> int:
    if job.video_id is None:
        raise ValueError(f"job {job.id} ({job.command}) requires a video_id")
    return job.video_id


# --- command handlers: each reuses an existing pipeline callable, nothing new ----------

def _produce(job: Job) -> None:
    pipeline_runner.run_new(topic_id=job.topic_id, motion=bool(_param(job, "motion", False)))


def _gen_topics(job: Job) -> None:
    topic_backlog.seed_backlog()
    topic_backlog.suggest_topics(int(_param(job, "n", 5)))


def _gen_audio(job: Job) -> None:
    media_commands.gen_audio(video_id=_require_video(job))


def _gen_visuals(job: Job) -> None:
    # typer trap: calling a typer command as a plain function leaves unpassed options as
    # OptionInfo objects — which are TRUTHY. `gen_all` unset therefore silently forced
    # every queued gen-visuals run into all-SDXL mode (skipping archival/stock tiers),
    # so every option must be passed explicitly here.
    media_commands.gen_visuals(
        video_id=_require_video(job),
        motion=bool(_param(job, "motion", False)),
        gen_all=bool(_param(job, "gen_all", False)),
    )


def _revoice(job: Job) -> None:
    media_commands.revoice(video_id=_require_video(job))


def _assemble(job: Job) -> None:
    video_id = _require_video(job)
    assemble_video(video_id)
    generate_thumbnails(video_id)  # mirrors the `assemble` CLI command (render + thumbs)


def _publish(job: Job) -> None:
    from .scheduler import jittered_publish_at  # local import breaks the scheduler<->worker cycle

    publish_at = _param(job, "publish_at_iso") or jittered_publish_at(
        datetime.now(timezone.utc), _rng
    )
    publish(_require_video(job), publish_at_iso=publish_at)


def _pull_analytics(_job: Job) -> None:
    analytics_puller.pull_all()


def _gen_shorts(job: Job) -> None:
    from . import shorts_runner  # local import: shorts pull in LLM/render deps lazily

    shorts_runner.generate_shorts(_require_video(job), force=bool(_param(job, "force", False)))


# The ONLY command->function binding. Kept in lockstep with web.job_queue.JOB_COMMANDS
# (a test asserts the two sets are equal), so no command can be enqueued without a handler.
DISPATCH: dict[str, Callable[[Job], Any]] = {
    "produce": _produce,
    "gen-topics": _gen_topics,
    "gen-audio": _gen_audio,
    "gen-visuals": _gen_visuals,
    "revoice": _revoice,
    "assemble": _assemble,
    "publish": _publish,
    "pull-analytics": _pull_analytics,
    "gen-shorts": _gen_shorts,
}


def claim_next() -> Job | None:
    """Atomically flip the oldest `pending` job to `running` and return it, or None if the
    queue is empty. The guarded UPDATE (status still 'pending') is the single-execute lock:
    if a racing claimer already took it, rowcount is 0 and we report empty."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as s:
        job_id = s.scalar(
            select(Job.id).where(Job.status == "pending").order_by(Job.id).limit(1)
        )
        if job_id is None:
            return None
        claimed = s.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "pending")
            .values(status="running", started_at=now)
        )
        s.commit()
        if claimed.rowcount != 1:
            return None  # lost the race; another claimer took it
        return s.get(Job, job_id)


def requeue_orphaned_jobs() -> int:
    """Reset jobs left `running` by a previous process back to `pending`.

    The worker is single-instance, so no job can legitimately be `running` at a fresh scheduler
    start — any such row is an orphan from a crash/restart mid-job. Left alone it is never re-run
    AND (enqueue dedups against pending|running) permanently blocks re-enqueuing the same work,
    silently no-op'ing the panel button. Called once at startup, before the drain loop begins."""
    with SessionLocal() as s:
        result = s.execute(
            update(Job)
            .where(Job.status == "running")
            .values(status="pending", started_at=None, error="requeued after an interrupted run")
        )
        s.commit()
    if result.rowcount:
        log.warning("requeued %d orphaned running job(s) after restart", result.rowcount)
    return result.rowcount


def _finish(job_id: int, status: str, error: str | None) -> None:
    with SessionLocal() as s:
        s.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status=status, error=error, finished_at=datetime.now(timezone.utc))
        )
        s.commit()


def run_job(job: Job) -> None:
    """Dispatch one claimed job to its handler; record done|failed. Never re-raises — a
    scheduler-driven worker must survive any single job's failure."""
    try:
        DISPATCH[job.command](job)
    except Exception as exc:  # noqa: BLE001 - isolate the failure to this one job
        log.error("job %s (%s) failed: %s", job.id, job.command, exc)
        _finish(job.id, "failed", str(exc)[:2000] or repr(exc)[:2000])
        return
    _finish(job.id, "done", None)
    log.info("job %s (%s) done", job.id, job.command)


def drain_jobs() -> int:
    """Run pending jobs sequentially until the queue is empty or the per-tick cap is hit.
    Returns how many jobs ran this tick. Wired into the scheduler at a short interval."""
    ran = 0
    for _ in range(_MAX_DRAIN_PER_TICK):
        job = claim_next()
        if job is None:
            break
        run_job(job)
        ran += 1
    return ran
