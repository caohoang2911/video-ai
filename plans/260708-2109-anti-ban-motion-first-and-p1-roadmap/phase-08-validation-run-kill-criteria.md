---
phase: 8
title: "Validation run + kill-criteria"
status: pending
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
- [ ] `validation-report` aggregates the window and prints avg views/retention/CTR + strike count.
- [ ] Emits PASS_P0 / KILL_P0 / INSUFFICIENT_DATA with the numeric rationale.
- [ ] Thresholds live in one tunable place; boundary cases classify correctly (unit-checked).
- [ ] Key-free pytest: `evaluate()` against a seeded/fixture `analytics` dataset (no live API key)
      classifies PASS_P0/KILL_P0/INSUFFICIENT_DATA correctly at every threshold boundary (retention,
      CTR, view-count, window-fill).
- [ ] compile + import clean.

## Risk Assessment
- Strike data has no public API: accept manual/app_state input; document the limitation.
- Premature KILL on thin early data: INSUFFICIENT_DATA guard until the window fills.
- Threshold subjectivity (CTR 4-6%): tunable; revisit with real data (open question in design doc).
