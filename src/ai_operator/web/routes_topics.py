"""Topic routes: browse the backlog + kick off content generation. Both POSTs enqueue jobs
(gen-topics seeds/suggests; produce turns a topic into a scripted draft) — no heavy work runs
in the web process."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from sqlalchemy import select

from ..db.engine import SessionLocal
from ..db.models import Topic
from .job_queue import enqueue
from .rendering import action_result, iso, render

router = APIRouter()


@router.get("/topics")
def list_topics(request: Request, status: str | None = None):
    stmt = select(Topic).order_by(Topic.created_at.desc())
    if status:
        stmt = stmt.where(Topic.status == status)
    with SessionLocal() as s:
        topics = [
            {"id": t.id, "title": t.title, "angle": t.angle, "status": t.status,
             "created_at": iso(t.created_at)}
            for t in s.scalars(stmt).all()
        ]
    return render(request, "topics.html", {"topics": topics, "status": status})


@router.post("/topics/gen-topics")
def gen_topics(request: Request, n: int = Form(5)):
    job = enqueue("gen-topics", params={"n": n})
    return action_result(request, job, "/jobs")


@router.post("/topics/{topic_id}/produce")
def produce_topic(request: Request, topic_id: int, motion: bool = Form(False)):
    try:
        job = enqueue("produce", topic_id=topic_id, params={"motion": motion})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return action_result(request, job, "/jobs")
