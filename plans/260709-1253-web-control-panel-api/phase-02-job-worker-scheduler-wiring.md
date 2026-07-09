---
phase: 2
title: "Job Worker & Scheduler Wiring"
status: pending
priority: P1
effort: "4h"
dependencies: [1]
---

# Phase 2: Job Worker & Scheduler Wiring

## Overview
The consumer side: a `drain_jobs()` that atomically claims one pending job and dispatches it to the *existing* pipeline functions, wired into the running scheduler.

## Requirements
- Functional: pending jobs are executed exactly once, sequentially; each terminal state (`done`/`failed` with error text) is recorded.
- Non-functional: zero duplication of pipeline logic — dispatch map points at existing callables; worker never kills the scheduler loop.

## Architecture
Single-worker drain (`max_instances=1`) → one job at a time → no SQLite writer contention, no ordering surprises. Claim is atomic via a guarded `UPDATE`. Dispatch map is the ONLY place command-strings bind to functions.

```
scheduler (every ~20s): drain_jobs()
  claim: UPDATE jobs SET status='running', started_at=now
         WHERE id = (SELECT id FROM jobs WHERE status='pending' ORDER BY id LIMIT 1)
  dispatch[command](video_id/topic_id/params)  # existing pipeline fns
  finish: status='done' | 'failed'(+error), finished_at=now
```

## Related Code Files
- Create: `src/ai_operator/ops/job_worker.py` — `DISPATCH: dict[str, Callable]`, `claim_next() -> Job|None`, `run_job(job)`, `drain_jobs()`.
- Modify: `src/ai_operator/ops/scheduler.py` — in `build_scheduler()` add `sched.add_job(job_worker.drain_jobs, "interval", seconds=20, id="jobs", max_instances=1, coalesce=True)`.

## Implementation Steps
1. `DISPATCH` map (reuse, don't reimplement):
   - `produce` → `pipeline_runner.run_new(topic_id=..., motion=params.get("motion", False))`
   - `gen-script` → `content ...` (existing script command path used by `run_new`; if only reachable via run_new, expose `produce` and drop standalone `gen-script` from allowlist — reconcile with Phase 1 `JOB_COMMANDS`).
   - `gen-audio` → `media.commands.gen_audio(video_id=...)`
   - `gen-visuals` → `media.commands.gen_visuals(video_id=..., motion=...)`
   - `revoice` → `media.commands.revoice(video_id=...)`
   - `assemble` → `assembler.commands.assemble(...)` / `assemble_video(video_id)`
   - `publish` → `publisher.publish.publish(video_id, publish_at_iso=scheduler.jittered_publish_at(...))`
   - `pull-analytics` → `analytics_puller.pull_all()`
   - Verify each signature against source before finalizing (some take `video_id=` kwarg, some positional).
2. `claim_next()`: guarded UPDATE (above). Return the claimed `Job` (re-`SELECT` by id) or `None`. Rely on WAL + `busy_timeout` for the single-writer guarantee.
3. `run_job(job)`: `try: DISPATCH[job.command](...)` → set `done`; `except Exception as exc: set failed + error=str(exc)[:2000]`; always set `finished_at`. Never re-raise (mirrors scheduler jobs' `# noqa: BLE001` pattern).
4. `drain_jobs()`: loop `claim_next()` until `None` (drains backlog each tick), but cap iterations (e.g. 5) so one tick can't run forever; log per job.
5. Wire into `scheduler.build_scheduler()`; import `job_worker` alongside existing `from . import ...`.
6. Manual check: `enqueue("pull-analytics")` then run `operator run-scheduler` briefly → job flips `pending→running→done`.

## Success Criteria
- [ ] Enqueued job transitions `pending → running → done`; `finished_at` set.
- [ ] A command that raises → job `failed` with `error` populated; scheduler keeps running (other jobs unaffected).
- [ ] Two pending jobs run **sequentially**, in id order, each exactly once (no double-execute).
- [ ] Reconciled: every command in Phase 1 `JOB_COMMANDS` has a `DISPATCH` entry and vice-versa (no orphan command).
- [ ] `job_worker.py` <200 lines; no pipeline logic duplicated (only calls existing fns).

## Risk Assessment
- **Long job blocks the tick:** a 5-min render holds the worker; other enqueued jobs wait. Acceptable for solo operator (matches today's sequential produce/publish). `/jobs` page (Phase 3) surfaces the wait.
- **`gen-script` reachability:** if scripting is only invoked inside `run_new`, don't fake a standalone path — collapse to `produce` and update the allowlist. Decide during impl by reading `content/commands.py`.
- **Signature drift:** dispatch calls must match real kwargs; verify each against source (checkpoint in step 1).
