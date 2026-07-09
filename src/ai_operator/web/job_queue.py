"""Enqueue side of the DB job queue (producer).

The web panel calls `enqueue(...)` to request heavy pipeline work; the scheduler's drain
loop (ops.job_worker) consumes it. Enqueue is idempotent: a double-click while a matching
job is still pending/running reuses that row instead of inserting a duplicate.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..db.engine import SessionLocal
from ..db.models_ops import Job
from ..logging_setup import get_logger

log = get_logger("web.job_queue")

# The ONLY commands the panel may enqueue. Every entry must have a matching handler in
# ops.job_worker.DISPATCH (a test asserts the two sets are equal). `gen-script` is
# intentionally absent: scripting is reachable only via `produce` (pipeline_runner.run_new).
JOB_COMMANDS: frozenset[str] = frozenset(
    {
        "produce",         # pick/advance a topic -> scripted draft (run_new)
        "gen-topics",      # seed backlog + LLM-suggest new angles
        "gen-audio",       # narrate an existing video
        "gen-visuals",     # fetch b-roll / stills for a video
        "revoice",         # force brand-voice re-synth
        "assemble",        # rebuild final.mp4
        "publish",         # upload an approved video
        "pull-analytics",  # refresh YouTube analytics
    }
)

_ACTIVE_STATUSES = ("pending", "running")


def _idem_key(
    command: str, video_id: int | None, topic_id: int | None, params: dict[str, Any] | None
) -> str:
    """Stable fingerprint of an enqueue request; identical requests collapse to one job."""
    payload = json.dumps(params or {}, sort_keys=True, separators=(",", ":"))
    raw = f"{command}|{video_id}|{topic_id}|{payload}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def enqueue(
    command: str,
    *,
    video_id: int | None = None,
    topic_id: int | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a `pending` job, or reuse an in-flight one with the same fingerprint.

    Returns a detached-safe snapshot: {id, status, command, created}. `created` is False
    when an existing pending/running job was reused (a deduped double-click).
    """
    if command not in JOB_COMMANDS:
        raise ValueError(f"unknown job command: {command!r}")

    key = _idem_key(command, video_id, topic_id, params)
    with SessionLocal() as s:
        existing = s.scalar(
            select(Job)
            .where(Job.idempotency_key == key, Job.status.in_(_ACTIVE_STATUSES))
            .order_by(Job.id)
        )
        if existing is not None:
            log.info("enqueue deduped -> existing job %s (%s)", existing.id, command)
            return {
                "id": existing.id,
                "status": existing.status,
                "command": command,
                "created": False,
            }

        job = Job(
            command=command,
            video_id=video_id,
            topic_id=topic_id,
            params=params,
            idempotency_key=key,
        )
        s.add(job)
        try:
            s.commit()
        except IntegrityError as exc:
            # FK enforcement is ON: a video_id/topic_id pointing at no row lands here. Turn the
            # raw driver error into a clean ValueError the routes render as a 400 (not a 500).
            s.rollback()
            raise ValueError(
                f"{command}: references a missing video_id={video_id} / topic_id={topic_id}"
            ) from exc
        s.refresh(job)
        log.info(
            "enqueued job %s command=%s video=%s topic=%s", job.id, command, video_id, topic_id
        )
        return {"id": job.id, "status": job.status, "command": command, "created": True}
