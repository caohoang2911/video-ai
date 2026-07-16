# Code Review — Shorts Motion / Karaoke Captions / Retention Curve / Sibling Series

Plan: `plans/260715-1749-shorts-motion-captions-retention-curve-series/` (4 phases)
Scope: uncommitted diff + untracked files listed in review request only (tree carries other unrelated WIP — cold-open, fact-check UI, costs view — excluded).

## Verdict

No Critical/High findings. Compile clean, **365/365 tests pass** (expected count matched). All 3 changed public contracts verified at every call site. One Medium quality finding (karaoke gap timing) + Low hardening notes. Two manual QA steps from the plan remain outstanding.

## Verification results

### (c) Contract changes — all call sites verified (grep, not assumed)
- `render_segment` `zoom_in` → `motion`: **zero `zoom_in=` callers remain** in src/ or tests/ (remaining hits are the MOTIONS literal and default-kwarg values in test fakes).
- `burn_and_mux sub_style: str | None`: video_builder uses default `_SUB_STYLE` (landscape unchanged), short_builder passes `None` (ASS) / `_PORTRAIT_SUB_STYLE` (SRT fallback), tests use defaults.
- `build_upload_body`/`build_short_description` new `sibling_youtube_id`: optional, default None; sibling lookup only under `kind == "short"` (publish.py:61) → mains untouched. All call sites fine.
- `transcribe(with_words=...)`: video_builder calls without it → long-form SRT path byte-identical.

### Math sanity (verified by hand)
- Freeze fix `step=(target-1)/(frames-1)` (kenburns_ffmpeg.py:60-61): cumulative `min(zoom+step,target)` reaches target at the last frame; motion spans the clip within ±1 frame for 3/8/20/45s. Old fixed-step froze after ~8s — fixed.
- Pan span `(iw-iw/zoom)` is the correct zoompan x-max; min/max clamps guard the `-t` extra-frame case. Center anchors `iw/2-(iw/zoom/2)` correct.
- ASS `_ts` centiseconds correct (61.234→`0:01:01.23`, 3601.5→`1:00:01.50`); `\k` runs sum to the dialogue span.
- ASS style ↔ `_PORTRAIT_SUB_STYLE` parity is numerically exact: FontSize 11×(1920/288)=73.3→73; Outline 2→13; MarginV 85→567; MarginL/R 45×(1080/384)=127.

### (b) Blast radius
- Long-form render: segment_builder now cycles 4 motions, landscape target 1.28 (plan asked ~1.25–1.3) — intentional Phase-1 change, not a regression.
- Analytics pull: retention isolated at 3 layers — inner try in `_query_retention` (analytics_puller.py:87), ≥200-views gate (line 153), outer per-video try (line 157). `_upsert` runs **before** the curve query → core metrics can never be lost to a curve failure.
- Web detail, never-uploaded video: `retention_panel` → None (retention_view.py:70-71) → template panel hidden. Covered by test_web_retention_view.py:37.
- Schema: `RetentionCurve` created by `Base.metadata.create_all` (db/engine.py:57) per convention — no ALTER path needed for a new table.

### (a) Acceptance criteria
| Phase | Status | Notes |
|---|---|---|
| 1 Ken Burns | ✅ code+tests | Manual step 4 (re-render + eyeball one short + one long-form) not verifiable from code — still owed |
| 2 Karaoke | ✅ | Sum-exact by construction (plan asked an assert; construction is stronger). Flag default ON but plan gated default-on on visual QA — confirm QA happened |
| 3 Retention | ✅ | Table, gated pull, replace-on-pull, sparkline + hook-zone + sibling overlay + views anchor + explicit empty state all present |
| 4 Sibling | ✅ | 24h gap guarantee holds end-to-end incl. future jittered publish_at (blocked via `publish_at > cutoff`, scheduler.py:79); backward-only single link, publish-time only |

## Findings

### Medium
1. **Karaoke words light up early after intra-segment pauses** — `ass_karaoke_writer.py:59-67`: each word's `\k` run spans from the *previous word's end*, so a 0.3–0.8s whisper gap (clause pause, comma) makes the next word turn white that much before it is spoken. Phase-2 success criterion is ±100ms. Deliberate and test-documented (test_ass_karaoke_writer.py:27-33), but the comment "timing stays true" is backwards — `\k` switches Primary at the *start* of the run. Fix is cheap: emit the gap as its own run on the inter-word space, e.g. `{{\k{gap}}} {{\k{dur}}}word`. Verify during the pending visual QA.

### Low
2. `_beat_durations` monotonicity overclaim — `short_builder.py:139-158`: the no-candidate fallback `bounds.append(target)` skips the `prev + _MIN_BEAT_S` guard; if `per_beat < ~_SNAP_TOLERANCE_S` a forward-snapped boundary can exceed the next even target → negative duration → ffmpeg `-t -0.02` failure. Unreachable for real shorts (≤60s / ~5-7 beats → per ≥ ~5s), but docstring says "stay monotonic". One-liner hardening: `bounds.append(max(target, prev + 0.1))`.
3. Sibling link liveness — `publish.py:72-80` comments "newest **live** sibling" but doesn't filter `publish_at <= now`; a manually scheduled-in-future sibling would be linked while still private. Scheduler path is safe (gap rule means the older sibling is live before the newer is scanned).
4. Sibling spacing applies only to the scheduler candidate scan; manual publish (web/CLI) bypasses it. Matches phase-04 wording — informational.
5. `_query_retention` ignores the `as_of` date the sibling queries use (analytics_puller.py:83 uses wall-clock today) — deterministic-backfill inconsistency only.
6. `zoom_out` first frame `if(eq(on,1),target,…)`: on ffmpeg builds where `on` starts at 0, frame 0 renders at zoom 1.0 then pops to target. Pre-existing idiom carried over (not a regression) — worth one look at the stronger 1.38 portrait target during QA.
7. `_clean` strips `{}` but not backslashes (`ass_karaoke_writer.py:47`) — `\N`/`\h` inside a word would render as escapes. Unreachable for whisper output; brace-strip already blocks override injection.
8. Stale test comment: test_kenburns_motion.py:41 says "6 decimals", code serializes `:.8f`. Assertion still valid.
9. `RetentionCurve` orphan rows are never pruned if an upload disappears — same as `Analytics`; negligible.

### Deviation from plan text (justified — do not "fix")
- Phase-3 says "`video_id` FK"; implementation keys on `youtube_video_id: String(32)` (models_ops.py:49). This matches the existing `Analytics` pattern exactly and sidesteps the temp_db FK=OFF vs prod FK=ON divergence. Correct call.

## Positive observations
- Failure-isolation style is uniform with the CTR precedent — comment even names it.
- Edge-state test coverage is strong: empty curve state, y-clamp for loop-heavy shorts, future-scheduled sibling blocking, degenerate ASS inputs, karaoke↔SRT fallback.
- Comments explain *why* (freeze math, force_style clobbering, replace-on-pull rationale) — audit-quality.

## Metrics
- `compileall`: clean. Tests: 365 passed / 0 failed (30.6s). Lint: ruff not installed in venv (no lint gate configured in repo).

## Unresolved questions
1. Was the Phase-2 visual QA render done before flipping `SHORTS_KARAOKE_CAPTIONS` default to True? Plan gated default-on on QA.
2. Phase-1 step 4 (re-render one short + one long-form, eyeball motion) — done?
