# Audit — short "ảnh lệch so với lời kể"

Method: 6-lens adversarial workflow (find → 3-way refute → synthesize). Session limit killed ~84/106 verify agents + synthesize, so counts unreliable; below is hand-synthesized from the 6 completed FIND lenses + 22 completed verdicts + **owner's own re-verification on disk** (short 23 md5, span-presence census, git dating).

## Verdict: TWO independent, both-verified root causes

### A. CONTENT bug — reuse picker ranks novelty ABOVE relevance, no floor (active, most jarring)
`shorts_runner.py:330` — `key=lambda t: (t[1] in used, t[1] in batch_used, -t[0])`. Booleans sort lexicographically before `-overlap`, so ANY not-yet-used parent still outranks a perfectly-matching used one; `scored[0][1]` taken unconditionally → a **zero-overlap** image is copied silently. `batch_used` is one set across the 2-3 sibling shorts, so degradation is cumulative (short #1 gets best matches, #2/#3 get leftovers).

**Verified on disk (owner, md5 provenance), short 23 (Halifax explosion), 3/6 beats overlap 0:**
- b4 "cargo steamship / munitions hold" → parent beat 8 = **vụ nổ** (mushroom cloud). Perfect parent beats 3+4 skipped.
- b5 "burning ship / crowd at window" → parent beat 10 = **phòng xử án**. Perfect parent beats 6+7 skipped.
- b6 "massive explosion" → parent beat 12 = **tàn tích tuyết phủ**. Real explosion still (beat 8) already stolen by b4.

This is literally "ảnh lệch so với lời" and is **independent of timing**. Only the reuse path (parent has ≥ len(beats) distinct stills); most shorts hit it.

Compounding: F30 — prompt rule 9 forces the LAST beat's keywords to echo the FIRST beat's (loop), but `used` demotes beat 1's image, so the loop beat is guaranteed the wrong still (last-beat mean overlap 1.27 vs first-beat 3.47).

### B. TIMING bug — every shipped short runs the EVEN SPLIT (active, pervasive, subtler)
Verified: **0 of 132 beats** across all 22 shorts carry a `narration_span`. All 22 predate `c71a339` (added the field 2026-07-21 19:19; newest short 17:41). So `beat_targets` returns None (`short_builder.py:179`) → `_beat_durations` even-splits. Measured drift of each even cut vs nearest true sentence boundary (whisper word times already on disk): **mean 1.9s, max 5.3s (short 31)** — image changes 1-2 sentences off the line.

The span-timing feature **has never engaged in production.** When it first does, it faces latent defects (spans currently optional + unvalidated, so LLM paraphrase/omission → silent even-split again):
- F16/F21 monotonic-floor cascade: one unmatched/out-of-order span drags every LATER matched boundary forward (clamp `max(target, floor)`). Docstring claims the opposite. Reproduced on output/25: one doubled-space in a span → a correct 16.75s boundary clamped to 21.5s.
- F17/F20 silent partial match: `found >= 1` returns the grid; no log/metric/gate. Only the zero-span case logs, and its text ("beats carry no narration spans") misnames the paraphrase case.
- F25 negative/zero duration: last boundary can exceed `narration_dur` → negative `-t` crashes ffmpeg trim (or exactly 0.0 → silent empty 261-byte segment, beat's image never appears). Test only asserts `durations[:-1]`.
- F24/F28 snap-to-END: snaps to caption-segment END (phrase before the cut) not the START where the span begins; 55% of segment ends are mid-sentence; 58% of boundaries find no end within ±0.8s → raw drifted proxy used.
- F32/F14 char-offset proxy: assumes constant chars/s; real narration is 21-27% silence, per-token rate spans 3.8-37.5 c/s → not calibratable, content-dependent.

## Refuted / trimmed (do not resurrect)
- "On-disk drift proves the char-proxy/verbatim-match bugs" — FALSE dating: on-disk shorts have no spans, they even-split. Those bugs are **latent** (future shorts), not the cause of current renders. (Multiple refuters, confirmed.)
- "Reuse path is ungated vs a gated alternative everywhere" — overstated: the beat-match floor guards only the archival/Wikimedia tier (`visual_fetcher.py:364`), not all paths.
- Monotonic floor as *sole* cause of the output/41 collapse — removing the floor gives byte-identical output there; the real trigger is `found>=1` accepting a one-span grid (`short_builder.py:179`).

## Fix plan (independent, layerable)

**A — reuse picker (small, low-risk, fixes worst symptom).** `shorts_runner.py:322-337`:
1. Relevance-first key: `key=lambda t: (-t[0], t[1] in used, t[1] in batch_used)` — de-dup preserved as tiebreak, never sacrifices a match for novelty.
2. Floor: if best overlap == 0, don't copy — refetch that beat via existing `_refetch_short_stills` (or log WARNING at minimum).
3. Loop beat: if last beat's keyword set == first beat's, deliberately copy beat 1's still.
Test: reconstruct short 23 assignment, assert no zero-overlap pick.

**B1 — make spans real + fail loud (generation).** `short_schema.py` ShortScript `model_validator(mode=after)`: normalize (NFKC, fold quotes/dashes/ellipsis, collapse ws) then require each non-empty span found in `narration` with a forward cursor, in order. Repair-then-drop (fuzzy relocate; drop the short only if <half beats anchor) to avoid batch-kill (`generate_short_scripts` raises at <MIN_VALID, called outside per-short try/except → whole job fails). Feeds existing retry.

**B2 — transcript alignment (root timing fix, ~medium).** Pass `caps` into `beat_targets`; locate span's first tokens in the whisper word sequence via `difflib.SequenceMatcher` on normalized tokens; use that word's `start` (recovered 91-99% of tokens on real renders). Snap to segment/word START. Keep char-proxy only as low-confidence fallback.

**B3 — guards (small).** Clamp last boundary ≤ `narration_dur - _MIN_BEAT_S`, assert `all(d>0)` before render loop (F25). `beat_targets` return match count; WARNING on partial; fix the misnamed log (F17/F20). Don't let an even-split stand-in raise the floor — interpolate unmatched between matched neighbours (F16).

## DO NOT
- Add a calibration constant for char-rate (content-dependent, F14).
- Silently flip reuse to relevance-first WITHOUT keeping novelty as tiebreak — that reverses the owner's de-dup intent.
- Wire span validation in `short_builder` — belongs at generation so the retry can fix it.

## IMPLEMENTED (this session) — scope A + B1 + B3, zero-overlap → refetch

Owner picked A+B1+B3, refetch-on-zero-overlap. Shipped, adversarially reviewed, 564→ full suite green (+9 tests).

- **A** `shorts_runner._reuse_parent_images`: sort key now `(-overlap, in used, in batch_used)` (relevance primary, novelty tiebreak); zero-overlap beat → `_acquire_short_stills(child, short, [i])` refetch instead of arbitrary copy; closing beat whose keywords echo the opener reuses the opening still (loop). `_refetch_short_stills` refactored to share `_acquire_short_stills`, which now forwards `narration_span` so the archival beat-match gate/CLIP see the sentence (F31/F8).
- **B1** `short_schema`: `normalize_for_match` + `locate_spans` (fold curly quotes/en-em dash/nbsp/ellipsis/ws/case); `ShortScript` validator rejects only when <half of PRESENT spans appear verbatim (independent membership, not forward cursor — so a reused sentence isn't mistaken for paraphrase). All-empty (pre-field / regen re-validate) passes.
- **B3** `short_builder`: `beat_targets` matches via `locate_spans` and ANCHORS matched beats, INTERPOLATES unmatched between nearest anchored neighbours + fixed ends (kills the F16 monotonic-floor cascade); logs none/partial coverage with correct wording (F17/F20). `_beat_durations` reserves `_MIN_BEAT_S*(remaining)` per boundary → last beat never zero/negative (F25); `build_short` raises on any non-positive duration.

Adversarial review (8 attack angles) cleared the interpolation/duration math (monotonic anchors, no `lo>hi`, no div-by-zero, correct None) and the credit/refetch plumbing; caught + fixed one real bug (validator false-rejecting reused-verbatim sentences).

### Deferred (not done)
- **B2** transcript alignment (difflib over whisper word times; snap to segment START): the root timing fix. Char-offset proxy still errs mean 0.67s / max 2.11s and snaps to segment END. Latent now (span-timing only engages on shorts generated after c71a339, i.e. none yet). Do next if drift shows on real post-fix renders.
- Existing 22 shorts stay even-split (no spans) + keep any zero-overlap reuse images already on disk; regen (`regenerate-shorts` / `gen-visuals`) re-runs the fixed paths.

### Known limitation (low)
- `_acquire_short_stills` partial refetch has `visual_fetcher.acquire` write a `visual_fetch` checkpoint with a partial `count`; benign in current flow (regen invalidates first; nothing re-calls acquire on the child with the full list), but a future full `acquire(child)` would early-return. Note, not fixed (touches visual_fetcher's checkpoint contract).

## Open questions
1. B2 (transcript alignment) — do next, or wait for a real post-fix render to confirm the char-proxy drift is visible?
2. Prompt rule 9 says spans must not overlap, yet a "dramatic closer" reusing one sentence is plausible LLM output; keep the lenient membership validator (tolerates it, renderer interpolates) or tighten the prompt to forbid reuse?
