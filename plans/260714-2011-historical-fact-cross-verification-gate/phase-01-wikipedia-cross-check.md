---
phase: 1
title: Wikipedia cross-check
status: completed
priority: P2
effort: 4-6h
dependencies: []
---

# Phase 1: Wikipedia cross-check

## Overview

A deterministic, free layer that confirms each citation's claim against a real Wikipedia
article: does the entity/event exist, and do the key dates/numbers in the claim match the
article text? Emits a per-citation verdict (`confirmed` / `unconfirmed` / `conflict`).

## Requirements

- Functional:
  - Given a `Citation{claim, source, verified}`, search Wikipedia for the claim's main entity
    and fetch the top article's plain-text extract.
  - Extract candidate dates (years, `DD Month YYYY`) and numbers from the claim; check whether
    they appear in the article extract.
  - Verdict (Validation Session 1): `confirmed` (entity found + a MAJORITY of extracted
    dates/numbers present — not every one), `conflict` (entity found but a claimed year/number
    contradicts the article — a DIFFERENT year/number for the same fact), `unconfirmed` (no
    article, or too few facts matched — NOT a contradiction).
    <!-- Updated: Validation Session 1 - confirmed = majority of facts, not all -->`
- Non-functional:
  - Free (Wikipedia REST/`api.php`, no key), rate-limited + retry like the Commons client.
  - Never raises into the pipeline — any network/parse failure returns `unconfirmed`.
  - Bounded latency: 3-5 citations/video × 1-2 calls each; cache 24h.

## Architecture

New module `src/ai_operator/content/fact_crosscheck.py` (keep < 200 LOC).

```
verdict_for(citation) -> CrossCheckVerdict{status, matched: [str], missing: [str], article: str|None}
  1. entity = _claim_entity(claim)            # first proper-noun phrase / quoted title
  2. article = wiki_client.top_article(entity) # search -> best page -> plain extract
     └─ none -> status="unconfirmed"
  3. facts = _extract_facts(claim)            # years, DD Month YYYY, standalone numbers
  4. for each fact: present in article extract?
     - a year/number for the SAME anchor differs in article -> "conflict" (checked first)
     - MAJORITY present, none contradicted    -> "confirmed"
     - too few present, none contradicted     -> "unconfirmed"
```

Wikipedia access reuses the `stock_clients` session pattern (DRY): a `_CachedLimiterSession`
against `https://en.wikipedia.org/w/api.php` with the same descriptive `User-Agent` and the
429/503 retry helper added in `0b379bb`. Put the thin client in `fact_crosscheck.py` (or a
small `wiki_client.py` if it grows) — do NOT bloat `stock_clients.py`, which is image-tier only.

Number/date matching is intentionally simple string/regex containment, not NLP: goal is to
catch gross fabrication (wrong year, invented casualty count), not to parse prose. Over-matching
toward `unconfirmed` is acceptable — Phase 2 (LLM skeptic) and the human gate are the safety net.

## Related Code Files

- Create: `src/ai_operator/content/fact_crosscheck.py`
- Create: `tests/test_fact_crosscheck.py`
- Read for pattern: `src/ai_operator/media/stock_clients.py` (`_CachedLimiterSession`,
  `_retry_after_seconds`, `search_wikimedia_commons`)
- Read for schema: `src/ai_operator/content/schema.py` (`Citation`)

## Implementation Steps

1. Add a Wikipedia search+extract helper: `api.php?action=query&generator=search&prop=extracts&
   explaintext=1&exintro=0` (or REST `/page/summary`); return plain-text extract of the best hit.
   Reuse the cached-limiter session + UA + retry-on-429/503 pattern.
2. `_claim_entity(claim)` — take the first capitalized multi-word phrase or a quoted title as the
   search entity (e.g. "RMS Lusitania", "Halifax Explosion").
3. `_extract_facts(claim)` — regex out 4-digit years, `DD Month YYYY`, and standalone integers
   (strip commas). Keep a small ignore-list for non-fact numbers if needed.
4. `verdict_for(citation)` — orchestrate per the Architecture pseudocode; return the dataclass.
5. `crosscheck_citations(citations) -> list[CrossCheckVerdict]` batch wrapper (dedup identical
   entities across citations to save calls).
6. Tests with mocked `wiki_client` (no live network in tests): confirmed / conflict / unconfirmed
   / no-article / network-error-returns-unconfirmed. One optional live smoke test marked to skip
   in CI.

## Success Criteria

- [ ] `verdict_for` returns `confirmed` for a Lusitania claim when a MAJORITY of its dates/numbers
      (incl. year 1915) appear in the mocked article — one missing minor number does NOT drop it.
- [ ] Returns `conflict` when the claim says 1916 but the article says 1915 (conflict wins over majority).
- [ ] Returns `unconfirmed` (not raise) on network error / missing article.
- [ ] No live network call in the unit tests; Wikipedia client mocked.
- [ ] Module < 200 LOC; reuses `stock_clients` session/retry pattern (no duplication).

## Risk Assessment

- **False `unconfirmed` (Wikipedia gap / entity name mismatch).** Acceptable by design —
  flag-only, and Phase 2 + human gate catch the rest. Mitigate by anchoring search on the claim's
  proper noun, and retrying search on the bare entity if the full claim over-narrows (mirrors the
  archival anchor-retry lesson).
- **Number matching false `conflict`.** A number appearing in a different context could look like a
  contradiction. Mitigate: only flag `conflict` when a date/number is clearly the SAME fact anchor
  (same surrounding noun); when unsure, downgrade to `unconfirmed`, never `conflict`. Bias toward
  under-claiming conflict.
- **Wikipedia rate limits.** Same 429 risk as Commons; the shared retry helper covers it.
