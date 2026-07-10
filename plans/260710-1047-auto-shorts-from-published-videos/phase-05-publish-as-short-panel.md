---
phase: 5
title: "Publish-as-Short & Panel"
status: completed
priority: P2
effort: "4h"
dependencies: [4]
---

# Phase 5: Publish-as-Short & Panel

## Overview
Make an approved short publishable as a real YouTube Short (vertical + `#Shorts` + parent-video
link for the funnel), and surface shorts in the web panel (kind badge/filter + parent↔children
links). Publishing stays behind the human review gate — never automatic.

## Requirements
- Functional: approving a short and publishing it uploads a vertical video whose description
  carries `#Shorts` + a link to the parent video; the panel shows which videos are shorts and
  links a short to its parent (and a main to its shorts).
- Non-functional: reuse `publisher.publish` + `metadata_builder`; **no auto-publish** — a short
  only uploads after the same `record_decision` approval a main needs.

## Architecture
- **Publish metadata variant:** in `metadata_builder.build_upload_body` (or a thin wrapper), when
  `video.kind == "short"`: prepend/append `#Shorts` + `▶ Full video: https://youtu.be/<parent_yt_id>`
  + the curiosity line to the description; keep title punchy. Vertical + ≤60s → YouTube auto-classifies
  as a Short (no special API flag needed). Parent's `youtube_video_id` comes from the parent `Upload`.
- **Publish flow reuse:** `publish(video_id)` already gates on state/approval; it just needs the
  kind-aware body. No separate publish path.
- **Web panel:** `/videos` list gains a `kind` badge + a `?kind=short|main` filter; the video detail
  shows `parent_id` link (for a short) and a "Shorts (N)" list (for a main). Small template/route edits.
- **"Regenerate Shorts" button (user-confirmed):** on a *main* video's detail, a
  `POST /videos/{id}/regenerate-shorts` enqueues `gen-shorts` with `params={"force": true}` →
  the runner discards the parent's non-published shorts and re-rolls a fresh batch (for a weak
  batch). Reuses the existing enqueue/`action_result` pattern; shown only for `kind="main"`.

## Related Code Files
- Modify: `src/ai_operator/publisher/metadata_builder.py` — kind-aware description (`#Shorts` + parent link).
- Modify: `src/ai_operator/publisher/publish.py` — pass `kind`/parent context into the body builder.
- Modify: `src/ai_operator/web/routes_videos.py` — `kind` badge/filter + parent/children in detail context.
- Modify: `src/ai_operator/web/routes_actions.py` — `POST /videos/{id}/regenerate-shorts` (enqueue gen-shorts force).
- Modify: `src/ai_operator/web/templates/videos.html`, `video_detail.html` — render kind + parent/children links + Regenerate button.

## Implementation Steps
1. `metadata_builder`: add `kind`/`parent_youtube_id` params; build the shorts description block
   (hashtags stay last per the existing test; parent link + `#Shorts` sit above them).
2. `publish`: resolve the parent's `youtube_video_id` (via parent `Upload`) and pass kind context.
3. Panel: add `kind` filter to `/videos`; show parent link on a short's detail + a shorts list on a main's.
4. Manual: approve a seeded short → dry-run `build_upload_body` → assert `#Shorts` + parent URL present.

## Success Criteria
- [ ] An approved short's upload body contains `#Shorts` + a working parent-video link; hashtags stay last.
- [ ] A short is uploaded ONLY after human approval (same gate as mains) — verified no auto-publish path exists.
- [ ] `/videos` filters by kind and shows a badge; a short links to its parent and a main lists its shorts.
- [ ] Main-video upload metadata is unchanged (kind defaults to main).

## Risk Assessment
- **Parent not yet published** when a short is approved → the parent link would be dead; guard:
  only allow short publish once the parent has a `youtube_video_id` (else show "parent not live yet").
- **YouTube Shorts classification** is heuristic (vertical + short) — no API guarantee; `#Shorts`
  + <60s + 9:16 is the accepted recipe. Documented, not over-engineered.
