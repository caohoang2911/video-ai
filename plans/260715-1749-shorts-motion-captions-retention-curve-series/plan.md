# Shorts Uplift: Motion, Dynamic Captions, Retention Curve, Series Packaging

Date: 2026-07-15 | Branch: feat/ops-observability-validation | Status: DONE (implemented + reviewed + 366 tests green, 2026-07-15)

## Context

External advisor feedback (2 rounds) cross-checked against codebase + internal research
(`plans/reports/research-260714-1640-shorts-hook-format-curiosity-ending-report.md`).

Verdict on advice:
- Effect-first hook + doubt/verification format: ALREADY DONE (`short_script_generator.py:50-55`).
  Formula auto-applies to every future topic (Titanic, Hindenburg...) — no work needed.
- Curiosity CTA: already stronger than advised (open-question validator, `short_schema.py:54-59`). No change.
- "Analyze which second viewers respond to": NOT POSSIBLE today — pipeline only pulls aggregate
  `averageViewPercentage` (`analytics_puller.py:23`). Real gap → Phase 3.
- "Make visuals more alive": Ken Burns exists but zoom-only, no pan, gentle amplitude on shorts,
  and long-form beats >8.3s freeze at MAX_ZOOM cap. Real gap → Phase 1.
- "Dynamic text matching narration pace": captions are segment-level static blocks
  (`caption_whisper.py:35`, word_timestamps=False). Real gap → Phase 2.
- "Mini-series 3 shorts/3 angles": structurally exists (batch shorts per parent, Halifax trio).
  Only packaging deltas remain → Phase 4 (optional, low priority).

## Phases

| # | Phase | Impact | Effort | Status |
|---|-------|--------|--------|--------|
| 1 | [Ken Burns motion upgrade](phase-01-kenburns-motion-upgrade.md) | High (every video) | S | done |
| 2 | [Word-level karaoke captions + beat-boundary cuts](phase-02-word-level-karaoke-captions-and-beat-sync.md) | High (shorts retention) | M | done |
| 3 | [Retention curve ingestion + view](phase-03-retention-curve-ingestion-and-view.md) | Medium (closes data loop) | S-M | done |
| 4 | [Sibling shorts cross-linking + spacing](phase-04-sibling-shorts-cross-linking-and-spacing.md) | Low-Medium | S | done |

Order: 1 → 2 → 3 → 4. Phases 1+3 independent, can parallelize. Phase 2 builds on Phase 1 output paths.

## Explicitly NOT doing (YAGNI)

- No playlist automation for series (Shorts shelf ignores playlists).
- No "Part N" titles (hurts standalone click-through on feed-served shorts).
- No CTA wording change (current open-question contract beats advisor's yes/no example).
- No script format work (G1/G2 shipped; G5 length A/B blocked on Phase 3 data).

## Manual ops (not code — do alongside)

- Set Related video link → parent on each published short (Studio, not settable via Data API).
- Pinned comment with parent link per short. Highest-leverage funnel steps per research report.

## Key dependencies

- Phase 3 needs YouTube Analytics API scope already granted (verify `yt-analytics.readonly` in token).
- Retention curves need view volume; low-view shorts return sparse/no curve rows — handle gracefully.
