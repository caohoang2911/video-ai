"""Topic routes: browse the backlog + kick off content generation. Both POSTs enqueue jobs
(gen-topics seeds/suggests; produce turns a topic into a scripted draft) — no heavy work runs
in the web process."""

from __future__ import annotations

import json

from fastapi import APIRouter, Form, HTTPException, Request
from sqlalchemy import select

from ..content import topic_categories
from ..db.engine import SessionLocal
from ..db.models import Topic, Video
from ..media import stock_clients
from .job_queue import enqueue
from .rendering import action_result, iso, render

router = APIRouter()


def _demand_tooltip(meta_json: str | None) -> str:
    """Human-readable evidence behind a demand score: top competing videos + view counts."""
    if not meta_json:
        return ""
    try:
        meta = json.loads(meta_json)
    except (ValueError, TypeError):
        return ""
    return " | ".join(f"{v['views']:,} — {v['title'][:50]}" for v in meta.get("top", []))


@router.get("/topics")
def list_topics(request: Request, status: str | None = None):
    stmt = select(Topic).order_by(Topic.created_at.desc())
    if status:
        stmt = stmt.where(Topic.status == status)
    with SessionLocal() as s:
        rows = s.scalars(stmt).all()
        # Production status per topic: the main video(s) built from it and their pipeline
        # state, so the list shows "produced → where" instead of a bare used/backlog pill.
        topic_ids = [t.id for t in rows]
        videos_by_topic: dict[int, list[dict]] = {}
        if topic_ids:
            for v in s.scalars(
                select(Video)
                .where(Video.topic_id.in_(topic_ids), Video.kind == "main",
                       Video.state != "rejected")  # scrapped attempts don't count as produced
                .order_by(Video.id)
            ).all():
                videos_by_topic.setdefault(v.topic_id, []).append(
                    {"id": v.id, "state": v.state}
                )
        topics = [
            {"id": t.id, "title": t.title, "angle": t.angle, "status": t.status,
             "category": topic_categories.label(t.category),
             "demand_score": t.demand_score, "demand_tooltip": _demand_tooltip(t.demand_meta),
             "videos": videos_by_topic.get(t.id, []), "created_at": iso(t.created_at)}
            for t in rows
        ]
    return render(request, "topics.html",
                  {"topics": topics, "status": status, "categories": topic_categories.CATEGORIES})


@router.get("/topics/{topic_id}/commons-coverage")
def commons_coverage(request: Request, topic_id: int):
    """Số ảnh tư liệu Wikimedia Commons đạt chuẩn (license + độ phân giải) cho một chủ đề.
    Gọi async từng ô qua htmx — Commons rate-limit 1 req/s nên không chặn cả trang; kết quả
    nằm trong HTTP cache 24h của stock_clients nên các lần xem sau trả về tức thì."""
    with SessionLocal() as s:
        topic = s.get(Topic, topic_id)
        if topic is None:
            raise HTTPException(status_code=404, detail=f"topic {topic_id} not found")
        # phần trước dấu ':' là tên thực thể (tàu/sự kiện) — query sạch hơn cả tiêu đề dài
        query = topic.title.split(":")[0].strip()
    hits = stock_clients.search_wikimedia_commons(query)
    return render(request, "topic_commons_coverage.html", {
        "topic_id": topic_id, "query": query, "count": len(hits),
    })


@router.post("/topics/gen-topics")
def gen_topics(request: Request, n: int = Form(5), category: str = Form("maritime")):
    job = enqueue("gen-topics", params={"n": n, "category": topic_categories.valid(category)})
    return action_result(request, job, "/jobs")


@router.post("/topics/{topic_id}/produce")
def produce_topic(request: Request, topic_id: int, motion: bool = Form(False)):
    try:
        job = enqueue("produce", topic_id=topic_id, params={"motion": motion})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return action_result(request, job, "/jobs")
