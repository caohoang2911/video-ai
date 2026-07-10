---
phase: 2
title: "Short Script Generator"
status: completed
priority: P1
effort: "5h"
dependencies: [1]
---

# Phase 2: Short Script Generator

## Overview
An LLM step that turns a main video's `script.json` into 2-3 self-contained ~30-45s short
scripts, each ending on a curiosity-gap question that drives search to the full video without
spoiling it.

## Requirements
- Functional: `generate_short_scripts(parent_script: dict, n: int) -> list[ShortScript]` returns
  2-3 validated shorts; each has punchy narration (~75-110 words), an on-screen hook line, 3-5
  visual beats (keywords to reuse parent assets), a closing curiosity question, and hashtags.
- Non-functional: reuse the existing LLM client + prompt conventions from `content/script_generator`;
  validate via pydantic (anti-slop, like `ScriptOutput`); no network in tests (client mocked).

## Architecture
- New pydantic `ShortScript` (looser than `ScriptOutput`): `narration`, `text_overlay` (hook),
  `beats: list[{keywords, mood}]` (3-5, to map parent `Asset`s), `curiosity_question`,
  `title`, `hashtags`. Small + self-contained so the vertical builder (Phase 3) reads it directly.
- Prompt inputs from parent `script.json`: `payoff_nodes` sorted by `surprise_score` desc (pick
  the genuine twists), `citations`/`sources` (facts must stay verified — no new hallucinated
  claims), `hooks`, `title_options`. Output N shorts, each built around a distinct top payoff.
- **Curiosity-gap contract (the make-or-break, user-confirmed reveal level):** narration delivers
  **exactly one satisfying verified fact**, then **withholds the twist/answer** and closes with an
  open question whose payoff is only in the full video — NOT a bare teaser (no fact) and NOT a
  near-full reveal (spoiler). Encode in the prompt + a validator that rejects a short whose
  `curiosity_question` is empty or is a statement (must end with "?").
- English (channel language). ~40s ≈ ~600 chars → re-TTS cost is negligible vs the 100k/mo quota.

## Related Code Files
- Create: `src/ai_operator/content/short_script_generator.py` — `generate_short_scripts(...)`.
- Create: `src/ai_operator/content/short_schema.py` — `ShortScript` pydantic model.
- Reuse: the LLM client/util `content/script_generator` uses (extract a shared `_complete()` if entangled).

## Implementation Steps
1. Define `ShortScript` + validators (curiosity_question non-empty & ends with "?"; narration word
   count 60-130; 3-5 beats).
2. Build the prompt: system = "faceless documentary Shorts editor"; user = distilled parent facts +
   the curiosity-gap rules + "produce N distinct shorts, each around a different high-surprise payoff".
3. Parse LLM JSON → validate each into `ShortScript`; drop invalid, retry once if < 2 valid.
4. Return the list; caller (Phase 4) persists each as a child video + writes its `output/<id>/script.json`.
5. Manual check with a sample parent `script.json` fixture → inspect the 2-3 shorts read sanely.

## Success Criteria
- [ ] Given a real parent `script.json`, returns 2-3 `ShortScript`s, each ending on a `?` curiosity question.
- [ ] Facts come from parent citations/payoffs (no new unverified claims); each short targets a distinct payoff.
- [ ] Narration length lands ~75-110 words (≈30-45s); validator rejects spoiler-y / question-less shorts.
- [ ] Deterministic-enough to test with a mocked LLM response; `< 200` lines per new file.

## Risk Assessment
- **Weak curiosity gaps** = the whole feature underperforms → strict prompt + validator + human
  review gate (Phase 5) as the backstop. Iterate the prompt with real outputs.
- **Hallucinated facts** in a short → constrain to parent citations; validator can flag claims not
  traceable to a source (best-effort; human review catches the rest).
