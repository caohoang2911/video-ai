# Phase 03 — Retention Curve Ingestion + Analytics View

Priority: MEDIUM | Status: done | Effort: S-M (~half-1 day) | Independent of Phases 01/02

## Context links

- `src/ai_operator/ops/analytics_puller.py:23` — pulls only `views,estimatedMinutesWatched,averageViewPercentage`
- `src/ai_operator/db/models_ops.py:33` — `avg_view_pct` single float per video
- `src/ai_operator/web/analytics_view.py`, `templates/analytics.html`
- Research report unresolved Q1 (narration length A/B) blocked on exactly this data

## Key insights

- Advisor's "phân tích giây thứ bao nhiêu khán giả phản hồi tốt nhất" is impossible today —
  only aggregate retention % stored. This phase closes that loop.
- YouTube Analytics API: metric `audienceWatchRatio` (+`relativeRetentionPerformance`),
  dimension `elapsedVideoTimeRatio` (100 buckets, 0.01–1.0), filter `video==ID`. Same authorized
  scope as current pulls — verify token has `yt-analytics.readonly` (it must, current puller works).
- Sparse-data reality: curves need view volume; low-view videos return few/no rows. Store what
  arrives, render "insufficient data" gracefully. Directional tool, not daily driver, until views grow.

## Requirements

1. New table `retention_curve` (video_id FK, elapsed_ratio float, watch_ratio float,
   relative_perf float nullable, pulled_at) — replace-on-pull per video (curves are cumulative
   snapshots, no need for history).
2. Puller extension: fetch curve per published video on the existing daily `analytics_job`; skip
   videos <N views (e.g. 200) to save quota; tolerate empty result (same failure-isolation pattern
   as CTR quirk handling `analytics_puller.py:26`).
3. Web: retention sparkline on video detail page + hook-zone readout ("% remaining at 2s/5s/10s"
   — the actionable numbers for hook iteration). Shorts: overlay sibling curves on one chart for
   angle-vs-angle comparison (Halifax-trio style analysis becomes one glance).

## Related code files

- Modify: `ops/analytics_puller.py`, `db/models_ops.py` (+migration path per existing convention)
- Modify: `web/analytics_view.py` or `web/routes_videos.py` + `templates/video_detail.html`
- Tests: extend `tests/test_web_analytics_view.py`; puller unit test with stubbed API response

## Implementation steps

1. Model + table. 2. Puller: second query per video inside existing job loop, threshold-gated.
3. Detail-page sparkline (inline SVG, no new JS dep — match existing chart approach in analytics view).
4. Hook-zone stats line. 5. Sibling overlay on parent page.

## Success criteria

- After next analytics job run: videos with sufficient views show a curve; others show explicit
  "not enough data yet" (not blank/error).
- Can answer "at which second does Halifax #22 lose viewers vs #23/#24" from the UI.

## Risks

- Quota: 1 extra query/video/day — negligible vs Data API upload costs; still respect existing throttle.
- Don't over-read low-sample curves — surface view count next to chart to anchor interpretation.
