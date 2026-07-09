---
phase: 4
title: "Control Actions"
status: pending
priority: P1
effort: "5h"
dependencies: [2, 3]
---

# Phase 4: Control Actions

## Overview
Wire the buttons: heavy actions POST → enqueue (`jobs`); light review actions POST → `record_decision()` directly. This is where "control panel" becomes real.

## Requirements
- Functional: from the UI, enqueue any heavy step and approve/reject/edit/hold + set-winner a video; results reflected on `/jobs` and video state.
- Non-functional: reuse existing decision core (no duplicated transition logic); stale transitions fail gracefully.

## Architecture
Two POST families:
- **Enqueue** `POST /jobs` (and per-object shortcuts like `POST /videos/{id}/gen-audio`) → `job_queue.enqueue(...)` → 303 redirect / HTMX swap showing the new pending job.
- **Direct decision** `POST /videos/{id}/decision` (form: `code`, optional `reason`) → `review.decision_store.record_decision(video_id, code, reason)` → on `InvalidTransition` show "already moved past this step" (mirrors Telegram copy). Edit metadata = a form posting the new title/description/tags applied in the same handler (web replaces Telegram's stateful `edit_pending`).
- **Set winner** `POST /videos/{id}/set-winner` → `publisher.ab_variants.set_winner(video_id, title=?, thumb=?)`.

Decision codes come from `review.decision_codes` (`PASS_POLICY`, `PASS_QUALITY`, `HOLD_RERUN`, `REJECT_POLICY_*`, `EDIT_*`) — reuse the enum/constants, don't hardcode strings.

## Related Code Files
- Modify: `src/ai_operator/web/routes_videos.py` — add POST handlers (enqueue shortcuts + `/decision` + `/set-winner`).
- Modify: `src/ai_operator/web/routes_topics.py` (create if not already) — `/topics` list + `POST /topics/gen` (enqueue `produce`/gen-topics) + `POST /topics/{id}/produce`.
- Modify: templates `video_detail.html`, `topics.html` — real forms/HTMX buttons.
- Reuse (no change): `review/decision_store.record_decision`, `review/decision_codes`, `web/job_queue.enqueue`, `publisher/ab_variants.set_winner`.

## Implementation Steps
1. Decision handler: parse `code` against `decision_codes` (reject unknown → 400). Call `record_decision`; catch `InvalidTransition` → flash message, re-render detail. For `EDIT_*`, also accept `title/description/tags` form fields and persist to the `Video` row in the same tx path the Telegram edit uses (find & reuse it; do not fork the write).
2. Enqueue shortcuts: thin handlers → `enqueue(command, video_id=...)`; return HTMX partial appending the pending job (or 303 to `/jobs`).
3. Topics: `gen-topics` and `produce` as enqueued jobs; `produce` may carry `topic_id` param.
4. HTMX buttons: `hx-post` + `hx-target` to swap a status area without full reload; disable button after click to reduce double-submit (idempotency key already backstops).
5. Consistency check: approve via web then inspect DB — identical `decisions` row + state as the Telegram path would produce (same `record_decision`).
6. Guard: buttons only shown for states where the action is legal (use `can_transition` to decide render), so the UI doesn't offer illegal moves.

## Success Criteria
- [ ] Approve/reject/hold from web writes the same `decisions` audit row + state transition as Telegram (same `record_decision`).
- [ ] Edit metadata from web updates title/description/tags and moves state per `EDIT_*` without a separate stateful step.
- [ ] Enqueue buttons create `pending` jobs visible on `/jobs`; scheduler runs them.
- [ ] Stale/illegal decision → graceful "already moved past" message, no 500.
- [ ] Set-winner applies via `publisher.set_winner` (no duplicated logic).
- [ ] Illegal actions not offered in UI (gated by `can_transition`).

## Risk Assessment
- **Double-submit:** idempotency key (Phase 1) + button-disable makes duplicate enqueue a no-op; decisions are guarded by `assert_transition` so a second approve just raises InvalidTransition (handled).
- **Edit-write reuse:** the Telegram edit path stores pending edit then applies free text — the web collapses this to one form. Must locate the actual metadata-write and reuse it, not reimplement; if it's entangled in `text_handlers`, extract a small pure `apply_metadata_edit(video_id, fields)` and have BOTH call it (DRY refactor, note in journal).
- **Coexistence:** web + Telegram both driving decisions on the same video — last write wins; `assert_transition` prevents inconsistent double-transitions.
