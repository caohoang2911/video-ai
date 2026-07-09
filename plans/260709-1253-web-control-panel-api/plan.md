---
title: "Web Control Panel + API (FastAPI/HTMX, DB job queue)"
description: "Local web control panel + REST/JSON API to view & drive the pipeline; heavy steps enqueue into scheduler via a DB job queue."
status: done
priority: P2
branch: "feat/ops-observability-validation"
tags: [web, api, fastapi, htmx, ops]
blockedBy: []
blocks: []
created: "2026-07-09T06:04:54.640Z"
createdBy: "ck:plan"
source: skill
---

# Web Control Panel + API (FastAPI/HTMX, DB job queue)

## Overview

Add a **local-only web control panel + REST/JSON API** so the whole pipeline (topics → script → voice → visuals → assemble → review → publish → analytics) can be viewed and driven from a browser instead of only CLI + Telegram.

**Approach A (approved):** 3 long-lived processes share one SQLite DB — `run-web` (FastAPI, bind `127.0.0.1`), `run-scheduler` (executor), `run-bot` (Telegram, coexists). Web never runs heavy compute: it **enqueues jobs** into a new `jobs` table; the scheduler drains and dispatches them to the *existing* `pipeline_runner`/commands. Light review actions (approve/reject/edit) call the transport-agnostic core `record_decision()` directly.

Source of truth: `plans/reports/from-brainstorm-to-plan-260709-1253-web-control-panel-api-report.md`.

**Core principles:** DRY (web = thin adapter over existing logic, zero business-logic duplication), KISS/YAGNI (server-rendered HTMX, no npm, no auth), each new file <200 lines.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Foundation & Job Model](./phase-01-foundation-job-model.md) | Done |
| 2 | [Job Worker & Scheduler Wiring](./phase-02-job-worker-scheduler-wiring.md) | Done |
| 3 | [Web App & Read Views](./phase-03-web-app-read-views.md) | Done |
| 4 | [Control Actions](./phase-04-control-actions.md) | Done |
| 5 | [Tests & Docs](./phase-05-tests-docs.md) | Done |

## Key Decisions (user-confirmed — do NOT auto-reverse)

- Scope: **full control panel** (view + control). UI: **FastAPI + HTMX/Jinja**. Auth: **local-only, bind 127.0.0.1, none**. Execution: **enqueue into scheduler only**. Topology: **A (3 process + DB queue)**.
- Heavy (compute/network) → **enqueue** (`jobs`): produce, gen-script, gen-audio, gen-visuals, revoice, assemble, publish, pull-analytics.
- Light (DB mutation) → **direct** call: approve/reject/edit/hold via `record_decision()`; set-winner via `publisher.set_winner()`.
- Reuse core is **`review.decision_store.record_decision(video_id, code, reason)`** (audit row + state transition, one tx) — NOT the Telegram-bound async `finalize_decision`.

## Dependencies

- Related (not blocking): `plans/260708-1548-lean-faceless-ai-video-operator-system/phase-08-observability-deploy.md` sketched a P1 read-only FastAPI dashboard. This plan **supersedes & extends** that sketch into a full control panel. Pipeline code it builds on already exists (foundation phases implemented), so no hard `blockedBy`.
- External deps to add: `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`. HTMX shipped as one static JS file (no npm).
- Existing invariants reused: SQLite **WAL** already on (`db/engine.py`, `busy_timeout=5000`); `init_db()` = `Base.metadata.create_all` (new `Job` model auto-creates on re-run); state machine `assert_transition` guards decisions.

## Build order rationale

1→2 first (queue data + executor) so the control surface has somewhere to enqueue. 3 (read views) proves DB rendering + `run-web`. 4 wires buttons to enqueue/direct-actions. 5 locks behavior with tests + docs.
