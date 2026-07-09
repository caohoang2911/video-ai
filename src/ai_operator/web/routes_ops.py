"""Ops routes: cost ledger (grouped by month+provider), analytics snapshots, and the job
queue. All read-only views over the shared DB."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from ..db.engine import SessionLocal
from ..db.models_ops import Analytics, CostLedger, Job
from .rendering import iso, render

router = APIRouter()

_JOBS_LIMIT = 100
_ANALYTICS_LIMIT = 200


@router.get("/costs")
def costs(request: Request):
    spent = func.coalesce(
        func.sum(func.coalesce(CostLedger.actual_cost, CostLedger.estimated_cost)), 0.0
    )
    with SessionLocal() as s:
        rows = s.execute(
            select(CostLedger.ym, CostLedger.provider, func.count(), spent)
            .group_by(CostLedger.ym, CostLedger.provider)
            .order_by(CostLedger.ym.desc(), CostLedger.provider)
        ).all()
    groups = [
        {"ym": ym, "provider": provider, "calls": int(n), "cost": round(float(total), 2)}
        for ym, provider, n, total in rows
    ]
    return render(request, "costs.html", {"costs": groups})


@router.get("/analytics")
def analytics(request: Request):
    """Newest analytics snapshot per video (many daily rows collapse to one per video)."""
    with SessionLocal() as s:
        rows = s.scalars(
            select(Analytics).order_by(Analytics.youtube_video_id, Analytics.as_of_date.desc())
        ).all()
    latest: dict[str, dict] = {}
    for a in rows:
        latest.setdefault(a.youtube_video_id, {
            "youtube_video_id": a.youtube_video_id, "as_of_date": iso(a.as_of_date),
            "views": a.views, "avg_view_pct": a.avg_view_pct, "ctr": a.ctr,
            "rpm": a.rpm, "est_revenue": a.est_revenue,
        })
    return render(request, "analytics.html", {"analytics": list(latest.values())[:_ANALYTICS_LIMIT]})


@router.get("/jobs")
def jobs(request: Request):
    with SessionLocal() as s:
        rows = s.scalars(select(Job).order_by(Job.id.desc()).limit(_JOBS_LIMIT)).all()
        jobs_out = [
            {"id": j.id, "command": j.command, "status": j.status,
             "video_id": j.video_id, "topic_id": j.topic_id, "error": j.error,
             "created_at": iso(j.created_at), "started_at": iso(j.started_at),
             "finished_at": iso(j.finished_at)}
            for j in rows
        ]
    return render(request, "jobs.html", {"jobs": jobs_out})
