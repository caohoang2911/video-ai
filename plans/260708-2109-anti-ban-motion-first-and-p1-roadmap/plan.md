---
title: "Anti-ban hardening + motion-first + P1 automation (increment 2)"
description: "Anti-ban/flag improvements (voice consistency, payoff/POV, thumbnail_text, EDSA), motion-first hybrid video pipeline, and P1 automation (scheduler/analytics, observability/deploy, validation) on top of committed phases 01-06."
status: pending
priority: P1
branch: "main"
tags: [python, youtube, anti-ban, tts, moviepy, ffmpeg, scheduler, ai-video]
blockedBy: []
blocks: []
created: "2026-07-08T14:25:02.419Z"
createdBy: "ck:plan"
source: skill
---

# Anti-ban hardening + motion-first + P1 automation (increment 2)

## Overview

Second increment on the `ai_operator` pipeline (base phases 01-06 committed `e90c147`). Hardens the
channel against YouTube's 2026 "inauthentic content" enforcement and completes P1 automation.
Design + research: [brainstorm summary](../reports/brainstorm-summary-260708-2109-anti-ban-improvements-motion-first-and-p1-roadmap-report.md)
(3 research workflows: TTS license, stock-video/motion, YouTube AI-detection). **Supersedes** the
unimplemented phase 07-09 stubs in `../260708-1548-lean-faceless-ai-video-operator-system/`.

**Research reprioritization (key):** YouTube targets *inauthentic/mass-produced/zero-editorial*, not
"video vs stills". Strongest survival signals = consistent brand voice + editorial POV + varied cadence
+ human review. SDXL non-photorealistic images are exempt from detection. Disclosure = zero penalty.
edge-tts = commercial ToS violation (never publish). → Tier A (voice/POV/EDSA) is cheap + high-ROI;
motion-first (item 2) is the biggest build for a medium lever (still worth it: render-time + slideshow-avoidance).

## Locked decisions (user-confirmed 260708-2109)
- **Voice = 1a:** ElevenLabs is the ONLY publishable voice; any fallback → `needs_revoice=True`, publish blocked, re-voice later. edge-tts = draft-only preview (never published). Drop OpenAI from chain.
- **Item 2 = FULL** this round (motion-first hybrid + ffmpeg-subprocess/`h264_videotoolbox` encode).
- Include P1 phases 06-08 (scheduler/analytics, observability/deploy, validation run).
- **ElevenLabs tier = Creator ($22/mo, 100k chars/mo):** at ~15-18k chars per 8-10min narration video,
  100k chars ≈ 5-6 videos/mo of headroom. Char-guard alerts at 70% of quota (~70k chars/mo used) —
  reuse `CostLedger` rows where `provider='elevenlabs'`, summed by `units` (chars) not $ (phase 01).
  Target cadence ~1-1.5 videos/week (~5/mo) is reconciled TO this char budget, not the other way
  round — `WEEKLY_VIDEO_CAP` guidance in phase 06 follows the char ledger, not a standalone number.
  **The ElevenLabs monthly CHARACTER ledger is the hard throttle, not `budget_guard`'s USD cap:**
  ElevenLabs spend at this cadence (~30k-90k chars ≈ $9-27/mo) never approaches the $500 `budget_guard`
  ceiling, so the existing $ cap alone cannot catch the char wall — a dedicated char-quota guard is
  required (phase 01), and phase 06's publish/produce jobs must skip + alert (not silently over-flag)
  once the char quota is exhausted.

## Sequencing gate

Before Phase 5's rewrite begins: obtain live API keys (populate `.env`) and run ONE real video
end-to-end through the existing, never-yet-executed 01-06 CLI — `gen-script → gen-audio →
gen-visuals --stills-only → assemble → notify-review → publish` (publish to a private/unlisted test
upload). This proves the committed base pipeline actually works before ~20-37h of increment-2 work
is built on top of it. Phase 5a (ffmpeg encode refactor, deps: []) may start once this one real
render exists and is buildable on the current stills path; Phase 5b (motion b-roll, deps: [4]) and
everything downstream waits for it.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Voice consistency + revoice gate](./phase-01-voice-consistency-revoice-gate.md) | Done |
| 2 | [Content quality gates](./phase-02-content-quality-gates.md) | Done |
| 3 | [EDSA review checklist](./phase-03-edsa-review-checklist.md) | Done |
| 4 | [Motion-first b-roll sourcing](./phase-04-motion-first-b-roll-sourcing.md) | Done (live-API E2E gated) |
| 5 | [Hybrid assembler + ffmpeg encode](./phase-05-hybrid-assembler-ffmpeg-encode.md) | 5a done (ffmpeg encode ~10x faster) · 5b pending (motion assembly) |
| 6 | [Scheduler + analytics loop](./phase-06-scheduler-analytics-loop.md) | Pending |
| 7 | [Observability + deploy](./phase-07-observability-deploy.md) | Pending |
| 8 | [Validation run + kill-criteria](./phase-08-validation-run-kill-criteria.md) | Pending |

## Dependency graph
```
1 (voice) ─┬─► 3 (EDSA, needs needs_revoice)
2 (content)┤
5a (encode refactor, deps: []) ──────────────┐
4 (sourcing) ─► 5b (motion assembly, deps: 4,5a) ┤
                                              ├─► 6 (scheduler) ─► 7 (obs/deploy)
1,2,3 ────────────────────────────────────────┘                └─► 8 (validation)
```
Tier A = phases 1-3 (cheap, high anti-ban ROI). Item 2 = phases 4-5 (5a encode refactor, deps: [];
5b motion assembly, deps: [4]). P1 automation = phases 6-8.
Phases 1,2,4 are independent (parallelizable). Most new logic ships **key-free** pytest unit tests
under `tests/` (schema round-trips, state-gating, SRT/fps invariants via ffprobe fixtures, scheduler
throttle+jitter with a frozen clock, validation thresholds at boundaries) — only true end-to-end runs
against real ElevenLabs/stock-video/YouTube APIs are gated on phase-00 keys.

## Global constraints (every phase)
- Package `ai_operator` (src layout); each phase package exposes `commands.py` with `register(app)` (cli.py auto-mounts).
- Files <200 lines; comments explain WHY, never reference phase/finding codes.
- Every paid API call: `budget_guard.check_and_reserve` before + `record_actual` after.
- State moves via `assert_transition` with the idempotent guard pattern (`if state != target:`).
- Foundation interface + verified API signatures: see `../260708-1548-.../reports/researcher-260708-1704-version-sensitive-api-implementation-reference-report.md`.
- Schema change (`Video.needs_revoice`) on a fresh dev DB → delete `data/operator.db` + re-`init-db` (no real data yet).
- `output/<id>/` retention: intermediate working files (normalized b-roll copies, per-beat segments,
  base/body intermediates) are deleted immediately after a successful final encode; the whole
  `output/<id>/` working tree is pruned once a video reaches `published` (keep `final.mp4` or archive
  off-disk first). See phase 05/07.

## Dependencies
- Builds on committed base pipeline (phases 01-06, `e90c147`). No external plan blocks.
- Supersedes phase 07/08/09 stubs in `260708-1548-lean-faceless-ai-video-operator-system` (those remain as historical reference).
