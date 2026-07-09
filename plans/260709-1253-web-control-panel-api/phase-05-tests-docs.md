---
phase: 5
title: "Tests & Docs"
status: pending
priority: P2
effort: "4h"
dependencies: [4]
---

# Phase 5: Tests & Docs

## Overview
Lock behavior with pytest (queue, worker, API, decision-consistency) and document the 3-process run model.

## Requirements
- Functional: automated tests cover enqueue idempotency, sequential single-execution, API rendering, and web↔Telegram decision parity.
- Non-functional: tests use a temp SQLite DB (no network, no real providers); docs updated.

## Architecture
`fastapi.testclient.TestClient` for HTTP; direct fn calls for queue/worker; dispatch mocked at the boundary (patch the pipeline callables) so tests never hit ElevenLabs/YouTube/SDXL.

## Related Code Files
- Create:
  - `tests/test_job_queue.py` — enqueue dedupe, `JOB_COMMANDS` allowlist, idem key stability.
  - `tests/test_job_worker.py` — claim atomicity (sequential, exactly-once), failed-job records error, dispatch map ↔ allowlist parity.
  - `tests/test_web_read_views.py` — TestClient GETs render + JSON variants.
  - `tests/test_web_control_actions.py` — POST decision reuses `record_decision` (parity), InvalidTransition path, enqueue POST creates pending job.
- Modify:
  - `docs/deployment-guide.md` — add 3-process run (`run-web` + `run-scheduler` + `run-bot`), bind/no-auth note, ports.
  - `README.md` — add `operator run-web` to the CLI list.
  - `docs/system-architecture.md` (if present) — note web/api layer + job queue.

## Implementation Steps
1. Test fixture: temp DB via `init_db()` against a tmp path (reuse existing test DB fixture pattern if one exists in `tests/`).
2. `test_job_queue`: enqueue same command twice while pending → one row; unknown command → `ValueError`; idem key deterministic for same args.
3. `test_job_worker`: seed 2 pending jobs, patch `DISPATCH` targets with spies, run `drain_jobs()` → both run once, in id order; make one spy raise → job `failed` + error text, worker returns normally; assert every `JOB_COMMANDS` has a `DISPATCH` key.
4. `test_web_read_views`: `TestClient(create_app())` GET each page → 200 + expected content; `/api/*` → JSON.
5. `test_web_control_actions`: POST `/videos/{id}/decision` with `PASS_POLICY` → asserts `record_decision` effect (state + decisions row) equals calling it directly; POST with a stale code → handled (no 500); POST enqueue shortcut → `pending` Job exists.
6. Run full suite: `PYTHONPATH=src .venv/bin/pytest -q`. Fix failures — do not skip.
7. Docs: update the three files; keep concise.

## Success Criteria
- [ ] All new tests pass; existing suite still green (`pytest -q`).
- [ ] Worker test proves exactly-once + sequential + failure isolation.
- [ ] Control-action test proves web decision == direct `record_decision` outcome (parity).
- [ ] No test hits a real external provider (all patched).
- [ ] `deployment-guide.md` + `README.md` reflect `run-web` and the 3-process topology.

## Risk Assessment
- **Flaky claim test:** single-process test with a shared engine — assert on ordering/count deterministically (no threads needed since drain is sequential). If concurrency is simulated, seed and assert exactly-once via spy call counts.
- **TestClient + StaticFiles output mount:** point the output mount at a tmp dir in tests to avoid missing-path errors.

## Post-plan
After Phase 5 green: run `/ck:journal` to capture the DRY refactor decisions (record_decision reuse, apply_metadata_edit extraction) and the 3-process topology.
