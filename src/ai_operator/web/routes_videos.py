"""Video routes: list (optionally filtered by state) + detail (paths, assets, cost rows,
decision history, upload). Read-only here; control POSTs are added in routes_actions."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from .. import checkpoint
from ..config import OUTPUT_DIR
from ..db.engine import SessionLocal
from ..db.models import Asset, Decision, Upload, Video
from ..db.models_ops import CostLedger, Job
from ..db.state_machine import VideoState, can_transition
from .rendering import iso, render

router = APIRouter()


def _media_url(path: str | None) -> str | None:
    """`/media/...` URL for a render artifact under OUTPUT_DIR, else None (path outside the
    read-only output mount can't be previewed)."""
    if not path:
        return None
    try:
        rel = Path(path).resolve().relative_to(OUTPUT_DIR.resolve())
    except (ValueError, OSError):
        return None
    return f"/media/{rel.as_posix()}"

# Actions a reviewer can drive from the detail page, and the state each needs to be legal in.
# The template only shows a button when the current state can still transition into it.
_DECISION_TARGETS = {
    "PASS_POLICY": VideoState.POLICY_OK,
    "PASS_QUALITY": VideoState.APPROVED,
    "HOLD_RERUN": VideoState.RERUN_QUEUED,
    "REJECT_POLICY_OTHER": VideoState.REJECTED,
    "EDIT_OTHER": VideoState.EDITING,
}


def _video_row(v: Video) -> dict:
    return {
        "id": v.id, "state": v.state, "topic_id": v.topic_id,
        "kind": v.kind, "parent_id": v.parent_id,
        "title": v.title, "duration_sec": v.duration_sec,
        "needs_revoice": v.needs_revoice, "reject_reason": v.reject_reason,
        "created_at": iso(v.created_at), "updated_at": iso(v.updated_at),
    }


def _video_detail(v: Video) -> dict:
    d = _video_row(v)
    d.update({
        "description": v.description, "tags": v.tags,
        "script_path": v.script_path, "audio_path": v.audio_path,
        "video_path": v.video_path, "thumb_path": v.thumb_path,
        "video_url": _media_url(v.video_path), "thumb_url": _media_url(v.thumb_path),
    })
    return d


@router.get("/videos")
def list_videos(request: Request, state: str | None = None, kind: str | None = None):
    stmt = select(Video).order_by(Video.updated_at.desc())
    if state:
        stmt = stmt.where(Video.state == state)
    if kind:
        stmt = stmt.where(Video.kind == kind)
    with SessionLocal() as s:
        videos = [_video_row(v) for v in s.scalars(stmt).all()]
        states = [st for (st,) in s.execute(select(Video.state).distinct()).all()]
        # Group rows into families for the tree view: each main followed by its shorts.
        # `videos` stays flat (JSON API contract); `families` drives the HTML table.
        shorts_by_parent: dict[int | None, list[dict]] = {}
        for row in videos:
            if row["kind"] == "short":
                shorts_by_parent.setdefault(row["parent_id"], []).append(row)
        families = [
            {"main": row, "stub": None,
             "shorts": sorted(shorts_by_parent.pop(row["id"], []), key=lambda r: r["id"])}
            for row in videos if row["kind"] != "short"
        ]
        # Shorts whose parent fell outside the current filter (or is gone): keep them
        # visible under a muted context stub instead of silently dropping them.
        for pid, kids in shorts_by_parent.items():
            parent = s.get(Video, pid) if pid is not None else None
            stub = None if parent is None else {
                "id": parent.id, "title": parent.title, "state": parent.state,
            }
            families.append({"main": None, "stub": stub,
                             "shorts": sorted(kids, key=lambda r: r["id"])})
    return render(request, "videos.html", {
        "videos": videos, "families": families,
        "state": state, "states": sorted(states), "kind": kind,
    })


@router.get("/videos/{video_id}")
def video_detail(request: Request, video_id: int):
    with SessionLocal() as s:
        v = s.get(Video, video_id)
        if v is None:
            raise HTTPException(status_code=404, detail=f"video {video_id} not found")
        detail = _video_detail(v)
        assets = [
            {"id": a.id, "kind": a.kind, "source": a.source, "license": a.license,
             "url_or_path": a.url_or_path}
            for a in s.scalars(select(Asset).where(Asset.video_id == video_id).order_by(Asset.id)).all()
        ]
        costs = [
            {"step": c.step, "provider": c.provider, "units": c.units,
             "cost": c.actual_cost if c.actual_cost is not None else c.estimated_cost,
             "ym": c.ym}
            for c in s.scalars(
                select(CostLedger).where(CostLedger.video_id == video_id).order_by(CostLedger.id)
            ).all()
        ]
        decisions = [
            {"tier": d.tier, "code": d.decision_code, "reason": d.reason, "at": iso(d.created_at)}
            for d in s.scalars(
                select(Decision).where(Decision.video_id == video_id).order_by(Decision.id)
            ).all()
        ]
        # job gần nhất của video: chỉ ra lệnh nào vừa chạy/failed (trả lời "kẹt ở đâu")
        last_job = s.scalar(select(Job).where(Job.video_id == video_id).order_by(Job.id.desc()))
        last_job_row = None if last_job is None else {
            "command": last_job.command, "status": last_job.status, "error": last_job.error,
            "finished_at": iso(last_job.finished_at),
        }
        upload = s.scalar(select(Upload).where(Upload.video_id == video_id).order_by(Upload.id.desc()))
        upload_row = None if upload is None else {
            "youtube_video_id": upload.youtube_video_id, "status": upload.status,
            "publish_at": iso(upload.publish_at), "ab_status": upload.ab_status,
            "winning_title": upload.winning_title, "winning_thumbnail": upload.winning_thumbnail,
        }
        shorts = [
            {"id": c.id, "state": c.state, "title": c.title}
            for c in s.scalars(
                select(Video).where(Video.parent_id == video_id).order_by(Video.id)
            ).all()
        ]
    allowed = sorted(c for c, t in _DECISION_TARGETS.items() if can_transition(v.state, t))
    return render(request, "video_detail.html", {
        "video": detail, "assets": assets, "costs": costs,
        "decisions": decisions, "upload": upload_row, "allowed_decisions": allowed,
        "shorts": shorts,  # children of a main; empty for a short
        "last_step": checkpoint.last_step(video_id),  # live pipeline position while rendering
        "last_job": last_job_row,  # most recent queue command for this video (shows failures)
    })
