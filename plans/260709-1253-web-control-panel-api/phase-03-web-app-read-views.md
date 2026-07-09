---
phase: 3
title: "Web App & Read Views"
status: pending
priority: P1
effort: "6h"
dependencies: [1]
---

# Phase 3: Web App & Read Views

## Overview
The FastAPI app + read-only views (dashboard, videos, costs, analytics, jobs) + the `run-web` command. Proves DB→HTML rendering and the JSON API surface before any control action.

## Requirements
- Functional: browse pipeline state from a browser; every page also returns JSON.
- Non-functional: bind `127.0.0.1` only; no auth; server-rendered HTMX; no npm/build step; each route file <200 lines.

## Architecture
FastAPI factory mounts routers + Jinja templates + static (`htmx.min.js`, 1 css). Read handlers query DB via `SessionLocal` (read-only). Content negotiation: same handler renders template for browsers, returns JSON when path is `/api/...` (or `Accept: application/json`). Reuse `ops.health` snapshot for the dashboard instead of re-querying.

```
web/app.py (factory) ──mounts──> routes_dashboard / routes_videos / routes_ops
                     ──StaticFiles──> web/static + read-only mount of output dir (video preview)
```

## Related Code Files
- Create:
  - `src/ai_operator/web/app.py` — `create_app()`; `Jinja2Templates`; mount routers; `StaticFiles` for `web/static` and a **read-only** mount of the render output dir (preview mp4/thumb).
  - `src/ai_operator/web/routes_dashboard.py` — `/` : reuse `ops.health` dict + `validation-report`.
  - `src/ai_operator/web/routes_videos.py` — `/videos` (list+filter by state), `/videos/{id}` (detail: paths, cost rows, assets).
  - `src/ai_operator/web/routes_ops.py` — `/costs`, `/analytics`, `/jobs`.
  - `src/ai_operator/web/commands.py` — `run-web` → `uvicorn.run(create_app(), host=settings.WEB_HOST, port=settings.WEB_PORT)`; `register(app)`.
  - `src/ai_operator/web/templates/` — `base.html` (+htmx), `dashboard.html`, `videos.html`, `video_detail.html`, `costs.html`, `analytics.html`, `jobs.html`.
  - `src/ai_operator/web/static/` — `htmx.min.js`, `app.css`.
- Modify: `src/ai_operator/cli.py` — add `"web.commands"` to `_PHASE_COMMAND_MODULES`.

## Implementation Steps
1. `app.py`: `create_app()` builds `FastAPI()`, sets `Jinja2Templates(directory=web/templates)`, mounts static + read-only output dir, includes the three routers. Keep thin.
2. Read handlers (DRY helper for JSON-vs-HTML): a small `render(request, template, ctx)` that returns `JSONResponse(ctx)` when JSON is requested else `templates.TemplateResponse`.
3. `routes_dashboard`: call existing `ops.health` snapshot fn (the one behind `health --json`) + validation aggregate → render counts/budget/quota/last-errors/PASS-KILL.
4. `routes_videos`: list query (`select(Video)` with optional `?state=`), order by `updated_at desc`; detail loads Video + its `Asset`s + `CostLedger` rows.
5. `routes_ops`: `/costs` (ledger grouped by provider/ym), `/analytics` (Analytics rows), `/jobs` (Job rows newest-first, show status + error).
6. Templates: `base.html` includes `htmx.min.js`; minimal tables; action buttons stubbed (wired in Phase 4). Vendor `htmx.min.js` into static (download once, commit).
7. `web/commands.py` `run-web`; add to `_PHASE_COMMAND_MODULES`.
8. Smoke: `operator run-web` → open `http://127.0.0.1:8000/` and each page renders; `curl /api/videos` returns JSON.

## Success Criteria
- [ ] `operator run-web` serves on `127.0.0.1:8000` (not `0.0.0.0`).
- [ ] `/`, `/videos`, `/videos/{id}`, `/costs`, `/analytics`, `/jobs` render from live DB.
- [ ] JSON variant returns structured data for each (content negotiation works).
- [ ] Dashboard reuses `ops.health` (no duplicated status query).
- [ ] Video preview mp4/thumb served from the read-only output mount.
- [ ] Each `routes_*.py` and `app.py` <200 lines.

## Risk Assessment
- **Serving local media:** mount output dir read-only, no directory traversal beyond it (FastAPI `StaticFiles` is path-safe). Local-only so low risk.
- **`ops.health` import shape:** confirm the snapshot fn is importable without side effects (it powers `health --json`, so it should be). If it prints, extract the pure dict builder.
- **Template sprawl:** keep one `base.html`; avoid per-widget partlikes beyond what HTMX needs.
