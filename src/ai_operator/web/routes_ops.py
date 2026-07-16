"""Ops routes: cost ledger (grouped by month+provider), analytics snapshots, and the job
queue (read views + scheduler process start/stop)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from sqlalchemy import select, update

from .. import checkpoint
from ..db.engine import SessionLocal
from ..db.models import Video
from ..db.models_ops import Job
from . import analytics_view, costs_view, scheduler_control
from .charts import bar_chart, views_sparkline
from .rendering import action_result, iso, render

router = APIRouter()

_JOBS_LIMIT = 100


def _fmt_elapsed(started, now: datetime) -> str | None:
    """Human elapsed since a running job's start (started_at may come back tz-naive from SQLite)."""
    if started is None:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    secs = int((now - started).total_seconds())
    if secs < 0:
        secs = 0
    return f"{secs // 60}m {secs % 60}s" if secs >= 60 else f"{secs}s"


@router.get("/costs")
def costs(request: Request):
    """Cost ledger: month summary vs budget cap + breakdowns (see web.costs_view)."""
    data = costs_view.overview()
    # Pre-render the per-day spend as inline SVG — same no-JS approach as /analytics.
    data["daily_svg"] = bar_chart(data["daily"])
    return render(request, "costs.html", data)


@router.get("/analytics")
def analytics(request: Request):
    """Real YouTube analytics: channel totals + trend + top/worst + per-video table + freshness.
    All derived from the pulled `analytics` rows (see web.analytics_view)."""
    data = analytics_view.overview()
    # Pre-render the trend as inline SVG so the template stays logic-free (no JS chart lib).
    data["views_svg"] = views_sparkline(data["trend"]["views"])
    return render(request, "analytics.html", data)


@router.get("/jobs")
def jobs(request: Request):
    now = datetime.now(timezone.utc)
    with SessionLocal() as s:
        rows = s.scalars(select(Job).order_by(Job.id.desc()).limit(_JOBS_LIMIT)).all()
        jobs_out = []
        for j in rows:
            elapsed = _fmt_elapsed(j.started_at, now) if j.status == "running" else None
            # for a running job, surface the video's live pipeline position (state + last done step)
            step = state = None
            if j.status == "running" and j.video_id is not None:
                v = s.get(Video, j.video_id)
                state = v.state if v else None
                step = checkpoint.last_step(j.video_id)
            jobs_out.append({
                "id": j.id, "command": j.command, "status": j.status,
                "video_id": j.video_id, "topic_id": j.topic_id, "error": j.error,
                "created_at": iso(j.created_at), "started_at": iso(j.started_at),
                "finished_at": iso(j.finished_at), "elapsed": elapsed,
                "video_state": state, "last_step": step,
            })
    running = [j for j in jobs_out if j["status"] == "running"]
    return render(request, "jobs.html", {
        "jobs": jobs_out, "running": running,
        "scheduler_running": scheduler_control.is_running(),
    })


@router.post("/jobs/{job_id}/cancel")
def job_cancel(request: Request, job_id: int):
    """Huỷ một job còn PENDING. Guarded UPDATE (id + status) nên không có race với worker:
    job đã bị claim (running) thì rowcount = 0 và không bị đụng vào."""
    with SessionLocal() as s:
        res = s.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "pending")
            .values(status="cancelled", error="cancelled by operator",
                    finished_at=datetime.now(timezone.utc))
        )
        s.commit()
        cancelled = res.rowcount == 1
    return action_result(request, {
        "ok": cancelled, "id": job_id,
        "note": None if cancelled else "job không còn pending (đã chạy/xong) — không huỷ được",
    }, "/jobs")


@router.post("/jobs/scheduler/start")
def scheduler_start(request: Request):
    return action_result(request, scheduler_control.start(), "/jobs")


@router.post("/jobs/scheduler/stop")
def scheduler_stop(request: Request):
    return action_result(request, scheduler_control.stop(), "/jobs")
