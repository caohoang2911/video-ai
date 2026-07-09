---
phase: 6
title: "Scheduler + analytics loop"
status: done
priority: P2
effort: "4-6h"
dependencies: [1, 2, 3, 5]
---

# Phase 6: Scheduler + analytics loop

## Overview
Turn the hand-run CLI pipeline into an always-on operator: an APScheduler-driven runner that produces
videos, publishes approved ones at a randomized cadence reconciled to the ElevenLabs Creator char
budget (~1-1.5/week, ~5/mo — not a standalone weekly number), pulls analytics, keeps the OAuth token
alive, and feeds the human-observed A/B winner back to the content engine.

## Requirements
- Functional: schedule generation + publish; **randomize publish day/time** within a cadence reconciled
  to the ElevenLabs Creator tier's 100k chars/mo (~1-1.5 videos/week, ~5/mo target — breaks algorithmic
  template detection AND stays under the char budget); pull YouTube Analytics (views/retention/CTR) into
  `analytics`; monthly `creds.refresh()` keep-alive; read `uploads.winning_title/thumbnail` → bias future content.
- Functional: produce/publish jobs check `elevenlabs_char_guard` (phase 01) before starting a new video —
  if the monthly ElevenLabs char quota is exhausted, the job SKIPS (does not produce/publish) and ALERTS
  (log + Telegram if wired), rather than silently over-flagging videos `needs_revoice` past the quota.
- Non-functional: single writer (SQLite WAL); idempotent step runner (reuse `checkpoint`); throttle honored —
  the ElevenLabs monthly CHARACTER ledger is the hard cap; `WEEKLY_VIDEO_CAP` is a soft cadence knob
  tuned to stay under it, not an independent limit.

## Architecture
New `ops/` package. `pipeline_runner.py` chains the existing per-step functions (gen-script → gen-audio →
gen-visuals → assemble → notify-review) for a video, resuming via checkpoints. `scheduler.py` (APScheduler)
holds jobs: produce (draft pipeline; checks `elevenlabs_char_guard` before starting — skip + alert if the
monthly char quota is exhausted), publish (scan `approved`, respect throttle + random jitter + the same
char-guard check), analytics pull, token keep-alive. `analytics_puller.py` uses the YouTube Analytics API
(yt-analytics.readonly scope already requested). `feedback.py` reads winners and nudges topic/title/thumbnail selection.

## Related Code Files
- Create: `src/ai_operator/ops/__init__.py`, `ops/pipeline_runner.py` (chain steps for one video, checkpoint-resumed)
- Create: `src/ai_operator/ops/scheduler.py` (APScheduler jobs: produce / publish-with-jitter / analytics / keepalive)
- Create: `src/ai_operator/ops/analytics_puller.py` (YouTube Analytics API → `analytics` rows)
- Create: `src/ai_operator/ops/keepalive.py` (monthly `creds.refresh()` so refresh token never expires)
- Create: `src/ai_operator/ops/feedback.py` (read `uploads` winners → bias content-engine selection)
- Create: `src/ai_operator/ops/commands.py` (`register`: `run-scheduler`, `pull-analytics`, `keepalive`, `run-pipeline --video-id`)
- Reference: `src/ai_operator/cost/elevenlabs_char_guard.py` (phase 01 — monthly char quota check
  consumed by the produce + publish jobs)

## Implementation Steps
1. `pipeline_runner.py`: `run_video(video_id)` executes each pipeline step in order, skipping checkpoint-done
   steps; stops at `pending_review` (human gate). `run_new(topic_id)` = pick topic → run_video.
2. `scheduler.py`: APScheduler `BackgroundScheduler`; jobs — (a) produce N drafts/week, checking
   `elevenlabs_char_guard.check_char_quota()` first — if the monthly char quota is exhausted, SKIP the
   produce run and ALERT (log + Telegram) instead of generating a video that will just land in
   `needs_revoice`; (b) publish scan: `approved` + not `needs_revoice` + throttle_ok +
   char-quota-not-exhausted → `publish()` at a randomized time (Python `random` jitter across the week,
   not fixed slots); (c) daily analytics pull; (d) monthly keepalive.
3. `analytics_puller.py`: query Analytics API per published video; upsert `analytics(views, watch_time,
   avg_view_pct, ctr, ...)`; budget-free (read-only).
4. `keepalive.py`: call `creds.refresh(Request())` monthly; log; alert on failure (token risk).
5. `feedback.py`: read `uploads.winning_title/winning_thumbnail`; expose a hint the content engine can use.
6. `commands.py`: register the CLI verbs; `run-scheduler` blocks (foreground P0/P1). Verify compile + import;
   scheduler starts with no keys as a dry no-op (jobs guard on missing config); a mocked exhausted char
   quota skips produce/publish and logs an alert instead of silently flagging videos `needs_revoice`.

## Success Criteria
- [ ] `run-scheduler` starts APScheduler with produce/publish/analytics/keepalive jobs (guards when unconfigured).
- [ ] Publish job honors `WEEKLY_VIDEO_CAP` as a soft cadence knob tuned to the ElevenLabs Creator char
      budget (~1-1.5/week, ~5/mo target), skips `needs_revoice`, and uses a randomized time (not a fixed slot).
- [ ] Produce/publish jobs SKIP + ALERT (not silently over-flag) when the monthly ElevenLabs char quota
      (`elevenlabs_char_guard`) is exhausted.
- [ ] `pull-analytics` writes `analytics` rows from the Analytics API.
- [ ] `keepalive` refreshes the OAuth token; feedback reads A/B winners.
- [ ] Key-free pytest: scheduler throttle + jitter logic exercised with a frozen clock (no live
      APScheduler run, no API keys) — asserts jitter stays within the weekly window and the char-quota
      skip path fires when `elevenlabs_char_guard` reports exhausted.
- [ ] compile + import clean.

## Risk Assessment
- SQLite write contention (scheduler + app): WAL + short txns + single scheduler instance.
- Analytics API quota/lag: daily pull, tolerate empty early windows.
- Token expiry if scheduler down >6 months: keepalive job + alerting; document manual re-auth path.
- ElevenLabs char quota exhaustion stalling the whole cadence: the 70% alert (phase 01) gives lead time
  before the hard skip; document the manual tier-upgrade path if ~5/mo is consistently too tight.
