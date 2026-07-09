---
phase: 8
title: "Validation run + kill-criteria"
status: done
priority: P2
effort: "2-3h"
dependencies: [6]
---

# Phase 8: Validation run + kill-criteria

## Overview
The P0 go/no-go harness: over the first 10-20 published videos, evaluate the channel against numeric
kill/pass thresholds from the design and emit a clear DECISION (continue / kill / change niche) so the
project doesn't drift on sunk cost.

## Requirements
- Functional: aggregate `analytics` over the validation window (≈20 videos / 3 months); compute avg views,
  retention%, CTR, and strike count; classify PASS_P0 / KILL_P0 / INSUFFICIENT_DATA against thresholds;
  print a decision report.
- Non-functional: pure read over existing tables; thresholds in one config block (tunable).

## Architecture
New `ops/validation.py` reads `analytics` + `uploads` + `videos`. Thresholds (from design + open Qs):
retention >30-40%, CTR ~4-6%, some videos >5-10K views, 0 policy strikes → PASS; flat <2-5K views + no
upward trend + retention <30% over the window → KILL. Strike count is manual input (no API) until confirmed.
Report is advisory; the human decides.

## Related Code Files
- Create: `src/ai_operator/ops/validation.py` (window aggregation + threshold classification + report)
- Modify: `src/ai_operator/ops/commands.py` (`validation-report [--window 20]`)
- Modify: `src/ai_operator/constants.py` (only if adding a threshold block — foundation-owned; otherwise keep thresholds local to validation.py)
- Reference: `docs/` (record the decision outcome per run)

## Implementation Steps
1. `validation.py`: `evaluate(window=20)` → pull last N published videos' latest `analytics`; compute avg
   views, avg retention, avg CTR, count of >5-10K-view videos, trend (early vs late window), strikes (manual/app_state).
2. Classify: PASS_P0 / KILL_P0 / INSUFFICIENT_DATA with the numeric thresholds (define constants in one block).
3. `commands.py`: `validation-report` prints the metrics + decision + rationale; `--json` optional.
4. Record decision to `docs/` (or `app_state`) for the audit trail.
5. Verify: compile + import; report runs against seeded/sample `analytics` and classifies correctly at boundaries.

## Success Criteria
- [x] `validation-report` aggregates the window and prints avg views/retention/CTR + strike count. — `ops/validation.py` + CLI `validation-report [--window] [--json]`.
- [x] Emits PASS_P0 / KILL_P0 / INSUFFICIENT_DATA with the numeric rationale. — `evaluate()` decision + `rationale`; KILL earned-only, ambiguous → marginal PASS (`strong_pass=False`).
- [x] Thresholds live in one tunable place; boundary cases classify correctly (unit-checked). — single threshold block in `validation.py`, local (foundation `constants.py` untouched).
- [x] Key-free pytest classifies at every boundary (retention, CTR, view-count, window-fill). — `tests/test_ops_validation.py` (13 cases: inclusive PASS/KILL boundaries, upward-trend override, strike gate).
- [x] compile + import clean. — imports clean; full suite 99 passed.

## Notes / decisions
- Only 3 output labels by design → the ambiguous middle (window full, no kill signal, but a
  PASS target unmet) classifies **PASS_P0 with `strong_pass=False`** and the unmet criteria in
  the rationale, rather than a silent auto-KILL. Killing a channel is an irreversible business
  call, so KILL_P0 must be clearly earned (flat low views AND low retention AND no upward trend).
- Policy strikes have no public API: read from `app_state["policy_strikes"]` (manual), default 0;
  a strike blocks a strong pass but does not by itself force KILL (kept aligned to the design).

### CTR collection + gate (from code review)
- **CTR now collected:** `analytics_puller._query_ctr` pulls `impressions,impressionsClickThroughRate`
  in a SEPARATE Analytics-API query (same `yt-analytics.readonly` scope, no new auth), stores the
  percentage-scaled value into `Analytics.ctr`. Separate query = a fresh/low-reach video with no
  impressions data records views/retention instead of failing the whole pull; `_upsert` only writes
  CTR when measured so a later unmeasured refresh can't wipe a prior good value.
- **Gate stays conditional:** validation gates CTR only when measured (`any ctr>0`); an all-zero CTR =
  "unmeasured" (fresh/low-reach), not a real 0%, so a strong pass can't be sunk on missing data.
  `health` shows `ctr=n/a` until measured. 4% threshold retained.
- **Trend uses cumulative views:** `views` is a running total, so newer uploads look lower and the
  early-vs-late trend is age-biased toward "flat" (nudges KILL easier). KILL is still triple-AND-gated
  (sub-2k views AND sub-30% retention AND no-up-trend) + INSUFFICIENT_DATA guard, so impact is bounded.
  A true trend needs age-normalized view-rate (not collected). Documented in `_is_upward`.

## Risk Assessment
- Strike data has no public API: accept manual/app_state input; document the limitation.
- Premature KILL on thin early data: INSUFFICIENT_DATA guard until the window fills.
- Threshold subjectivity (CTR 4-6%): tunable; revisit with real data (open question in design doc).
