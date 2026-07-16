---
phase: 3
title: Integrate and flag
status: completed
priority: P2
effort: 3-4h
dependencies:
  - 1
  - 2
---

# Phase 3: Integrate and flag

## Overview

Wire the two checks into the script pipeline right after `research_gate`, merge their verdicts
into a single per-citation confidence signal, persist it in `script.json`, and surface it so the
human reviewer sees it before approving. Flag-only: the pipeline never fails on a verdict.

## Requirements

- Functional:
  - After `research()` returns citations (in `script_generator.generate`), run Phase 1 + Phase 2
    over them and attach a merged verdict to each citation before the script is persisted.
  - Merge rule (per citation): `conflict` (Wikipedia contradiction) OR `unsupported` (skeptic) →
    `fact_status: "review"`; both positive (`confirmed` + `supported`) → `"ok"`; anything else →
    `"weak"`. Store the raw sub-verdicts too for transparency.
  - Persist into `script.json` (extend `Citation` schema with optional cross-check fields).
  - Surface a video-level summary (e.g. `2 ok / 1 weak / 1 review`) where the human sees it:
    the review notification and/or the video-detail page.
- Non-functional:
  - Zero behavior change to the existing fail-closed `research_gate` reject and the payoff gate.
  - Adds one Wikipedia batch + one LLM call per video at script time; both already bounded.
  - Fully skippable via a settings flag (`FACT_CROSSCHECK_ENABLED`, default on) so a Wikipedia
    outage or cost concern can disable the gate without code changes.

## Architecture

```
script_generator.generate():
    research_result = research(...)                      # unchanged (still fail-closed)
    if settings.FACT_CROSSCHECK_ENABLED:
        verdicts = fact_crosscheck.verify(topic, angle, research_result["citations"])
        research_result["citations"] = _merge(research_result["citations"], verdicts)
    ... prompt build / generate / persist ...            # citations now carry fact_status
```

- `fact_crosscheck.verify(...)` is the single public entry: runs `crosscheck_citations` (P1) +
  `skeptic_verdicts` (P2), applies the merge rule, returns citations enriched with
  `fact_status` + `crosscheck` detail. One try/except wrapper → on any failure, log and return
  citations unchanged (gate degrades to invisible, pipeline unaffected).
- `Citation` schema (`content/schema.py`) gains optional fields: `fact_status: Literal["ok",
  "weak","review"] | None`, `crosscheck: dict | None` (raw sub-verdicts). `extra="ignore"` already
  tolerates older scripts without them.
- Human surface (pick the lightest that lands):
  - Minimum: include the `N ok / N weak / N review` summary in the review notification
    (`review/review_notifier.py`) so it rides the existing human gate.
  - Nice-to-have: render per-citation `fact_status` on the video-detail page
    (`web/routes_videos.py` + template) — small, but this is where a reviewer already reads before
    approving. Ship if cheap; otherwise leave `script.json` as the record and defer UI.

## Related Code Files

- Modify: `src/ai_operator/content/script_generator.py` (call `verify` after `research`)
- Modify: `src/ai_operator/content/schema.py` (`Citation` optional fields)
- Create/extend: `src/ai_operator/content/fact_crosscheck.py` (`verify` orchestrator + `_merge`)
- Modify: `src/ai_operator/config.py` (`FACT_CROSSCHECK_ENABLED` only — `FACT_SKEPTIC_MODEL`
  dropped per Validation Session 1)
- Modify (human surface): `src/ai_operator/review/review_notifier.py` and/or
  `src/ai_operator/web/routes_videos.py` + `web/templates/video_detail.html`
- Create: `tests/test_fact_crosscheck_integration.py`
- Read for call site: `src/ai_operator/content/script_generator.py:55-71`

## Implementation Steps

1. Extend `Citation` with optional `fact_status` + `crosscheck`; confirm `script.json` round-trips
   (older scripts without the fields still validate).
2. Implement `verify(topic, angle, citations)` + `_merge(...)` in `fact_crosscheck.py`; wrap in
   try/except → return citations unchanged on failure, with a warning log.
3. Add `FACT_CROSSCHECK_ENABLED` (default `True`) to settings; gate the call in `generate()`.
4. Insert the `verify` call in `script_generator.generate` immediately after the `research()`
   success path; ensure the enriched citations flow into `_persist` (they already go through
   `research_result["citations"]`).
5. Add the human-facing summary to the review notification; optionally the per-citation badge on
   video-detail.
6. Tests: merge rule truth table (ok/weak/review); disabled flag = no-op passthrough; verify()
   swallows P1/P2 failures and returns original citations; `script.json` persists + reloads the new
   fields; end-to-end `generate()` with P1/P2 mocked writes `fact_status` into the script.

## Success Criteria

- [ ] `script.json` citations carry `fact_status` after generation (P1/P2 mocked in tests).
- [ ] Merge rule matches the truth table: conflict/unsupported → `review`, both positive → `ok`,
      else `weak`.
- [ ] `FACT_CROSSCHECK_ENABLED=False` → citations unchanged, zero extra calls.
- [ ] A P1 or P2 failure never fails the video — citations pass through unannotated + a warning logs.
- [ ] `research_gate` fail-closed reject and payoff gate behavior are byte-for-byte unchanged.
- [ ] Human reviewer sees a `N ok / N weak / N review` summary at the review gate.
- [ ] Full test suite green.

## Risk Assessment

- **Scope creep into a hard gate.** Explicitly out of scope — verdicts must stay flag-only. Guard in
  review: no code path may raise/fail based on `fact_status`.
- **Latency at script time.** One Wikipedia batch + one LLM call; both bounded and behind the
  enable flag. If a Wikipedia outage slows scripting, flip `FACT_CROSSCHECK_ENABLED=False`.
- **Schema drift breaking phase 03/04 readers.** New fields are optional with `extra="ignore"`;
  downstream (tts/render/publish) never reads `fact_status`, so it's additive only.
- **Reviewer ignores the flag.** Out of our control, but the summary rides the existing
  notification they already act on — lowest-friction placement.
