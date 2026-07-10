---
title: 'Real YouTube Analytics on the Web UI (channel totals, trends, refresh)'
description: ''
status: completed
priority: P2
branch: feat/ops-observability-validation
tags: []
blockedBy: []
blocks: []
created: '2026-07-09T10:25:33.050Z'
createdBy: 'ck:plan'
source: skill
---

# Real YouTube Analytics on the Web UI (channel totals, trends, refresh)

## Overview

Surface **real YouTube analytics** on the web control panel: the data pipeline already pulls
per-video metrics (views / watch time / retention / CTR) from the **YouTube Analytics API v2**
(`ops.analytics_puller`) into the `analytics` table — this plan makes the UI *rich and current*
on top of that. Add **channel totals** (subscribers / total views / video count via Data API
v3 `channels.list`), **trend charts** rendered as **inline SVG** (no npm, per KISS/no-build
constraint), a **top/worst videos** view, an **on-demand "Refresh from YouTube"** button
(enqueues the existing `pull-analytics` job), and a **freshness** indicator (last pull time).

**Approach:** thin read-layer over existing data (DRY) + one new channel-stats fetch reusing
the already-built Data API v3 client. Zero new heavy compute in the web process — refresh only
*enqueues* a job the scheduler drains (same pattern as the rest of the panel).

## Key constraints & decisions (user-confirmed)

- Scope: **both** on-demand refresh + freshness **and** richer analytics (channel totals,
  trends, top videos).
- Visualization: **inline SVG charts + tables** — self-drawn, no JS chart library, no npm.
- **Revenue/RPM is GATED and OUT of P1 scope:** est_revenue/rpm need the
  `yt-analytics-monetary.readonly` OAuth scope, which is NOT currently granted (only
  `youtube.upload`, `youtube.readonly`, `yt-analytics.readonly`). Adding revenue would force a
  re-authorize. The `Analytics.est_revenue/rpm` columns stay unpopulated; the UI hides revenue
  until the user opts into re-auth (documented as a follow-up, not silently included).

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Channel Stats Source](./phase-01-channel-stats-source.md) | Completed |
| 2 | [Web Analytics Aggregates](./phase-02-web-analytics-aggregates.md) | Completed |
| 3 | [UI Charts & Refresh](./phase-03-ui-charts-refresh.md) | Completed |
| 4 | [Tests & Docs](./phase-04-tests-docs.md) | Completed |

## Dependencies

- Builds on the **Web Control Panel** (`plans/260709-1253-web-control-panel-api/`, status: done,
  committed `d112421`): reuses `web/rendering.py`, `routes_ops.py` `/analytics`, `job_queue.enqueue`,
  and the `pull-analytics` DISPATCH entry. Not blocking (already merged).
- Reuses existing backend: `publisher/oauth_headless.build_youtube_service()` (Data API v3 client),
  `ops/analytics_puller` (Analytics API v2), `db.models_ops.Analytics` / `AppState`, `ops/health`.
- External: no new deps. Channel stats via already-granted `youtube.readonly` scope.

## Build order rationale

1 (channel-stats source) gives the UI new real numbers to show. 2 (read aggregates) turns the
existing daily `analytics` rows + channel stats into trend/top/freshness data — pure functions,
testable without a browser. 3 wires charts + refresh button into templates. 4 locks it with
tests (all API calls mocked) + documents the revenue re-auth caveat.
