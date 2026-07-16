---
phase: 2
title: Adversarial LLM verify
status: completed
priority: P2
effort: 3-4h
dependencies:
  - 1
---

# Phase 2: Adversarial LLM verify

## Overview

A second LLM plays skeptic over the citations `research_gate` produced, hunting for claims not
actually supported by their stated source and numbers/dates that smell fabricated. This catches
what keyword matching (Phase 1) cannot: plausible-but-unsupported reasoning, over-precise figures,
and source-claim mismatch.

## Requirements

- Functional:
  - Input: the topic, angle, and the list of `Citation{claim, source, verified}`.
  - Output per citation: a skeptic verdict `supported` / `doubtful` / `unsupported` + a one-line
    reason. Kept independent of Phase 1's verdict (they're merged in Phase 3).
  - The skeptic is prompted to DEFAULT TO DOUBT on uncertainty and to flag any citation whose
    `source` would not plausibly contain the `claim`.
- Non-functional:
  - One `llm_client.complete()` call per video (batch all citations in a single prompt),
    ~1.5k tokens — cheap (~$0.02 on Opus 4.8).
  - Never raises into the pipeline; on LLM/parse failure every citation defaults to `doubtful`
    (fail-open to a cautious flag, never blocks — consistent with the flag-only decision).
  - Must NOT reuse the same reasoning that wrote the citations — a distinct, adversarial skeptic
    system prompt. Runs on `DEFAULT_ANTHROPIC_MODEL` (Opus 4.8); independence comes from the prompt
    inversion, not a separate model (Validation Session 1 — `FACT_SKEPTIC_MODEL` dropped).

## Architecture

Extend `fact_crosscheck.py` (or a sibling `fact_skeptic.py` if it pushes the file over ~200 LOC):

```
skeptic_verdicts(topic, angle, citations) -> list[SkepticVerdict{status, reason}]
  prompt = _SKEPTIC_SYSTEM  # "You are a hostile fact-checker. For each claim, decide whether the
                            #  NAMED SOURCE would actually contain it. Default to doubt. Flag
                            #  invented-looking specifics (oddly precise counts, unverifiable refs)."
  raw = complete(_SKEPTIC_SYSTEM, _format_citations(citations), max_tokens=1200, step="fact_skeptic")
  data = parse_json(raw)   # {"verdicts":[{"index":int,"status":str,"reason":str}, ...]}
  -> align back to citations by index; missing index -> "doubtful"
```

Reuses `llm_client.complete()` + `parse_json()` (DRY with `research_gate`) on the default model.
The skeptic prompt is adversarial by construction — it is rewarded for finding holes, the inverse
of `research_gate`'s "list credible sources" framing, so the two are genuinely independent even on
the same model. No separate model is configured (Validation Session 1): the prompt inversion is the
independence mechanism. If practice later shows same-model bias, a `FACT_SKEPTIC_MODEL` override can
be added then (YAGNI now).
<!-- Updated: Validation Session 1 - skeptic runs on DEFAULT_ANTHROPIC_MODEL, FACT_SKEPTIC_MODEL dropped -->

## Related Code Files

- Create/extend: `src/ai_operator/content/fact_crosscheck.py` (or `fact_skeptic.py`)
- Create: `tests/test_fact_skeptic.py`
- Read for pattern: `src/ai_operator/content/research_gate.py` (`_SYSTEM_PROMPT`, `complete`,
  `parse_json`, JSON-contract handling)
- Read for schema: `src/ai_operator/content/schema.py` (`Citation`)

## Implementation Steps

1. Write `_SKEPTIC_SYSTEM` — adversarial fact-checker persona; explicit "default to doubt",
   "flag source-claim mismatch", "flag invented-looking specifics"; strict minified-JSON output
   contract keyed by citation index.
2. `_format_citations(citations)` — number each citation so the model can reference by index.
3. `skeptic_verdicts(...)` — call `complete()`, `parse_json()`, align verdicts by index, default
   any missing/garbled entry to `doubtful`. Wrap in try/except → all `doubtful` on failure.
4. Tests with `complete` monkeypatched: well-formed skeptic JSON maps correctly; missing index →
   `doubtful`; malformed JSON → all `doubtful` (no raise); index out of range ignored safely.

## Success Criteria

- [ ] `skeptic_verdicts` returns one aligned verdict per input citation.
- [ ] Malformed / partial LLM output degrades to `doubtful`, never raises.
- [ ] Skeptic system prompt is adversarial (distinct from `research_gate`'s sourcing prompt).
- [ ] Exactly one LLM call per video (citations batched, not one call each).
- [ ] Tests mock `complete()` — no live LLM in unit tests.

## Risk Assessment

- **Skeptic hallucinates its own doubt (false `unsupported`).** Flag-only + human gate absorb it;
  the reason string lets the human judge. Keep the prompt asking for a concrete reason per flag so
  a baseless doubt is visible as such.
- **Same-model grading itself.** Mitigated by the adversarial prompt inversion (the decided
  mechanism). If a same-model bias shows up in practice, add a `FACT_SKEPTIC_MODEL` override then —
  not built now (YAGNI).
- **Cost creep.** One batched call per video is negligible; guard against per-citation calls in
  review (the batch contract is the point).
