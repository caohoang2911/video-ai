"""Declarative base + shared helpers for all ORM models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


def utcnow() -> datetime:
    """Timezone-aware UTC now (store UTC, convert on display)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass
