"""Control POSTs: the buttons that make this a *control* panel.

Two families, both thin adapters over existing core logic (zero duplicated business logic):
  - heavy work  -> web.job_queue.enqueue(...)         (scheduler drains it)
  - light review -> review.decision_store.record_decision(...) / metadata_edit / set_winner

A stale/illegal decision surfaces as a graceful message (409 JSON or a redirect carrying
`?msg=`), never a 500 — `assert_transition` inside record_decision is the guard.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..db import InvalidTransition, SessionLocal
from ..db.models import Video
from ..publisher import ab_variants
from ..review import decision_codes as dc
from ..review.decision_store import record_decision
from ..review.metadata_edit import apply_metadata_edit
from .job_queue import JOB_COMMANDS, enqueue
from .rendering import action_result, wants_json

router = APIRouter()

# Heavy per-video commands the detail page may enqueue (subset of JOB_COMMANDS that take a video).
_VIDEO_COMMANDS = frozenset({"gen-audio", "gen-visuals", "revoice", "assemble", "publish"})
# Commands wired to the MAIN pipeline only: they read shot_list scripts (assemble) or chain
# into it (revoice enqueues assemble). A short that needs new audio or a rebuild re-rolls via
# "Regenerate shorts" on its parent; gen-visuals is short-aware in the worker and publish
# applies to both kinds.
_MAIN_ONLY_COMMANDS = frozenset({"gen-audio", "revoice", "assemble"})


def _decided(request: Request, video_id: int, payload: dict, status_code: int = 200):
    """Redirect a browser back to the video detail (carrying a status message) / JSON for API."""
    if wants_json(request):
        return JSONResponse(payload, status_code=status_code)
    msg = payload.get("error") or payload.get("state") or "ok"
    return RedirectResponse(url=f"/videos/{video_id}?msg={quote(str(msg))}", status_code=303)


@router.post("/jobs")
def enqueue_job(
    request: Request,
    command: str = Form(...),
    video_id: int | None = Form(None),
    topic_id: int | None = Form(None),
    motion: bool = Form(False),
):
    """Generic enqueue endpoint (also backs the JSON API). Command must be allow-listed."""
    try:
        job = enqueue(command, video_id=video_id, topic_id=topic_id, params={"motion": motion})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return action_result(request, job, "/jobs")


@router.post("/videos/{video_id}/enqueue/{command}")
def enqueue_for_video(request: Request, video_id: int, command: str, motion: bool = Form(False)):
    if command not in _VIDEO_COMMANDS:
        raise HTTPException(status_code=400, detail=f"{command!r} is not a per-video command")
    with SessionLocal() as s:
        video = s.get(Video, video_id)
    # A missing video falls through: enqueue() raises ValueError -> the same 400 as before.
    if video is not None and video.kind == "short" and command in _MAIN_ONLY_COMMANDS:
        raise HTTPException(
            status_code=400,
            detail=f"{command!r} runs the main-video pipeline — for a short, re-roll the "
                   f"batch via 'Regenerate shorts' on parent #{video.parent_id}",
        )
    try:
        job = enqueue(command, video_id=video_id, params={"motion": motion})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return action_result(request, job, "/jobs")


@router.post("/videos/{video_id}/regenerate-shorts")
def regenerate_shorts(request: Request, video_id: int):
    """Re-roll a main video's Shorts batch: discards its non-published shorts and generates
    a fresh set (gen-shorts with force). Only mains have shorts — 400 for a short."""
    with SessionLocal() as s:
        video = s.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail=f"video {video_id} not found")
    if video.kind != "main":
        raise HTTPException(status_code=400, detail="only a main video can regenerate shorts")
    job = enqueue("gen-shorts", video_id=video_id, params={"force": True})
    return action_result(request, job, "/jobs")


@router.post("/analytics/refresh")
def refresh_analytics(request: Request):
    """Pull fresh YouTube analytics now — enqueues the pull-analytics job (idempotency key
    dedupes repeat clicks while one is already pending/running)."""
    job = enqueue("pull-analytics")
    return action_result(request, job, "/analytics?msg=queued")


@router.post("/videos/{video_id}/decision")
def decide(
    request: Request,
    video_id: int,
    code: str = Form(...),
    reason: str | None = Form(None),
    title: str | None = Form(None),
    description: str | None = Form(None),
    tags: str | None = Form(None),
):
    """Record a review decision via the SAME core the Telegram bot uses. For an EDIT_* code the
    metadata edit is applied in the same request (web replaces the bot's stateful edit prompt)."""
    if not dc.is_final(code):
        raise HTTPException(status_code=400, detail=f"unknown or non-terminal decision code {code!r}")
    if dc.requires_free_text(code) and not (reason and reason.strip()):
        raise HTTPException(status_code=400, detail=f"{code} requires a reason")
    try:
        new_state = record_decision(video_id, code, reason=reason)
    except InvalidTransition:
        return _decided(request, video_id, {"error": "already moved past this step"}, status_code=409)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if code.startswith(dc.EDIT_PREFIX):
        apply_metadata_edit(video_id, {"title": title, "description": description, "tags": tags})
    return _decided(request, video_id, {"state": new_state.value, "code": code})


@router.post("/videos/{video_id}/set-winner")
def set_winner(
    request: Request,
    video_id: int,
    title: str | None = Form(None),
    thumb: str | None = Form(None),
):
    try:
        ab_variants.set_winner(video_id, title=title, thumb=thumb)
    except ValueError as exc:
        return _decided(request, video_id, {"error": str(exc)}, status_code=400)
    return _decided(request, video_id, {"state": "winner_recorded"})


def _script_json(video_id: int) -> tuple[Path, dict]:
    """(path, parsed script.json) for a video, or 404. Shared by the fact-check actions."""
    with SessionLocal() as s:
        video = s.get(Video, video_id)
    if video is None or not video.script_path or not Path(video.script_path).exists():
        raise HTTPException(status_code=404, detail=f"video {video_id} has no script.json")
    path = Path(video.script_path)
    return path, json.loads(path.read_text(encoding="utf-8"))


@router.post("/videos/{video_id}/factcheck/{index}/resolve")
def factcheck_resolve(request: Request, video_id: int, index: int):
    """Human arbitration: the reviewer looked at the evidence and vouches for the claim.
    Flips the citation to fact_status=ok and stamps crosscheck.human=confirmed — the machine
    verdicts stay visible underneath so the trail shows WHO overrode WHAT."""
    path, data = _script_json(video_id)
    citations = data.get("citations", [])
    if not 0 <= index < len(citations):
        raise HTTPException(status_code=400, detail=f"citation index {index} out of range")
    citations[index]["fact_status"] = "ok"
    citations[index].setdefault("crosscheck", {})["human"] = "confirmed"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return _decided(request, video_id, {"state": f"citation {index + 1}: đã bỏ cờ (người duyệt xác nhận)"})


@router.post("/videos/{video_id}/factcheck/recheck")
def factcheck_recheck(request: Request, video_id: int):
    """Re-run the flag-only cross-check (Wikipedia + skeptic) over the video's citations —
    for transient failures (Commons 429) or after research was corrected. Runs inline
    (~15s: one wiki batch + one LLM call). Human arbitration OUTRANKS the machines: a
    citation the reviewer already vouched for (crosscheck.human=confirmed) is kept as-is
    and excluded from the re-run — only unarbitrated citations are recomputed."""
    from ..content import fact_crosscheck
    from ..content.schema import Citation

    path, data = _script_json(video_id)
    cits = [Citation(**c) for c in data.get("citations", [])]
    if not cits:
        return _decided(request, video_id, {"error": "script has no citations"}, status_code=400)
    unarbitrated = [c for c in cits if (c.crosscheck or {}).get("human") != "confirmed"]
    if not unarbitrated:
        return _decided(request, video_id,
                        {"state": "tất cả claim đã được người duyệt xác nhận — không kiểm lại gì"})
    with SessionLocal() as s:
        title = (s.get(Video, video_id).title or "")
    verified = iter(fact_crosscheck.verify(title, "", unarbitrated, video_id=video_id))
    merged = [c if (c.crosscheck or {}).get("human") == "confirmed" else next(verified) for c in cits]
    data["citations"] = [c.model_dump() for c in merged]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    kept = len(cits) - len(unarbitrated)
    note = f" ({kept} claim người duyệt giữ nguyên)" if kept else ""
    return _decided(request, video_id,
                    {"state": f"đã kiểm lại: {fact_crosscheck.summarize(merged)}{note}"})
