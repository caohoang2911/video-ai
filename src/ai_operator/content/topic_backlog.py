"""Topic backlog: hand-seeded originality anchor + LLM-suggested expansion.

Human-written seeds (seed_topics.yaml) are the originality signal a policy-sensitive
faceless channel needs; LLM-suggested topics extend the backlog but must still pass
semantic dedup before being trusted, same as any other topic source.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import select

from ..dedup.topic_dedup import is_duplicate, record
from ..db.engine import SessionLocal
from ..db.models import Topic
from ..logging_setup import get_logger
from . import topic_categories, topic_demand
from .llm_client import complete, parse_json

log = get_logger("content.topic_backlog")

# Co-located with code (NOT data/) because data/ is gitignored and this file is the
# hand-written originality seed — it must ship with the repo, not be regenerated.
SEED_PATH = Path(__file__).parent / "seed_topics.yaml"


def _suggest_system_prompt(category: str) -> str:
    """LLM system prompt for topic suggestion, scoped to the chosen sub-niche (`domain`)."""
    dom = topic_categories.domain(category)
    return (
        f"You are a history researcher sourcing topics for a faceless YouTube documentary "
        f"channel about forgotten {dom}. Suggest NEW, real, lesser-known events in that domain, "
        "distinct from the examples given — never repeat an example or a well-worn one "
        "(e.g. Titanic). Each topic needs a unique angle: the specific human, investigative, or "
        "political thread that makes it worth telling. Respond with ONLY minified JSON: "
        '{"topics":[{"title":str,"angle":str,"angle_vi":str (a natural Vietnamese translation of '
        'angle),"source_hint":str}, ...]}'
    )


def translate_to_vi(text: str | None) -> str | None:
    """Best-effort natural-Vietnamese gloss of an English angle (for the bilingual topics table).
    Returns None on empty input or any LLM failure — never blocks the caller."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        raw = complete(
            "Translate the user's text into natural, concise Vietnamese. Output ONLY the "
            "translation — no quotes, no notes, no original text.",
            text, max_tokens=400, step="translate_angle",
        )
        return raw.strip() or None
    except Exception as exc:  # noqa: BLE001 - translation is a nicety; never break the caller
        log.warning("translate_to_vi failed: %s", exc)
        return None


def load_seeds() -> list[dict]:
    """Read the hand-written seed list (title/angle/source_hint)."""
    if not SEED_PATH.exists():
        return []
    data = yaml.safe_load(SEED_PATH.read_text(encoding="utf-8")) or {}
    topics = data.get("topics", []) if isinstance(data, dict) else data
    return topics or []


def seed_backlog() -> int:
    """Insert any seed topics not already present in `topics`. Returns count added."""
    seeds = load_seeds()
    added = 0
    with SessionLocal() as s:
        existing_titles = {t.title for t in s.scalars(select(Topic)).all()}
        for seed in seeds:
            title = seed["title"]
            if title in existing_titles:
                continue
            s.add(Topic(
                slug=_slugify(title), title=title, angle=seed.get("angle"),
                source_notes=seed.get("source_hint"), status="backlog",
                category=topic_categories.valid(seed.get("category")),
            ))
            added += 1
        s.commit()
    return added


def suggest_topics(n: int, category: str = "maritime", video_id: int | None = None) -> list[Topic]:
    """Ask Claude for `n` new disaster angles in `category`; dedup, demand-score, persist."""
    category = topic_categories.valid(category)
    seeds = load_seeds()
    # bias the "don't repeat" examples toward the chosen sub-niche so the LLM stays on-domain
    same = [s for s in seeds if topic_categories.valid(s.get("category")) == category]
    seed_lines = "\n".join(f"- {s['title']}: {s.get('angle', '')}" for s in (same or seeds)[:15])
    user = f"Existing topics (do not repeat):\n{seed_lines}\n\nSuggest {n} new topics."

    raw = complete(_suggest_system_prompt(category), user, max_tokens=1500,
                   step="suggest_topics", video_id=video_id)
    data = parse_json(raw)

    # Phase 1 — all network I/O (dedup reads + YT demand lookups) OUTSIDE any write transaction,
    # so the slow calls never hold SQLite's single write lock (which would starve web/scheduler).
    accepted: list[tuple[dict, int | None, str | None]] = []
    for item in data.get("topics", []):
        title = (item.get("title") or "").strip()
        if not title or is_duplicate(title):
            continue
        # entity (pre-colon) is the clean query for the demand lookup; best-effort (None ok)
        demand, meta = topic_demand.score_json(title.split(":")[0].strip())
        accepted.append((item, demand, meta))
        if len(accepted) >= n:
            break

    # Phase 2 — one short write transaction: insert topics + record their dedup embeddings in the
    # SAME session (record(session=s) avoids the nested-write self-deadlock).
    created: list[Topic] = []
    with SessionLocal() as s:
        for item, demand, meta in accepted:
            title = item["title"].strip()
            topic = Topic(
                slug=_slugify(title), title=title, angle=item.get("angle"),
                angle_vi=item.get("angle_vi"), source_notes=item.get("source_hint"),
                status="backlog", category=category, demand_score=demand, demand_meta=meta,
            )
            s.add(topic)
            record(title, session=s)
            created.append(topic)
        s.commit()
    log.info("suggest_topics[%s]: created %d/%d requested (rest were duplicates)", category, len(created), n)
    return created


def backfill_topic_signals(limit: int | None = None) -> int:
    """Auto-fill missing demand_score / angle_vi on backlog topics (idempotent — already-filled
    ones are skipped). YouTube + translate lookups run OUTSIDE any write transaction; each topic
    is committed in its own short transaction. Returns the number of topics updated."""
    with SessionLocal() as s:
        targets = [
            (t.id, t.title, t.angle, t.demand_score is None, t.angle_vi is None and bool(t.angle))
            for t in s.scalars(select(Topic).where(Topic.status == "backlog")).all()
            if t.demand_score is None or (t.angle_vi is None and t.angle)
        ]
    if limit is not None:
        targets = targets[:limit]

    updated = 0
    for tid, title, angle, need_demand, need_vi in targets:
        demand = meta = vi = None
        if need_demand:
            demand, meta = topic_demand.score_json(title.split(":")[0].strip())
        if need_vi:
            vi = translate_to_vi(angle)
        with SessionLocal() as s:
            t = s.get(Topic, tid)
            if t is None:
                continue
            if need_demand:
                t.demand_score, t.demand_meta = demand, meta
            if need_vi and vi:
                t.angle_vi = vi
            s.commit()
        updated += 1
    if updated:
        log.info("backfill_topic_signals: filled demand/angle_vi on %d topic(s)", updated)
    return updated


def pick_next() -> Topic | None:
    """Oldest un-used backlog topic (FIFO — surfaces hand-written seeds first)."""
    with SessionLocal() as s:
        return s.scalar(
            select(Topic).where(Topic.status == "backlog").order_by(Topic.created_at.asc()).limit(1)
        )


def mark_used(topic_id: int) -> None:
    with SessionLocal() as s:
        topic = s.get(Topic, topic_id)
        if topic is not None:
            topic.status = "used"
            s.commit()


def _slugify(title: str) -> str:
    return "-".join(title.lower().split())[:200]
