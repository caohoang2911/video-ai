---
phase: 1
title: "Foundation & Job Model"
status: pending
priority: P1
effort: "3h"
dependencies: []
---

# Phase 1: Foundation & Job Model

## Overview
Add deps + the `jobs` queue table + a thin enqueue helper + config knobs. This is the data spine everything else builds on.

## Requirements
- Functional: a `Job` row can be created (enqueued) with an idempotency key; duplicate enqueue of the same in-flight command is deduped.
- Non-functional: no new business logic; `init_db()` creates the table; file <200 lines.

## Architecture
`Job` = single-table DB queue (producer = web, consumer = scheduler). Statuses `pending → running → done|failed`. Idempotency key = deterministic string (`{command}:{video_id|topic_id}:{param-hash}`) with a **partial-unique guarantee enforced in code** (SQLite lacks easy partial unique index across ORM) — enqueue checks for an existing `pending`/`running` job with same key before insert.

## Related Code Files
- Modify: `src/ai_operator/db/models_ops.py` — add `Job(Base)`.
- Create: `src/ai_operator/web/__init__.py`, `src/ai_operator/web/job_queue.py` — `enqueue(command, *, video_id=None, topic_id=None, params=None) -> Job | Job(existing)` + `JOB_COMMANDS` allowlist (the only commands web may enqueue).
- Modify: `src/ai_operator/config.py` — add `WEB_HOST="127.0.0.1"`, `WEB_PORT=8000` (pydantic-settings, env-overridable).
- Modify: `pyproject.toml` — deps `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`.

## Implementation Steps
1. `Job` model in `models_ops.py`:
   `id`, `command: str(40)`, `video_id: FK videos.id | None`, `topic_id: FK topics.id | None`, `params: JSON | None`, `status: str(12) default "pending" index`, `idempotency_key: str(120) index`, `error: Text | None`, `created_at`, `started_at: DateTime|None`, `finished_at: DateTime|None`. Use existing `utcnow` default + `Base` import pattern already in file.
2. `web/job_queue.py`:
   - `JOB_COMMANDS: frozenset[str]` = {`produce`,`gen-script`,`gen-audio`,`gen-visuals`,`revoice`,`assemble`,`publish`,`pull-analytics`}. Reject unknown command → `ValueError`.
   - `_idem_key(command, video_id, topic_id, params)` → stable string (sorted params json).
   - `enqueue(...)`: in one `SessionLocal()` tx, `SELECT` existing Job with same `idempotency_key` AND status in (`pending`,`running`); if found return it (dedupe double-click), else insert `pending` and return. Return a lightweight dict/row-safe snapshot (id, status) to avoid detached-instance issues.
3. `config.py`: add the two settings fields (mirror existing field style).
4. `pyproject.toml`: append the 4 deps to `dependencies`.
5. Run `PYTHONPATH=src .venv/bin/python -m ai_operator.cli init-db` → confirm `jobs` table created (re-run is idempotent via `create_all`).

## Success Criteria
- [ ] `pip install -e .` resolves new deps on Python 3.11.
- [ ] `init-db` creates `jobs` table; re-run is a no-op.
- [ ] `enqueue("gen-audio", video_id=1)` inserts one `pending` row; calling again while it's still pending returns the SAME row (no duplicate).
- [ ] `enqueue("bogus")` raises `ValueError`.
- [ ] `models_ops.py` and `job_queue.py` each <200 lines; no import cycle (`web` may import `db`, not vice-versa).

## Risk Assessment
- **Idempotency race** (two near-simultaneous enqueues): acceptable for solo local use; `busy_timeout=5000` + short tx makes the check-then-insert window tiny. If it ever double-inserts, the worker's own claim (Phase 2) still runs each once and the second is a cheap re-run guarded by pipeline checkpoints. Documented, not over-engineered.
- **Dep weight:** `uvicorn[standard]` pulls a few extras — still lightweight, no GPU/native build. Acceptable per free-stack.
