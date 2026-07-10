"""schema_migrations: guarded ADD COLUMN works on a legacy table and no-ops on re-run/fresh."""

from sqlalchemy import create_engine, text

from ai_operator.db import schema_migrations


def _legacy_engine(tmp_path):
    """A videos table WITHOUT kind/parent_id — the pre-shorts deployed shape."""
    eng = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}", future=True)
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE videos (id INTEGER PRIMARY KEY, state VARCHAR(24))"))
        conn.execute(text("INSERT INTO videos (state) VALUES ('published')"))
    return eng


def test_adds_missing_columns_and_defaults_existing_rows(tmp_path):
    eng = _legacy_engine(tmp_path)
    added = schema_migrations.apply_pending(eng)
    assert added == ["videos.kind", "videos.parent_id"]
    with eng.connect() as conn:
        row = conn.execute(text("SELECT kind, parent_id FROM videos")).one()
    assert row == ("main", None)  # existing row backfilled by the column DEFAULT


def test_rerun_is_noop(tmp_path):
    eng = _legacy_engine(tmp_path)
    schema_migrations.apply_pending(eng)
    assert schema_migrations.apply_pending(eng) == []


def test_missing_table_is_skipped(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}", future=True)
    assert schema_migrations.apply_pending(eng) == []  # create_all owns fresh DBs
