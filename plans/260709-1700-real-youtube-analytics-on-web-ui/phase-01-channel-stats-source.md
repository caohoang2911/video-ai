---
phase: 1
title: Channel Stats Source
status: completed
priority: P2
effort: 3h
dependencies: []
---

# Phase 1: Channel Stats Source

## Overview
Add a real channel-level stats fetch (subscribers, total views, video count) from the YouTube
**Data API v3**, and fold it into the existing `pull-analytics` job so one refresh updates both
per-video and channel numbers.

## Requirements
- Functional: `pull_channel_stats()` returns/persists `{subscribers, total_views, video_count, fetched_at}` for the authorized channel; unconfigured OAuth → safe no-op (returns None), never raises.
- Non-functional: reuse the existing Data API v3 client; read-only (no budget); store as a single snapshot (KV), not a new table (YAGNI).

## Architecture
- Reuse `publisher.oauth_headless.build_youtube_service()` (already builds `youtube` v3 with the granted `youtube.readonly` scope) → `service.channels().list(part="statistics", mine=True)` → `items[0].statistics.{subscriberCount, viewCount, videoCount}`.
- Persist as one JSON blob in the existing `AppState` KV table (key `channel_stats`) with an ISO `fetched_at` — no schema migration needed. `AppState` already exists (`db/models_ops.py`).
- Called from the `pull-analytics` job so the panel's refresh button (Phase 3) covers it too.

**Revenue is explicitly excluded** — `estimatedRevenue`/RPM need `yt-analytics-monetary.readonly`
(not granted). Do not query monetary metrics; leave `Analytics.est_revenue/rpm` as-is.

## Related Code Files
- Create: `src/ai_operator/ops/channel_stats.py` — `pull_channel_stats() -> dict | None` + `load_channel_stats() -> dict | None` (read the KV snapshot for the web layer).
- Modify: `src/ai_operator/ops/analytics_puller.py` — after the per-video loop in `pull_all()`, call `channel_stats.pull_channel_stats()` (guarded; failure logged, never aborts the video pull).
- Reuse (no change): `publisher/oauth_headless.build_youtube_service`, `db.models_ops.AppState`, `db.engine.SessionLocal`.

## Implementation Steps
1. `channel_stats.py`:
   - `pull_channel_stats()`: guard on `settings.missing([...YT keys])` → None. Build v3 service, `channels().list(part="statistics", mine=True).execute()`, parse counts (ints), write `AppState(key="channel_stats", value=json.dumps({...,"fetched_at": utcnow iso}))` (upsert). Return the dict.
   - `load_channel_stats()`: read the KV row, `json.loads` or None.
   - Wrap the API call in try/except → log + return None (mirror analytics_puller's tolerance).
2. Wire into `analytics_puller.pull_all()`: `try: channel_stats.pull_channel_stats() except Exception: log.warning(...)` — outside the per-video loop, after it. Keep `pull_all`'s return (rows written) unchanged so existing tests/UI don't break.
3. Manual check: `enqueue("pull-analytics")` (or CLI `pull-analytics`) then read `AppState` key `channel_stats`.

## Success Criteria
- [ ] `pull_channel_stats()` writes a `channel_stats` KV row with subscribers/total_views/video_count/fetched_at when OAuth is configured.
- [ ] Unconfigured OAuth → returns None, no exception, no row.
- [ ] `load_channel_stats()` returns the parsed dict (or None).
- [ ] `pull_all()` still returns per-video rows-written and does not fail if channel-stats fetch errors.
- [ ] `channel_stats.py` < 120 lines; reuses the existing v3 client (no new OAuth code).

## Risk Assessment
- **Scope for channels.list:** `mine=True` needs `youtube.readonly` (granted) — verify at impl; if a 403 appears, log and no-op (don't crash the pull).
- **Quota:** `channels.list` costs 1 unit — negligible vs the daily quota; runs once per pull.
- **KV vs table:** a single snapshot in `AppState` is intentional (KISS). If channel-stats history is later wanted, that's a separate table + plan.
