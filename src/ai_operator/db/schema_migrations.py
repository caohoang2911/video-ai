"""Idempotent SQLite column migrations.

`Base.metadata.create_all` only creates missing TABLES — it never alters an existing one.
Columns added to a model after a deploy therefore need an explicit `ALTER TABLE ADD COLUMN`,
guarded by `PRAGMA table_info` so re-runs (and fresh DBs where create_all already made the
column) are no-ops. Applied from `init_db()`.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..logging_setup import get_logger

log = get_logger("db.schema_migrations")

# (table, column, SQL type/default as it should appear in ADD COLUMN)
_PENDING: tuple[tuple[str, str, str], ...] = (
    ("videos", "kind", "VARCHAR(8) DEFAULT 'main'"),
    ("videos", "parent_id", "INTEGER REFERENCES videos(id)"),
)


def _existing_columns(engine: Engine, table: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).all()
    return {r[1] for r in rows}  # row[1] = column name


def apply_pending(engine: Engine) -> list[str]:
    """Add any missing columns; returns the list of columns added (empty on a no-op run)."""
    added: list[str] = []
    for table, column, ddl in _PENDING:
        cols = _existing_columns(engine, table)
        if not cols:
            continue  # table not created yet -> create_all will make it with all columns
        if column in cols:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        added.append(f"{table}.{column}")
        log.info("schema migration: added %s.%s", table, column)
    return added
