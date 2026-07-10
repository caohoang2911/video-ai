---
phase: 4
title: "Gen-Shorts Job & Wiring"
status: completed
priority: P1
effort: "5h"
dependencies: [2, 3]
---

# Phase 4: Gen-Shorts Job & Wiring

## Overview
The orchestration that ties it together: a `gen-shorts` job (auto-enqueued when a main video is
published) creates 2-3 child shorts and drives each through script→TTS→vertical render→review.

## Requirements
- Functional: `generate_shorts(parent_video_id)` produces 2-3 child `Video`s (kind=short,
  parent_id), each rendered vertical and left at `pending_review`; idempotent (re-running for the
  same parent doesn't duplicate shorts).
- Non-functional: reuse existing steps (tts_narrator, visual reuse, short_builder, review notify);
  never recurse (a short never spawns shorts); heavy work runs in the scheduler, not the web process.

## Architecture
- New `ops/shorts_runner.py` — `generate_shorts(parent_video_id)`:
  1. Load parent `script.json`; `short_script_generator.generate_short_scripts(...)`.
  2. For each short: create a child `Video` (kind=short, parent_id, unique idempotency_key
     `short:{parent}:{index}`), write `output/<child_id>/script.json`.
  3. Synthesize the short narration (reuse `media.tts_narrator` via a small `gen_audio`-like call;
     char-guarded).
  4. Reuse parent visual `Asset`s matched by beat keywords (copy/reference into the short's beats);
     fallback to `visual_fetcher` only if a beat has no match.
  5. `assembler.short_builder.build_short(child_id)` → vertical `final.mp4`.
  6. Advance the child to `pending_review` via the existing review notifier (same gate as mains).
- **Idempotency + regenerate (force):** `generate_shorts(parent_video_id, force=False)`. Normal
  path skips a parent that already has shorts. `force=True` (the panel "Regenerate Shorts" button,
  Phase 5) first **discards the parent's non-published shorts** (pending/failed/rejected child rows
  + their `output/<id>/` dirs), then generates a fresh batch — for when a batch is weak.
- **Rejected short = discard (user-confirmed):** a short REJECTED at the review gate stays
  `rejected` and is simply never published — **no rework loop** (shorts are cheap; re-roll via the
  regenerate button instead). Do NOT wire shorts into the main videos' rerun/edit rework paths.
- **Auto-enqueue after publish:** where a main video's state becomes `published` (in
  `publisher/publish.py` after a confirmed upload, or `scheduler.publish_job`), enqueue
  `("gen-shorts", video_id=parent)` — GUARDED to `kind=="main"` so shorts never trigger shorts.
- Job queue: add `gen-shorts` to `web.job_queue.JOB_COMMANDS` and `ops.job_worker.DISPATCH`
  (the parity test keeps them in lockstep).

## Related Code Files
- Create: `src/ai_operator/ops/shorts_runner.py`.
- Modify: `src/ai_operator/web/job_queue.py` — add `gen-shorts` to `JOB_COMMANDS`.
- Modify: `src/ai_operator/ops/job_worker.py` — add `gen-shorts` → `shorts_runner.generate_shorts`.
- Modify: `src/ai_operator/publisher/publish.py` (or `ops/scheduler.publish_job`) — enqueue
  `gen-shorts` after a main video is confirmed published (kind-guarded).
- Reuse: `content/short_script_generator`, `media/tts_narrator`, `media/visual_fetcher`,
  `assembler/short_builder`, `review/review_notifier`.

## Implementation Steps
1. `shorts_runner.generate_shorts` per the flow above; wrap each short in try/except so one bad
   short doesn't abort the others; log per short.
2. Register `gen-shorts` in `JOB_COMMANDS` + `DISPATCH` (keep the parity test green).
3. Auto-enqueue: at the post-publish point, `enqueue("gen-shorts", video_id=parent)` only if
   `video.kind == "main"` and it has no shorts yet.
4. Manual: seed a "published" main with a `script.json`, run `drain_jobs` (patched TTS/render) →
   2-3 child shorts exist at `pending_review` with `parent_id` set.

## Success Criteria
- [ ] Enqueued `gen-shorts` creates 2-3 child shorts (kind=short, parent_id), each `pending_review`.
- [ ] Re-running `gen-shorts` (force=False) for the same parent does not duplicate shorts (idempotent).
- [ ] `gen-shorts` with force=True discards the parent's non-published shorts and regenerates a fresh batch.
- [ ] A rejected short stays `rejected` and is never published; shorts are not wired into rework/edit loops.
- [ ] Publishing a main video auto-enqueues exactly one `gen-shorts`; a short never enqueues shorts.
- [ ] `JOB_COMMANDS` == `DISPATCH` keys (parity test passes); one failing short doesn't abort the rest.
- [ ] `shorts_runner.py` < 200 lines; reuses existing steps (no duplicated pipeline logic).

## Risk Assessment
- **Long job:** rendering 2-3 shorts holds the single worker for minutes — acceptable (matches
  main render); surfaced on the live `/jobs` view.
- **Asset reuse mismatch:** a short beat with no matching parent asset → fallback fetch (small cost)
  or a branded text card; never leave a blank beat.
- **Partial failure:** a short that fails render leaves its child row in a non-review state — mark it
  `failed` so it's visible and doesn't masquerade as ready.
