"""Video routes: list (optionally filtered by state) + detail (paths, assets, cost rows,
decision history, upload). Read-only here; control POSTs are added in routes_actions."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from ..config import OUTPUT_DIR
from ..db.engine import SessionLocal
from ..db.models import Asset, Decision, Upload, Video
from ..db.models_ops import CostLedger
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
def list_videos(request: Request, state: str | None = None):
    stmt = select(Video).order_by(Video.updated_at.desc())
    if state:
        stmt = stmt.where(Video.state == state)
    with SessionLocal() as s:
        videos = [_video_row(v) for v in s.scalars(stmt).all()]
        states = [st for (st,) in s.execute(select(Video.state).distinct()).all()]
    return render(request, "videos.html", {"videos": videos, "state": state, "states": sorted(states)})


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
        upload = s.scalar(select(Upload).where(Upload.video_id == video_id).order_by(Upload.id.desc()))
        upload_row = None if upload is None else {
            "youtube_video_id": upload.youtube_video_id, "status": upload.status,
            "publish_at": iso(upload.publish_at), "ab_status": upload.ab_status,
            "winning_title": upload.winning_title, "winning_thumbnail": upload.winning_thumbnail,
        }
    allowed = sorted(c for c, t in _DECISION_TARGETS.items() if can_transition(v.state, t))
    return render(request, "video_detail.html", {
        "video": detail, "assets": assets, "costs": costs,
        "decisions": decisions, "upload": upload_row, "allowed_decisions": allowed,
    })
