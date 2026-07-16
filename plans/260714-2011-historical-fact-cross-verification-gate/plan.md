---
title: Historical fact cross-verification gate (flag-only)
description: ''
status: completed
priority: P2
branch: feat/ops-observability-validation
tags: []
blockedBy: []
blocks: []
created: '2026-07-14T13:17:51.516Z'
createdBy: 'ck:plan'
source: skill
---

# Historical fact cross-verification gate (flag-only)

## Overview

`research_gate` (`src/ai_operator/content/research_gate.py`) is the only fact control
today, and it is **self-attestation**: it asks the LLM to name sources and set
`verified: true` per citation, with no independent check. A citation can look real
("The National Archives, ref MT 9/1326") and be fabricated, or carry a wrong date/number.

This plan adds a SECOND, INDEPENDENT gate that runs after `research_gate` and cross-checks
each citation against outside evidence, then annotates `script.json` with a per-citation
verdict. It is **flag-only** — it never fails the video. The existing human review gate
(video stops at `rendered`/`pending_review`) stays the decision point; this gate just gives
the human a machine-checked confidence signal to read before approving.

Two independent checks per citation:
- **Wikipedia cross-check** (Phase 1): confirm the entity/event exists and key dates/numbers
  in the claim match a real Wikipedia article — the cheap, deterministic layer.
- **Adversarial LLM verify** (Phase 2): a second LLM plays skeptic over the citations, hunting
  claims unsupported by their stated source or numbers that smell fabricated — catches what a
  keyword match can't.

Phase 3 merges both verdicts into `script.json` and surfaces them for the human reviewer.

## Design decisions (user-confirmed)

- **Flag-only, never block.** Verdicts are written to `script.json`; the pipeline never fails
  on them. `research_gate`'s existing fail-closed reject is untouched. Rationale: Wikipedia has
  gaps and entity names drift, so a hard reject would kill true claims (false negatives). The
  human gate already exists as the real decision point.
- **Scope = Tier 1 + Tier 2.** Wikipedia cross-check AND adversarial LLM. No new web-UI panel
  this round (verdicts live in `script.json`; a later plan can surface them on the control panel).

## Non-goals

- No hard reject / auto-fail on verification (flag-only by decision above).
- No Wikidata SPARQL / paid fact-check API (YAGNI at current scale).
- No web control-panel verification view (deferred to a follow-up plan).
- No re-verification of shorts — a short reuses its parent's already-verified citations and
  invents no new claims (`short_script_generator` rule 5), so the parent's verdicts cover it.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Wikipedia cross-check](./phase-01-wikipedia-cross-check.md) | Completed |
| 2 | [Adversarial LLM verify](./phase-02-adversarial-llm-verify.md) | Completed |
| 3 | [Integrate and flag](./phase-03-integrate-and-flag.md) | Completed |

## Validation Log

### Session 1 (2026-07-14)

Verification pass (Standard tier, 3 phases) — all plan claims VERIFIED against codebase:
`review_notifier.notify`, `script_generator.generate/_persist` + citations flow
(`script_generator.py:68,121,160`), `stock_clients` session/retry symbols, config bool-flag
pattern (`DISABLED_VISUAL_SOURCES`). Wikipedia extracts API live-checked: `prop=extracts&
explaintext=1` returns a 1180-char extract for "RMS Lusitania" — Phase 1's core assumption holds.
No FAILED claims.

Decisions confirmed:
- **Entity extraction = simple regex** (first capitalized phrase / quoted title), retry on the
  bare entity when the full claim over-narrows. No per-claim LLM entity extraction. Bias toward
  `unconfirmed` on ambiguous claims is acceptable (flag-only).
- **`confirmed` rule = MAJORITY of facts match** (not every fact). Entity present + majority of
  extracted dates/numbers found → `confirmed`; a directly contradicting date/number → `conflict`;
  otherwise `unconfirmed`. Avoids false `unconfirmed` on multi-number claims.
- **Skeptic runs on `DEFAULT_ANTHROPIC_MODEL` (Opus 4.8) with an adversarial prompt** — independence
  comes from prompt inversion, not a separate model. `FACT_SKEPTIC_MODEL` is DROPPED from scope.

## Dependencies

- Reuses `_CachedLimiterSession` + `User-Agent`/retry pattern from
  `src/ai_operator/media/stock_clients.py` (Wikipedia API is a sibling of the Commons API
  already called there).
- Reuses `llm_client.complete()` + `parse_json()` for the adversarial pass (same as
  `research_gate`).
- Hooks into `src/ai_operator/content/script_generator.py` right after the `research()` call.
- No cross-plan blockers (checked unfinished plans in `plans/` — no overlap; the auto-shorts
  plan is complete and this gate sits upstream of it).
