# Phase 02 — Shorts distill reveal separation

## Context Links

- `src/ai_operator/content/short_script_generator.py` — `_distill_parent` (:92-119), `_request` (:122-135), `generate_short_scripts` (:138-150), `_SYSTEM` prompt (:27-89)
- `src/ai_operator/ops/shorts_runner.py:72` — the only caller (`SHORTS_PER_VIDEO = 3` at :36)
- `src/ai_operator/publisher/metadata_builder.py:86-109` — `build_short_description` (:93-95) puts `curiosity_question` on the FIRST line of every short's description
- `tests/test_short_script_generator.py` — existing protected-reveal contract tests
- Evidence artifacts: `output/35/script.json` (parent), `output/36|37|38/script.json` (the batch)

## Overview

- **Priority:** P1
- **Status:** not started
- **Description:** Shorts cut from one parent sometimes converge on the same closing question. Root cause is structural, in `_distill_parent`: it protects only `payoffs[0]` and hands `payoffs[1:]` to the generator — including the OTHER half of the same climactic moment. Fix = withhold the whole max-surprise cluster, not just one node. Forward fix only; the two published near-duplicates have 0 views each, no remediation needed.

## Key Insights

All verified against live code/artifacts on 2026-07-20.

1. **The convergence is real and measurable.** Pairwise difflib ratio on `curiosity_question` for parent 35's batch (videos 36/37/38): 36↔37 = 0.89, 36↔38 = 0.85, 37↔38 = 0.74. Questions:
   - 36: "What did William Mulholland conclude when he inspected the dam that morning?"
   - 37: "What did Mulholland decide when he inspected the dam that morning?"
   - 38: "What did William Mulholland conclude when he studied the St. Francis Dam that morning?"
2. **It is occasional, not systemic.** Same measurement on every other batch on disk: parent 3 → 0.21-0.32, parent 5 → 0.24-0.51, parent 6 → 0.44-0.56, parent 9 → 0.19-0.32, parent 28 → 0.26-0.32. Only parent 35 is pathological.
3. **Root cause CONFIRMED.** `output/35/script.json` `payoff_nodes` has TWO nodes at `surprise_score: 5`:
   - `"Chief engineer personally cleared the dam 12 hours before it killed 400+"`
   - `"Muddy leak meant the foundation was dissolving; he blamed a nearby road cut"`

   Both describe Mulholland's inspection of the dam that morning. `sorted(..., reverse=True)` is stable, so node 1 becomes `protected` and node 2 lands at the head of `buildable` (`short_script_generator.py:104-105`). The generator is handed the protected moment's other half, and prompt rule 3 (:34-38) requires every question to aim at the protected reveal — so all three questions converge on "what did Mulholland conclude that morning". Convergence by construction.
4. **Payoff nodes have NO subject/moment field.** Shape is exactly `{"text": str, "surprise_score": int}` across all 11 parents on disk. A "same subject" rule therefore cannot key on metadata, and TEXT similarity does not work either: the two colliding node texts share almost no vocabulary ("cleared the dam" vs "muddy leak / road cut"). The only signal that actually separates the cluster is the **tied max surprise score**.
5. **Score ties at the top are common.** ties@top across parents: 1,1,2,2,2,1,2,2,1,1,2 (outputs 1,2,28,3,35,4,5,6,7,8,9). So the fix fires on ~half of parents and must not starve the batch.
6. **Starvation check (simulated over all 11 parents on disk):** dropping the whole max-score cluster removes at most 1 node; buildable count goes 5→5, 4→4, 8→7, 6→5, 6→5, 5→5, 5→4, 8→7, 6→6, 8→8, 9→8. Every parent keeps ≥4 buildable payoffs for 3 shorts, and the prompt only consumes `buildable[:6]` anyway. No real material loss.
7. **The description duplication is downstream, not separate.** `build_short_description` (`metadata_builder.py:93-95`) prepends `curiosity_question` verbatim as line 1. Fixing the question fixes the description; no second change needed. (Shorts' `videos.description` column is empty in the DB — descriptions are built at publish time.)
8. **Single-call generation confirmed.** `_request` issues ONE `complete()` call (:127) for the whole batch; `generate_short_scripts` only makes a second call as a full-batch retry (:145-147). There is no sibling-by-sibling loop.
9. **Per-short re-script does not exist.** `routes_actions.py:37` — `_MAIN_ONLY_COMMANDS = frozenset({"gen-audio", "revoice", "assemble"})`, enforced at :71. A short cannot be revoiced or re-assembled individually; the only re-roll path is "Regenerate shorts" on the parent, which discards unpublished siblings.

## Requirements

Functional:

- R1. `_distill_parent` must exclude from `top_payoffs` every payoff node that shares the protected node's surprise score, not just the protected node itself.
- R2. `protected_reveal` stays a SINGLE node (the prompt's rule 3 is written around one reveal). Cluster siblings are simply withheld — not mentioned to the model at all.
- R3. The rule must never starve the batch: if withholding the cluster leaves fewer than `DEFAULT_COUNT` buildable payoffs, fall back to today's behaviour (drop only `payoffs[0]`).
- R4. Existing behaviour for parents with <2 payoffs (nothing protected, everything buildable) is unchanged.

Non-functional:

- N1. Deterministic and unit-testable without an LLM call.
- N2. Smallest possible diff — one function body, no new module, no schema change, no prompt rewrite.
- N3. Prompt rule 3 (`short_script_generator.py:34-38`) must NOT be weakened; it is what makes the funnel work.

## Architecture

Unchanged data flow:

```
parent script.json
  -> _distill_parent  (payoff selection happens HERE — the only change)
  -> _SYSTEM + user prompt -> one LLM call -> ShortScript[]
  -> shorts_runner._produce_one -> TTS -> render -> publish (description line 1 = curiosity_question)
```

Current selection (`:99-105`):

```
payoffs   = sorted(payoff_nodes, key=surprise_score, desc)   # stable sort
protected = payoffs[0] if len(payoffs) >= 2 else None
buildable = payoffs[1:] if protected else payoffs
```

New selection: after picking `protected`, filter the remainder by `surprise_score != protected.surprise_score`; keep that filtered list only if it still has `>= DEFAULT_COUNT` entries, else keep `payoffs[1:]`.

Why score-equality is the cluster key: payoff nodes carry no subject field, and the colliding texts share almost no tokens (Key Insight 4), so lexical clustering cannot see the collision. A tie at the maximum surprise score is the model's own signal that two nodes are the same climax rated twice. Coarse, but deterministic, one-line, and cost-free — the false positive (two genuinely distinct top payoffs, one withheld) costs one strong-but-optional payoff out of 4-8 available and cannot produce a bad short.

## Related Code Files

Modify:

- `src/ai_operator/content/short_script_generator.py` — `_distill_parent` body + docstring (:92-119)
- `tests/test_short_script_generator.py` — extend contract tests

Create: none.

Delete: none.

## Implementation Steps

1. Open `src/ai_operator/content/short_script_generator.py`. In `_distill_parent`, replace the `buildable = payoffs[1:] if protected else payoffs` line (:105) with cluster-aware selection:

   ```python
   if protected:
       top = protected.get("surprise_score", 0)
       distinct = [p for p in payoffs[1:] if p.get("surprise_score", 0) != top]
       # Fall back to single-node protection rather than starve the batch of material.
       buildable = distinct if len(distinct) >= DEFAULT_COUNT else payoffs[1:]
   else:
       buildable = payoffs
   ```

2. Update the `_distill_parent` docstring to state the WHY without plan references: a parent's climax is often split across two payoff nodes rated equally, and handing the batch the second half makes every curiosity question converge on the same moment; so the whole top-scored cluster is withheld, floored so the batch keeps enough buildable material.
3. Do NOT touch `_SYSTEM`. `protected_reveal` stays a single dict; the withheld siblings are absent from `top_payoffs` and are already covered by the prompt's existing "withhold any other twist the full video resolves" clause (:38).
4. Add a similarity canary (observability only, NOT a gate) in `generate_short_scripts` after the batch is validated: compute max pairwise `difflib.SequenceMatcher` ratio over `curiosity_question` and `log.warning` when it is >= 0.70, including the parent `video_id`. Never raise, never regenerate — the question is baked into narration audio and there is no per-short re-script path (Key Insight 9). Keep it under ~8 lines; import `difflib` at module top.
5. Extend `tests/test_short_script_generator.py`:
   - `test_distill_withholds_whole_top_scored_cluster` — parent with scores `[5, 5, 4, 4, 3]`: `protected_reveal["surprise_score"] == 5`, no entry in `top_payoffs` has score 5, and `len(top_payoffs) == 3`.
   - `test_distill_keeps_material_when_cluster_drop_would_starve` — parent with scores `[5, 5, 5, 4]`: filtering leaves only 1 node, so `top_payoffs` falls back to `[5, 5, 4]` (3 nodes).
   - Single-top-score behaviour (`[5, 4, 3]` still yields `top_payoffs` scores `[4, 3]`) is already covered by `tests/test_short_script_generator.py:20-24` — extend that test rather than adding a duplicate.
   - Keep the existing `[4]` single-payoff test passing untouched.
6. Add `test_similar_curiosity_questions_are_logged` — patch `_request` to return two `ShortScript`s with near-identical `curiosity_question`, assert a warning is emitted (caplog) and that the function still RETURNS them (no raise, no extra LLM call).
7. Run `python -m pytest tests/test_short_script_generator.py tests/test_shorts_runner.py -q`.
8. Sanity-check against real data (read-only, no commit): load each `output/*/script.json`, run `_distill_parent`, print buildable counts; confirm every parent keeps >= 4 buildable nodes and parent 35's `top_payoffs` no longer contains the "muddy leak" node.

## Todo List

- [ ] Cluster-aware `buildable` selection in `_distill_parent`
- [ ] Docstring rewritten (WHY only, no plan refs)
- [ ] `_SYSTEM` untouched; verify rule 3 text unchanged in the diff
- [ ] difflib similarity WARNING (no gate) in `generate_short_scripts`
- [ ] Three distill unit tests + one logging test
- [ ] `pytest tests/test_short_script_generator.py tests/test_shorts_runner.py` green
- [ ] Real-parent sanity script run over `output/*/script.json`
- [ ] Full suite green before commit

## Success Criteria

- `_distill_parent(output/35/script.json)` returns `top_payoffs` with 5 nodes, none scored 5, and the "muddy leak" node absent.
- Every parent on disk keeps >= `DEFAULT_COUNT` buildable payoffs.
- Behaviour for parents with a unique top score is byte-identical to today.
- Next generated batch's pairwise `curiosity_question` difflib ratios land in the historical healthy band (<= ~0.6); a batch above 0.70 shows up as a WARNING in logs.
- This phase's diff touches no other module: no change to `_SYSTEM`, `short_schema`, or `shorts_runner`, and no publish-metadata change *from this phase* (phases 01 and 03 do edit `build_short_description`, independently).

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Two genuinely distinct top payoffs, one needlessly withheld | Medium (ties@top = 2 on ~half of parents) | Low — 4-8 buildable nodes remain, prompt uses at most 6 | Accept; floor at `DEFAULT_COUNT` keeps material |
| Fix does not eliminate convergence (LLM still converges on the protected reveal by design) | Medium | Low — rule 3 REQUIRES aiming at the same reveal; the goal is distinct ANGLES, not distinct targets | difflib warning makes recurrence visible; revisit prompt rule 4b (planted detail) if warnings persist |
| Cluster drop leaves <3 buildable on a future thin parent | Low | Medium — weak batch | Explicit fallback branch + dedicated test |
| Similarity warning becomes log noise | Low | Low | Threshold 0.70 sits above every healthy batch measured (max 0.56) |

### Rejected alternatives (do not implement)

- **Sibling ban-list of already-generated questions.** The whole batch comes from ONE `complete()` call (`short_script_generator.py:127`); at generation time there are no siblings to ban. Only the retry path (:147) could consume one, which is the rare case, not the common one.
- **Pre-publish difflib gate that regenerates the short.** The question is baked into the narration audio; changing it requires re-TTS + re-render through a per-short re-script path that does not exist — `_MAIN_ONLY_COMMANDS` blocks `gen-audio`/`revoice`/`assemble` for shorts (`routes_actions.py:37,71`). A gate could only block publication, leaving a rendered short unusable.
- **Relaxing prompt rule 3** (`short_script_generator.py:34-38`, every question must point at the protected reveal). That rule is the funnel. Do not weaken it.

### On a difflib assertion as a unit test over generated batches

Recommendation: **do not** assert similarity over generated batches; **do** add the two cheap things instead (steps 4-5 above).

Reasoning: a "generated batch" comes from a live LLM. A unit test that mocks `complete()` asserts only on the mock's canned strings — vacuous. A test that really calls the LLM is slow, costs money, and is nondeterministic, so it would either flake or be `skip`-ped into irrelevance. The regression risk being guarded is *structural* (which payoffs reach the prompt), and that IS deterministic — so assert it directly on `_distill_parent` output. Pair it with the runtime WARNING so real batches that still converge are visible without any test-suite flakiness or render-time gate.

## Security Considerations

None. No new inputs, no I/O, no credentials, no external calls. Pure in-process reshaping of data already loaded from the parent's own `script.json`; logging emits only a float ratio and a video id.

## Next Steps

- Re-roll shorts for a parent with tied top scores (force re-roll on an unpublished batch) and re-measure pairwise similarity.
- Leave published videos 37 / 38 alone — 0 views each, no remediation value, and republishing would burn a re-render.
- If warnings persist after the fix, the next lever is prompt rule 4b (making the PLANTED DETAIL provably different per short), tracked separately — not part of this phase.

## Unresolved Questions

1. Threshold 0.70 for the warning is chosen from 11 observed batches (healthy max 0.56, pathological min 0.74). Fine for now; revisit after ~10 more batches.
2. Should the withheld cluster siblings be surfaced to the model as an explicit "do not touch" list rather than silently omitted? Omission is smaller and safer (nothing to accidentally paraphrase), but it costs the model context about what the full video still resolves.
3. Nobody has verified whether the surprise scores themselves are reliable — if a parent's true climax is scored 4 while a lesser beat is scored 5, this fix protects the wrong moment. Out of scope here.
