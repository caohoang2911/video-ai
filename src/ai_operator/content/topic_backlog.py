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
from .llm_client import complete, parse_json

log = get_logger("content.topic_backlog")

# Co-located with code (NOT data/) because data/ is gitignored and this file is the
# hand-written originality seed — it must ship with the repo, not be regenerated.
SEED_PATH = Path(__file__).parent / "seed_topics.yaml"

_SUGGEST_SYSTEM_PROMPT = (
    "You are a maritime-history researcher sourcing topics for a faceless YouTube "
    "documentary channel about forgotten maritime disasters. Suggest NEW, real, "
    "lesser-known maritime disasters distinct from the examples given — never repeat "
    "an example or a well-worn one (e.g. Titanic). Each topic needs a unique angle: "
    "the specific human, investigative, or political thread that makes it worth "
    'telling. Respond with ONLY minified JSON: {"topics":[{"title":str,"angle":str,'
    '"source_hint":str}, ...]}'
)


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
            ))
            added += 1
        s.commit()
    return added


def suggest_topics(n: int, video_id: int | None = None) -> list[Topic]:
    """Ask Claude for `n` new maritime-disaster angles; dedup + persist as backlog."""
    seeds = load_seeds()
    seed_lines = "\n".join(f"- {s['title']}: {s.get('angle', '')}" for s in seeds[:15])
    user = f"Existing topics (do not repeat):\n{seed_lines}\n\nSuggest {n} new topics."

    raw = complete(_SUGGEST_SYSTEM_PROMPT, user, max_tokens=1500, step="suggest_topics", video_id=video_id)
    data = parse_json(raw)

    created: list[Topic] = []
    with SessionLocal() as s:
        for item in data.get("topics", []):
            title = (item.get("title") or "").strip()
            if not title or is_duplicate(title):
                continue
            topic = Topic(
                slug=_slugify(title), title=title, angle=item.get("angle"),
                source_notes=item.get("source_hint"), status="backlog",
            )
            s.add(topic)
            s.flush()  # need topic.id before recording embedding history
            record(title)
            created.append(topic)
            if len(created) >= n:
                break
        s.commit()
    log.info("suggest_topics: created %d/%d requested (rest were duplicates)", len(created), n)
    return created


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
