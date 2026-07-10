---
phase: 2
title: Web Analytics Aggregates
status: completed
priority: P2
effort: 4h
dependencies:
  - 1
---

# Phase 2: Web Analytics Aggregates

## Overview
A pure read-layer that turns the existing daily `analytics` rows + the Phase-1 channel snapshot
into everything the UI needs: channel totals, freshness, top/worst videos, and per-metric trend
series — all as plain JSON-safe dicts, no browser required.

## Requirements
- Functional: one module exposes `overview()` returning `{channel, freshness, per_video[], top[], worst[], trend{}}`.
- Non-functional: pure functions over the DB (read-only); reuse the existing "latest snapshot per video" logic instead of duplicating it (DRY — the code review flagged this exact duplication).

## Architecture
- **Consolidate DRY:** promote `ops.health._latest_analytics_per_video` to a public
  `latest_analytics_per_video()` and have BOTH `health` and the new web layer call it (removes
  the duplicate `select(Analytics).order_by(...)` + setdefault currently copied into `routes_ops`).
- **Trends from existing rows:** `_query_video` stores CUMULATIVE totals as of each `as_of_date`,
  so a per-date series of `views` is a valid cumulative-growth trend. Build:
  - channel trend = for each `as_of_date`, SUM of latest-per-video-up-to-that-date views (or simpler: total views over time from the daily rows), plus a retention/CTR average series.
  - per-video sparkline = that video's `views` across its `as_of_date` rows (chronological).
- **Top/worst:** rank `latest_analytics_per_video()` by views (and expose retention/CTR sort keys).
- **Freshness:** `max(Analytics.created_at)` (last successful pull) + channel `fetched_at` from Phase-1 KV.
- Output strictly JSON-safe (ISO dates, floats) so the same dict serves HTML context and `/api`.

## Related Code Files
- Create: `src/ai_operator/web/analytics_view.py` — `overview() -> dict`, plus small helpers (`_trend_series`, `_rank`). Keep < 200 lines.
- Modify: `src/ai_operator/ops/health.py` — rename `_latest_analytics_per_video` → public `latest_analytics_per_video` (keep behavior); update its internal callers.
- Modify: `src/ai_operator/web/routes_ops.py` — `/analytics` handler delegates to `analytics_view.overview()` (drop the duplicated dedup loop). Add channel + trend + top to the context.
- Reuse: `ops.channel_stats.load_channel_stats` (Phase 1), `db.models_ops.Analytics`.

## Implementation Steps
1. Promote the health helper to public; repoint `_analytics_averages` (and any other caller) at it. Run `test_ops_health` to confirm no regression.
2. `analytics_view.overview()`:
   - `channel = channel_stats.load_channel_stats()` (may be None → template shows "—").
   - `latest = latest_analytics_per_video()`; build `per_video` dicts (existing projection).
   - `top = _rank(latest, key="views")[:N]`, `worst = ...[-N:]` (or lowest retention).
   - `trend = _trend_series()` → `{dates: [...], views: [...], retention: [...], ctr: [...]}` from grouped `Analytics` rows by `as_of_date`.
   - `freshness = {last_pull: iso(max created_at), channel_fetched_at: channel.fetched_at}`.
3. Rewire `routes_ops.analytics` to return `overview()` (HTML + JSON via existing `render`).
4. Keep `_ANALYTICS_LIMIT` behavior for the per-video table.

## Success Criteria
- [ ] `overview()` returns channel totals (or None), per_video, top, worst, trend series, freshness — all JSON-serializable.
- [ ] `health.latest_analytics_per_video` is the single source for "newest snapshot per video" (no duplicate query left in `routes_ops`).
- [ ] `/api/analytics` returns the enriched JSON; existing `test_ops_health` still green.
- [ ] Trend series length == number of distinct `as_of_date`s; empty DB → empty series (no crash).
- [ ] `analytics_view.py` < 200 lines.

## Risk Assessment
- **Cumulative-vs-daily semantics:** views snapshots are cumulative; label the chart "cumulative views" so it isn't misread as daily. Documented in code comment + chart title.
- **Sparse dates:** videos published on different days → uneven `as_of_date` coverage; aggregate defensively (missing = carry-forward or skip), never divide by zero.
