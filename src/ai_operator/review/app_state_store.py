"""Durable ephemeral UI state (pending free-text prompts, checklist ticks).

Uses the existing `AppState` KV table instead of an in-process dict — a bot restart
mid-conversation (waiting on a reason or metadata reply) must not strand the reviewer's
next message with nothing listening for it; DB-backed state survives the restart.
"""

from __future__ import annotations

import json

from ..db.engine import SessionLocal
from ..db.models_ops import AppState


def get_json(key: str) -> dict | None:
    with SessionLocal() as s:
        row = s.get(AppState, key)
        if row is None or not row.value:
            return None
        return json.loads(row.value)


def set_json(key: str, value: dict) -> None:
    with SessionLocal() as s:
        row = s.get(AppState, key)
        payload = json.dumps(value)
        if row is None:
            s.add(AppState(key=key, value=payload))
        else:
            row.value = payload
        s.commit()


def clear(key: str) -> None:
    with SessionLocal() as s:
        row = s.get(AppState, key)
        if row is not None:
            s.delete(row)
            s.commit()
