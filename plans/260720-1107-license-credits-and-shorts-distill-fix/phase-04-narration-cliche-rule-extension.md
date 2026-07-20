# Phase 04 — Narration cliché rule extension (optional)

## Context Links

- Prompt to edit: `prompts/script_system.md` (261 lines; "Non-negotiable rules" block, rule 3 at :21-25)
- Only consumer of that file: `src/ai_operator/content/prompt_builder.py:12` (`_SYSTEM_PATH`), loaded by `load_system_prompt()` at :18-19
- Evidence corpus: `output/<id>/script.json` → `narration` field, 11 long-form scripts (ids 1-9, 28, 35)
- Long-form video ids + creation order: `sqlite3 "file:data/operator.db?mode=ro" -header "select id,kind,created_at,duration_sec,title from videos where kind='main' order by created_at;"`

## Overview

- **Priority:** P2 — **OPTIONAL. Defer if time-constrained.** Nothing breaks if this is never done; it is a prose-quality nit, not a correctness or policy issue.
- **Status:** not started.
- **Description:** Extend the existing banned-cliché rule in `prompts/script_system.md` so the ban covers the whole narration (not just the opening) and names two recurring tics: the "not just X, but Y" family and the "the system / history forgot" closing move. Prompt-text change only — 0 lines of Python, no test, no re-render, no DB coupling.

## Key Insights

1. **The literal ban already works.** Rule 3 lists 7 banned opening strings (`prompts/script_system.md:21-25`). Checked all 11 long-form narrations: zero of the 7 strings appear **anywhere** in any narration, let alone at the start. So a literal, enumerated ban is empirically honored by the model. This is the whole reason the proposed fix is cheap and likely to work.

2. **CORRECTION to the briefing — the evidence is NOT stale.** The briefing said the three newest mains close concretely and that 8 of ~12 "not just X, but Y" occurrences sit in the two oldest scripts, implying "already fixed, defer". Measured on the actual corpus:
   - Strict form (`not just/simply/merely/only … but`): **7 occurrences** across 4 scripts (ids 2, 4, 5, 7), 5 of them in `output/2` and `output/4`. Dropping the `but` requirement gives 13 across 6 scripts. That half of the briefing broadly holds.
   - Including the contracted form (`didn't just X`, `wasn't just X`, `isn't just X`): **17 occurrences**, and the three newest long-forms by `videos.created_at` (id 9 → 2026-07-10, id 28 → 2026-07-14, id 35 → 2026-07-17) each still contain it: `output/9` "didn't just sink a ship on the East River in 1904", `output/28` "didn't just leak", `output/35` "not simply how a dam broke" + "not just water".
   - In `output/9` the construction is in the **closing sentence itself**. The tic did not disappear; it changed register into a contraction the strict regex missed.

3. **10 of 11 long-form scripts close on the same rhetorical move** — an abstraction about a system or about history forgetting. Closing clauses (verbatim fragments from the closing paragraph — for ids 6, 7 and 8 the quoted string sits at ~95% of the narration with one further sentence after it, not as the literal last clause):
   - id 1: "erased by history's crueler current of news"
   - id 2: "the silence that protected the atomic bomb ultimately condemned the men who delivered it"
   - id 3: "a system willing to let two ordinary ships meet in a channel with no room left for mistakes"
   - id 4: "the greatest dangers lie not in the grand, obvious failures, but in the small, unsealed gaps that humanity leaves behind"
   - id 5: "how the sheer momentum of a world at war can erase the memory of its own most devastating moments"
   - id 6: "how a government's instinct to manage a story can outlast the war it was meant to serve"
   - id 7: "the most profound lessons are those history decides to forget"
   - id 8: "a failure of the imagination required to ask what a fix actually does to the whole system it's added to"
   - id 9: "never counted among the disaster's casualties — though it should have been"
   - id 35: "a monument to how quietly a disaster assembles itself, one reasonable decision at a time"
   - id 28 is the **only** clean close: "whether the door was the whole story, or only the part of it that happened to be visible first."
   Newer scripts are more *concrete on the surface* (a named object, a number) but still land the same abstraction. The move is body-and-ending-wide, so an opening-scoped rule cannot reach it.

4. **Rule 3 is opening-scoped by construction:** "never start the hook or narration with any of" (`prompts/script_system.md:21`). Both tics occur mid-body and at the close. Scope must be widened to "anywhere in the narration or in any hook variant".

5. **Rejected alternative — dynamic ban list.** Feeding prior videos' closing sentences into the prompt as a grow-with-every-video ban list is rejected: (a) it pastes examples of the exact prose you don't want into the same turn that asks for prose, and in-context anchoring reliably produces near-miss variants that dodge the literal ban; (b) the list grows monotonically forever, eating prompt budget; (c) it couples script generation to the DB / to `output/`, which the current generator does not touch at all. Static enumeration is the KISS option and is already proven to work (insight 1).

6. **Adjacent finding — DO NOT act on it in this phase.** `DEFAULT_WORD_TARGET = 1800` (`src/ai_operator/content/prompt_builder.py:15`) but delivered narrations run **1025-1497 words** (min id 7 = 1025, max id 35 = 1497) — every long-form undershoots by 17-43%, while rule 4 (`:26-27`) demands "within about 10%". Consequence: 9 of the 10 long-forms with a recorded `duration_sec` land in a 439-469s band (only id 35 breaks out, at 533s). Whether to lower the target, split the ask, or vary structure is a separate operator decision. Do not change the number here.

## Requirements

Functional:
- R1. The banned-cliché rule must apply to the entire narration and to all hook variants, not only to the first sentence.
- R2. The rule must name the "not just X, but Y" family explicitly, including contracted and near variants: `not just`, `not simply`, `not merely`, `not only`, `didn't just`, `wasn't just`, `isn't just`, and `… but rather …`.
- R3. The rule must name the closing move to avoid: ending on an abstraction about a system, an institution, or history forgetting/erasing/burying the event.
- R4. The rule must say what to do instead, not only what to avoid — otherwise the model substitutes a different abstraction. Prescribe: end on a concrete, physical, checkable image or fact tied to this specific event (an object that still exists, a number, a person's last recorded action, an unanswered question of fact).

Non-functional:
- R5. Prompt-only. No Python change, no schema change, no test, no re-render of existing videos.
- R6. Keep the addition short (~8-12 lines). `prompts/script_system.md` is already 261 lines; every added line competes for attention with the retention-architecture rules further down.
- R7. No plan/phase references inside the prompt file text.

## Architecture

No architecture change. `prompt_builder.load_system_prompt()` reads `prompts/script_system.md` verbatim at generation time (`src/ai_operator/content/prompt_builder.py:12,18-19`); the wording is deliberately kept out of code (module docstring, :1-6). Editing the markdown is the entire deployment mechanism — the next generated script picks it up, previously generated scripts are untouched.

```
prompts/script_system.md  ──read──▶  load_system_prompt()  ──▶  LLM system turn
        (edit here)                   prompt_builder.py:18
```

## Related Code Files

Modify:
- `prompts/script_system.md` — rule 3 (:21-25) only.

Create: none.

Delete: none.

Explicitly NOT touched: `src/ai_operator/content/prompt_builder.py`, `tests/`, `data/operator.db`, `output/`.

## Implementation Steps

1. Open `prompts/script_system.md` and locate rule 3 under `## Non-negotiable rules` (currently :21-25, header `3. **Banned opening clichés**`).
2. Rename the rule to drop "opening" — e.g. `3. **Banned clichés (anywhere in the script)**` — and change the lead-in from "never start the hook or narration with any of" to wording that binds the whole narration and every hook variant.
3. Keep all 7 existing banned strings verbatim. They are proven-honored; do not reword or trim them.
4. Add a second sub-bullet for the construction ban: forbid "not just X, but Y" and its family — `not simply`, `not merely`, `not only`, and the contracted `didn't just / wasn't just / isn't just X — it Y`, plus `… but rather …`. Say it may appear **at most once in the whole script**, or ban it outright; prefer the outright ban, since 17 occurrences across 11 scripts means the model reaches for it by default and a quota invites one per script.
5. Add a third sub-bullet for the closing move: the final paragraph must not generalise to "the system failed", "the institution looked away", or "history forgot / erased / buried" this event. Give the positive instruction from R4 (end on a concrete object, number, person, or open question of fact) and one short example of a good close in the abstract (do **not** paste real closing sentences from `output/*` — that is the rejected dynamic-ban-list failure mode in miniature).
6. Re-read the edited rule alongside the "Retention architecture" section further down the same file to confirm the new ending instruction does not contradict the existing ending guidance there. If it does, adjust the new wording, not the existing section.
7. Done. Do not run the pipeline, do not re-render, do not add a test.

## Todo List

- [ ] Read `prompts/script_system.md:21-25` and the ending guidance in the "Retention architecture" section
- [ ] Rewrite rule 3 header + lead-in to be script-wide instead of opening-scoped
- [ ] Preserve the 7 existing banned strings verbatim
- [ ] Add the "not just X, but Y" family ban (incl. contracted forms)
- [ ] Add the closing-move ban + positive instruction for what to end on
- [ ] Check for contradiction with the retention/ending section
- [ ] Confirm no Python, test, prompt-template, or DB file was touched (`git status`)

## Success Criteria

- `git diff --stat` shows exactly one changed file: `prompts/script_system.md`.
- The edited rule contains no plan/phase/finding references (project rule).
- Rule 3 no longer contains the word "start"/"opening" as its scope limiter.
- All 7 original banned strings still present.
- File growth ≤ ~12 lines.
- Deferred validation (next natural long-form render, not part of this phase): the new narration contains zero `not just/simply/merely/only` and zero `didn't|wasn't|isn't just`, and its final sentence names a concrete object, number, person, or factual question. Reuse the check by scanning `output/<new_id>/script.json` → `narration`.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Model substitutes a *different* stock abstraction for the banned one (whack-a-mole) | Medium | Low | The positive instruction (R4) is the real lever; a pure ban is known to just displace the tic. If it recurs with a new phrase, that is a future one-line addition, not a redesign. |
| Prompt bloat dilutes the higher-value retention rules further down the file | Low-Medium | Medium | Cap the addition at ~12 lines; fold into the existing rule 3 rather than adding a new numbered rule. |
| Over-constraining the ending makes closes feel abrupt or listy | Low | Medium | Instruct on what to end *on*, not just what to avoid; do not mandate sentence count or length. |
| Someone treats this as blocking | — | — | Status is optional; ship phases 01-03 first. |
| Regression is invisible until a fresh render | High | Low | Accepted. No re-render is in scope; the check is deferred to the next natural render. |

## Security Considerations

None. Prompt-text edit to a file already loaded verbatim from disk (`src/ai_operator/content/prompt_builder.py:12`). No new inputs, no user-supplied data, no credentials, no network, no DB access, no filesystem writes outside the repo. No change to what is uploaded or to the synthetic-media disclosure path.

## Next Steps

- Independent of phases 01-03 in this plan; do it last or not at all.
- Follow-up requiring operator input (do not decide unilaterally): the `DEFAULT_WORD_TARGET = 1800` vs 1025-1497 delivered-words gap, and the resulting 439-469s duration clustering (Key Insight 6). Options are lower the target to match reality, or keep it and find why generation stops short — both change output length, so the operator picks.
- If the next long-form still closes on a system/history abstraction after this edit, the next lever is the narrative-pattern templates in `prompts/script_templates/`, not another line in `script_system.md`.

## Unresolved Questions

1. Outright ban on "not just X, but Y" vs "at most once per script"? Recommendation: outright — 17 occurrences in 11 scripts shows it is the default reach, and a quota reads as permission.
2. Should the rule also cover shorts narration, or long-form only? Shorts are distilled from the main script, so the tic can be inherited; not investigated in this phase.
3. Briefing assumed the newest scripts were already clean and this could be deferred on staleness grounds. That assumption is false (Key Insight 2), but the phase is still marked optional on *value* grounds, not evidence grounds. Confirm that framing is what the operator wants.
