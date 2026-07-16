"""Shared test fixtures.

`temp_db` points the whole app at a throwaway SQLite file. Every module imported
`SessionLocal` from `db.engine` by reference, and they all share that one sessionmaker
instance — so `SessionLocal.configure(bind=...)` rebinds ALL of them at once (no per-module
monkeypatch needed). The original bind is restored on teardown.
"""

from __future__ import annotations

from pathlib import Path

import importlib

import pytest
from sqlalchemy import create_engine, event

from ai_operator.db.base import Base

# The db package re-exports the Engine object as `engine`, shadowing the submodule attribute,
# so `import ai_operator.db.engine as x` binds x to the Engine, not the module. import_module
# returns the real module from sys.modules — that's the one holding the shared SessionLocal.
db_engine = importlib.import_module("ai_operator.db.engine")


@pytest.fixture(autouse=True)
def _no_production_db():
    """Bind the shared sessionmaker to an EMPTY in-memory engine for every test.

    Without this, a test that touches the DB but forgot `temp_db` silently reads/writes the
    developer's real data/*.db — publish()'s gen-shorts auto-enqueue actually leaked real job
    rows this way (the live scheduler then ran them). The guard engine has NO schema on
    purpose: a forgotten fixture now fails loudly ("no such table") instead of leaking.
    `temp_db`/`temp_db_fk` re-configure the bind on top of this for tests that need a DB."""
    guard_engine = create_engine("sqlite://", future=True)  # empty: no tables on purpose
    db_engine.SessionLocal.configure(bind=guard_engine)
    try:
        yield guard_engine
    finally:
        db_engine.SessionLocal.configure(bind=db_engine.engine)
        guard_engine.dispose()


@pytest.fixture
def temp_db(tmp_path: Path, _no_production_db):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    db_engine.SessionLocal.configure(bind=test_engine)
    try:
        yield test_engine
    finally:
        # back to the guard (NOT the real engine) — later teardowns stay leak-proof
        db_engine.SessionLocal.configure(bind=_no_production_db)
        test_engine.dispose()


@pytest.fixture
def temp_db_fk(tmp_path: Path, _no_production_db):
    """Like `temp_db` but with SQLite FK enforcement ON (mirrors the real engine), so tests can
    exercise IntegrityError paths (e.g. enqueue against a missing video_id)."""
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'test_fk.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(test_engine, "connect")
    def _fk_on(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(test_engine)
    db_engine.SessionLocal.configure(bind=test_engine)
    try:
        yield test_engine
    finally:
        # back to the guard (NOT the real engine) — later teardowns stay leak-proof
        db_engine.SessionLocal.configure(bind=_no_production_db)
        test_engine.dispose()
