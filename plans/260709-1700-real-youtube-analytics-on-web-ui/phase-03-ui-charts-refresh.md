---
phase: 3
title: UI Charts & Refresh
status: completed
priority: P2
effort: 5h
dependencies:
  - 2
---

# Phase 3: UI Charts & Refresh

## Overview
Render the enriched analytics on the panel: channel-total cards, inline-SVG trend charts, a
top-videos list, a "Refresh from YouTube" button, and a freshness line — plus a small trend on
the dashboard. No JS chart library, no npm.

## Requirements
- Functional: `/analytics` shows channel totals + trend chart(s) + top/worst + existing table; a Refresh button enqueues `pull-analytics`; freshness ("last pulled …") is visible.
- Non-functional: charts are server-rendered **inline SVG** (self-contained); button uses the existing enqueue → 303 PRG pattern; each new file < 200 lines.

## Architecture
- **SVG chart helper** `web/charts.py`: pure functions returning an SVG string from a list of
  numbers — `sparkline(points, w, h)` (polyline path) and `bar_chart(points, labels)` — scaled
  to the data range, themed with the existing CSS accent vars via `currentColor`/inline styles.
  No external assets; the SVG is dropped into the template with `| safe`.
- Templates consume `overview()` (Phase 2). Refresh = `POST /analytics/refresh` →
  `enqueue("pull-analytics")` → 303 back to `/analytics?msg=queued` (reuses `action_result`).
- Dashboard gets a compact channel line + a small views sparkline (reuse the same helper).

## Related Code Files
- Create: `src/ai_operator/web/charts.py` — inline-SVG chart builders.
- Modify: `src/ai_operator/web/routes_actions.py` — add `POST /analytics/refresh` (thin enqueue).
- Modify: `src/ai_operator/web/templates/analytics.html` — channel cards, freshness, refresh button (form), trend SVG, top/worst, keep the per-video table.
- Modify: `src/ai_operator/web/templates/dashboard.html` — channel totals + one sparkline.
- Modify: `src/ai_operator/web/routes_dashboard.py` — pass a trimmed `overview()` subset (channel + trend) into the dashboard context.
- Reuse: `web/rendering.action_result`, `job_queue.enqueue`, `web/analytics_view.overview`.

## Implementation Steps
1. `charts.py`: implement `sparkline()` + `bar_chart()`; guard empty input → return a small "no data" SVG or "". Deterministic output (test-friendly). Expose them as Jinja globals (register in `rendering.py`'s `templates.env.globals`) OR pre-render SVG strings in the route and pass into context. Prefer pre-render in `analytics_view`/route to keep templates dumb.
2. `POST /analytics/refresh`: `enqueue("pull-analytics")`; return `action_result(request, job, "/analytics?msg=queued")`.
3. `analytics.html`: top row = channel cards (subscribers / total views / videos) + freshness + Refresh button; then trend chart (cumulative views + retention/CTR); then Top videos + existing table. Show "—" / "Chưa có dữ liệu" when channel/trend empty.
4. Dashboard: add a channel line + a small sparkline near the existing Analytics card.
5. Smoke: `run-web` → `/analytics` renders charts from seeded rows; Refresh creates a pending `pull-analytics` job on `/jobs`.

## Success Criteria
- [ ] `/analytics` shows channel totals, an inline-SVG trend chart, top videos, freshness, and the per-video table.
- [ ] "Refresh from YouTube" enqueues a `pull-analytics` job (visible on `/jobs`), 303-redirects back.
- [ ] Charts render with zero external requests (view-source shows inline `<svg>`), and degrade to a "no data" state on an empty DB.
- [ ] Dashboard shows channel totals + a sparkline.
- [ ] `charts.py` and each touched template < 200 lines; Vietnamese labels consistent with the rest of the UI.

## Risk Assessment
- **SVG scaling edge cases:** single data point / all-equal values → avoid divide-by-zero in the y-scale; clamp and center. Covered by a chart unit test in Phase 4.
- **CSP/inline:** inline SVG is same-origin, no CSP issue; no external chart CDN (which the panel forbids anyway).
- **Refresh spam:** idempotency key on `enqueue` already dedupes repeat clicks while a pull is pending/running (no extra guard needed).
