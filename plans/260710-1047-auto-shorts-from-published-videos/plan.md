---
title: "Auto-generate vertical Shorts from published main videos"
description: ""
status: completed
priority: P2
branch: "feat/ops-observability-validation"
tags: []
blockedBy: []
blocks: []
created: "2026-07-10T04:08:46.418Z"
createdBy: "ck:plan"
source: skill
---

# Auto-generate vertical Shorts from published main videos

## Overview

Auto-produce **2-3 vertical YouTube Shorts** from each *published* main documentary to funnel
viewers back to the channel. Each short is a **self-contained ~30-45s clip** (fresh punchy
narration built from the main video's researched facts) that **ends on a curiosity-gap
question** so viewers search out the full video — without a cheap cutoff or full spoiler.

**Approach (approved in brainstorm):** a short is a **child `Video` row** (`kind="short"`,
`parent_id`) so it flows through the *existing* state machine, review gate, publish, web panel,
and job queue — near-zero new plumbing (DRY). New pieces: 2 columns, an LLM short-script
generator, a **vertical 1080×1920 render path** (reuses Ken Burns / captions / branding /
ffmpeg), a `gen-shorts` job auto-enqueued after the main publishes, and a publish-as-Short
metadata variant (`#Shorts` + parent link). Re-TTS of a ~40s short ≈ ~600 chars ≈ 0.6% of the
ElevenLabs monthly quota — cheap; parent visual assets are reused (no new sourcing).

Source of truth: `plans/reports/from-brainstorm-to-plan-260710-1047-auto-shorts-from-main-videos-report.md`.

## Key decisions (user-confirmed — do NOT auto-reverse)
- Content: **new self-contained short script + re-TTS** (not a slice of the main narration);
  each ends on a **curiosity-gap question** that satisfies but does not spoiler.
- Render: **re-render vertical 9:16** from assets (not crop the landscape final.mp4).
- Trigger: **auto after the main video is `published`**.
- **Publish: through the human review gate like main videos — NEVER auto-publish** (user memory:
  "no publish without approval"). Shorts land at `pending_review`.
- Count/length: **2-3 shorts/video, ~30-45s** each.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Data Model kind parent](./phase-01-data-model-kind-parent.md) | ✅ Done |
| 2 | [Short Script Generator](./phase-02-short-script-generator.md) | ✅ Done |
| 3 | [Vertical Render Path](./phase-03-vertical-render-path.md) | ✅ Done |
| 4 | [Gen-Shorts Job & Wiring](./phase-04-gen-shorts-job-wiring.md) | ✅ Done |
| 5 | [Publish-as-Short & Panel](./phase-05-publish-as-short-panel.md) | ✅ Done |
| 6 | [Tests & Docs](./phase-06-tests-docs.md) | ✅ Done |

## Dependencies

- **Reuses (not blocked by, all merged/mostly-done):** the pipeline built in
  `plans/260708-1548-lean-faceless-ai-video-operator-system/` (assembler, tts, publisher, state
  machine, review gate) and `plans/260709-1253-web-control-panel-api/` (web panel, job queue).
  This plan *extends* them; no hard `blockedBy`.
- **Runtime dependency (not a code blocker):** end-to-end run needs a *published* main video +
  working YouTube OAuth. Both are currently unavailable (0 published videos; OAuth `invalid_grant`
  pending re-authorize). The capability is built now; it exercises once the channel is live.
- External deps: none new. Re-TTS via existing ElevenLabs path (char-guarded); visuals reuse
  parent `Asset` rows; vertical render via existing ffmpeg.

## Build order rationale

1 (data model) unlocks child-short rows the rest depends on. 2 (script gen) is the content brain,
testable in isolation. 3 (vertical render) is the riskiest new tech (portrait framing) — proven
before wiring. 4 chains 2+3 into a `gen-shorts` job auto-enqueued after publish. 5 makes approved
shorts publishable as real Shorts + visible/filterable in the panel. 6 locks it with tests + docs.
