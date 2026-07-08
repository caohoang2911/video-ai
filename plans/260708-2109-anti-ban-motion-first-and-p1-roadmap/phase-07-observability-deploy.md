---
phase: 7
title: "Observability + deploy"
status: pending
priority: P3
effort: "3-4h"
dependencies: [6]
---

# Phase 7: Observability + deploy

## Overview
Make the always-on operator observable and runnable unattended: a status/metrics surface over the existing
logs + DB, and a deploy path (start with the M1 Mac always-on; Docker/cloud optional). KISS — no Grafana.

## Requirements
- Functional: a `status`/`health` CLI showing pipeline state counts, month budget, quota, last publish,
  recent errors, per-video metrics, and `output/` disk usage; a supervised run of the scheduler that
  restarts on crash.
- Non-functional: log-file + DB are the source of truth (no new infra at P0); secrets stay in `.env`.

## Architecture
Reuse `logging_setup` (rotating file) + the `analytics`/`app_state`/`cost_ledger` tables. `ops/health.py`
aggregates a one-screen status. Deploy: a launchd/systemd/`supervisor`-style wrapper to keep
`run-scheduler` alive on the Mac; an optional `Dockerfile` for a future Fly.io/Hetzner move (deploy target
still open). Log ffmpeg/API failures with enough context to debug unattended.

## Related Code Files
- Create: `src/ai_operator/ops/health.py` (aggregate: state counts, budget, quota, last publish, recent errors, retention/CTR summary, `output/` disk-usage summary)
- Modify: `src/ai_operator/ops/commands.py` (add `health`/`dashboard` verb)
- Create: `deploy/` (launchd plist OR run script for Mac always-on; optional `Dockerfile`; `docs/deployment-guide.md` note)
- Modify: `src/ai_operator/logging_setup.py` (only if structured fields needed; otherwise reuse as-is)

## Implementation Steps
1. `health.py`: `snapshot()` → dict of pipeline counts by state, `budget_remaining`, quota used today,
   last publish time, N most-recent errors from the log, avg retention/CTR from `analytics`, and a
   disk-usage line for `output/` (total size + per-`<id>` size, surfacing any working dir that missed
   phase 05's post-encode cleanup or phase 05/07's post-publish prune).
2. `commands.py`: `health` prints the snapshot (human table); optional `--json`.
3. `deploy/`: a keep-alive runner for `run-scheduler` on macOS (launchd plist or a bash supervisor with
   restart-on-exit); document how to start/stop. Add a minimal `Dockerfile` for a future cloud move (not activated).
4. `docs/deployment-guide.md`: fill the deploy steps for the chosen target (Mac always-on default).
5. Verify: `health` runs against the dev DB; deploy runner starts/stops the scheduler cleanly.

## Success Criteria
- [ ] `operator health` shows one-screen status (states, budget, quota, last publish, recent errors, retention/CTR, `output/` disk usage).
- [ ] Scheduler runs under a supervisor that restarts it on crash (Mac always-on).
- [ ] `docs/deployment-guide.md` documents the run/stop procedure; optional Dockerfile present.
- [ ] compile + import clean.

## Risk Assessment
- Over-engineering: keep to log + DB + one status command (no metrics stack at P0).
- Deploy target undecided (Mac vs Fly.io vs Hetzner): default Mac always-on; Dockerfile keeps the door open.
- Unattended failure blindness: ensure ffmpeg/API errors log actionable context; `health` surfaces recent errors.
