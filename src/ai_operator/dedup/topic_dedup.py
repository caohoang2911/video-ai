"""Reject near-duplicate topics so the channel is never flagged for repetitive content.

Embeds each topic with all-MiniLM-L6-v2 (CPU, lazy import so `init-db` needs no torch),
stores normalized float32 vectors in topic_history, and compares by cosine (== dot on
normalized vectors). A topic scoring >= threshold vs any past topic is a duplicate.
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import select

from ..constants import DEDUP_COSINE_THRESHOLD, DEDUP_EMBED_MODEL
from ..db.engine import SessionLocal
from ..db.models_ops import TopicHistory

_model = None


def _get_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer  # heavy: lazy-loaded
        except ImportError as exc:  # a drifted venv -> fail with the one-line fix, not a cryptic import
            raise RuntimeError(
                "Topic dedup needs 'sentence-transformers' (a declared base dependency) but it "
                "is not installed — the venv is out of sync. Run `pip install -e .` in the venv."
            ) from exc
        _model = SentenceTransformer(DEDUP_EMBED_MODEL)
    return _model


def _embed(text: str) -> np.ndarray:
    vec = _get_model().encode([text], normalize_embeddings=True)[0]
    return np.asarray(vec, dtype=np.float32)


def _load_history() -> list[np.ndarray]:
    with SessionLocal() as s:
        rows = s.scalars(select(TopicHistory)).all()
    return [np.frombuffer(r.embedding, dtype=np.float32) for r in rows]


def max_similarity(topic_name: str) -> float:
    history = _load_history()
    if not history:
        return 0.0
    q = _embed(topic_name)
    return max(float(np.dot(q, h)) for h in history)


def is_duplicate(topic_name: str, threshold: float = DEDUP_COSINE_THRESHOLD) -> bool:
    return max_similarity(topic_name) >= threshold


def record(topic_name: str, session=None) -> None:
    """Persist a topic's embedding after it has been accepted for production. Pass `session` to
    write within an existing transaction — nesting a second write session inside an open one
    self-deadlocks SQLite's single writer (busy_timeout then SQLITE_BUSY)."""
    row = TopicHistory(topic_name=topic_name, embedding=_embed(topic_name).tobytes())
    if session is not None:
        session.add(row)  # caller owns the commit
        return
    with SessionLocal() as s:
        s.add(row)
        s.commit()
