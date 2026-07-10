---
phase: 1
title: "Data Model kind parent"
status: completed
priority: P1
effort: "3h"
dependencies: []
---

# Phase 1: Data Model (kind, parent_id)

## Overview
Make a short a first-class *child* of a main video by adding two columns to `Video`, so every
existing subsystem (state machine, review gate, publish, web panel, job queue) treats shorts for
free. Includes the SQLite column migration (create_all does NOT alter existing tables).

## Requirements
- Functional: a `Video` row can be `kind="short"` with a `parent_id` pointing at its main video;
  existing rows default to `kind="main"`, `parent_id=NULL`.
- Non-functional: additive + backward-compatible; the live `data/operator.db` (has real rows)
  must migrate in place without data loss; no new state-machine states.

## Architecture
- `Video` gains `kind: str(8) = "main"` (index) + `parent_id: int | None` (FK videos.id).
- `create_all` only creates missing *tables*, not columns → add an **idempotent SQLite migration**:
  `ALTER TABLE videos ADD COLUMN ...`, guarded by `PRAGMA table_info(videos)` so re-runs are no-ops.
  Wire it into `init_db()` (runs after `create_all`) so `operator init-db` applies it.
- No `VideoState` changes: a short walks the SAME lifecycle (draft→...→pending_review→published→
  analyzed). `kind` is the only discriminator; review/publish/analytics key off `video_id` already.

## Related Code Files
- Modify: `src/ai_operator/db/models.py` — add `kind`, `parent_id` to `Video`.
- Create: `src/ai_operator/db/schema_migrations.py` — `apply_pending(engine)` running guarded ADD COLUMNs.
- Modify: `src/ai_operator/db/engine.py` — `init_db()` calls `schema_migrations.apply_pending(engine)` after `create_all`.

## Implementation Steps
1. Add columns to `Video` model (mirror existing `mapped_column` style; `kind` indexed).
2. `schema_migrations.apply_pending(engine)`: for `("videos","kind","VARCHAR(8) DEFAULT 'main'")`
   and `("videos","parent_id","INTEGER")`, check `PRAGMA table_info`; `ALTER TABLE ADD COLUMN` if absent.
   Idempotent; safe on a fresh DB (columns already there via create_all) and an old DB (adds them).
3. Call it in `init_db()`. Verify: `operator init-db` on the real DB adds the columns, existing 5 videos keep `kind='main'`.
4. Backfill: existing rows get `kind='main'` via the column DEFAULT; no data migration needed.

## Success Criteria
- [ ] `operator init-db` adds `kind`/`parent_id` to the existing `videos` table with no data loss; re-run is a no-op.
- [ ] New `Video(kind="short", parent_id=<main id>)` persists and loads; old rows read back `kind="main"`.
- [ ] A short row transitions through the existing state machine unchanged (no new states).
- [ ] `schema_migrations.py` < 80 lines; guarded/idempotent.

## Risk Assessment
- **create_all won't add columns** — the guarded ALTER TABLE is mandatory; a fresh-DB path must also
  work (columns already present → PRAGMA guard skips). Covered by a test on both a fresh and a
  pre-existing table.
- **FK self-reference** on SQLite: `parent_id` FK to `videos.id` is fine; enforcement only when
  `PRAGMA foreign_keys=ON` (already set) — a bad parent_id enqueue is caught upstream (Phase 4).
