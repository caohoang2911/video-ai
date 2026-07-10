---
phase: 4
title: Tests & Docs
status: completed
priority: P2
effort: 3h
dependencies:
  - 3
---

# Phase 4: Tests & Docs

## Overview
Lock the new behavior with pytest (channel-stats fetch, aggregates, SVG helper, refresh
endpoint) and document the revenue re-auth caveat.

## Requirements
- Functional: tests cover channel-stats parse + no-op guard, `overview()` aggregates/top/trend/freshness, SVG chart edge cases, and the refresh endpoint enqueue.
- Non-functional: no network — the Data API v3 + Analytics API services are mocked; use the shared `temp_db` fixture.

## Architecture
- Mock `channel_stats.build_youtube_service` (patch the boundary) to return a fake `channels().list().execute()` payload → assert KV write + parse.
- Seed `Analytics` rows across multiple `as_of_date`s + videos via `temp_db`, call `overview()`, assert top/worst order, trend length, freshness.
- `charts.py`: assert SVG string contains `<svg`/`<polyline>` and handles empty / single-point / all-equal inputs.
- `TestClient` for `POST /analytics/refresh` → assert a pending `pull-analytics` Job exists.

## Related Code Files
- Create:
  - `tests/test_channel_stats.py` — parse + unconfigured no-op + KV upsert.
  - `tests/test_web_analytics_view.py` — `overview()` top/worst/trend/freshness from seeded rows; DRY helper parity with `health.latest_analytics_per_video`.
  - `tests/test_web_charts.py` — sparkline/bar edge cases.
  - `tests/test_web_analytics_refresh.py` — POST refresh enqueues job (TestClient).
- Modify:
  - `docs/deployment-guide.md` — note the new `/analytics` capabilities + the **revenue requires `yt-analytics-monetary.readonly` re-auth** caveat.
  - `README.md` if the analytics surface is described there.
- Reuse: `tests/conftest.py` (`temp_db`, `temp_db_fk`).

## Implementation Steps
1. `test_channel_stats`: patch the v3 service builder; feed `{"items":[{"statistics":{"subscriberCount":"1234","viewCount":"56789","videoCount":"12"}}]}`; assert `pull_channel_stats()` writes the KV row and `load_channel_stats()` returns ints + `fetched_at`. Separately: `settings` missing YT keys → returns None, no row.
2. `test_web_analytics_view`: seed 3 videos × 2 dates; assert `overview()['top'][0]` is the highest-views video, trend `dates` sorted unique, `freshness.last_pull` == newest `created_at`.
3. `test_web_charts`: `sparkline([])`, `[5]`, `[3,3,3]`, `[1,9,4]` → valid SVG, no exception, no NaN in coords.
4. `test_web_analytics_refresh`: `TestClient(create_app())` POST `/api/analytics/refresh` → 200/JSON + a pending `pull-analytics` Job in the DB.
5. Run full suite `PYTHONPATH=src .venv/bin/pytest -q`; fix failures (don't skip).
6. Docs: concise additions; call out the revenue caveat explicitly.

## Success Criteria
- [ ] All new tests pass; existing suite still green.
- [ ] No test performs a real network/API call (Data API + Analytics API mocked).
- [ ] Channel-stats no-op path (unconfigured OAuth) covered.
- [ ] Chart helper proven safe on empty/degenerate inputs.
- [ ] `deployment-guide.md` documents the enriched `/analytics` + the revenue re-auth caveat.

## Risk Assessment
- **Mock drift:** patch the service *builder* boundary (not deep internals) so the test stays valid if `channels().list` argument details change.
- **Trend assertions on cumulative data:** assert on ordering/length/non-negativity, not exact values, to avoid brittleness.

## Post-plan
After Phase 4 green: `/ck:journal` to capture the DRY consolidation (`latest_analytics_per_video`)
and the deliberate revenue-scope exclusion.
