"""Engine + session factory. SQLite runs in WAL mode (app + scheduler share the db)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ..config import PROJECT_ROOT, ensure_dirs, settings
from .base import Base

# Import model modules so their tables register on Base.metadata before create_all.
from . import models, models_ops  # noqa: F401,E402

_SQLITE_PREFIX = "sqlite:///"


def _resolve_url(url: str) -> str:
    """Anchor a relative sqlite path to the project root so CWD can't split the db."""
    if url.startswith(_SQLITE_PREFIX):
        raw = url[len(_SQLITE_PREFIX):]
        p = Path(raw)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return f"{_SQLITE_PREFIX}{p}"
    return url


def _make_engine():
    url = _resolve_url(settings.DB_URL)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    eng = create_engine(url, echo=False, future=True, connect_args=connect_args)

    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            # Background scheduler jobs run on overlapping threads; WAL allows one writer, so a
            # second concurrent writer must WAIT (up to 5s) rather than fail fast on SQLITE_BUSY.
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    return eng


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create runtime dirs + all tables (idempotent)."""
    ensure_dirs()
    Base.metadata.create_all(engine)
