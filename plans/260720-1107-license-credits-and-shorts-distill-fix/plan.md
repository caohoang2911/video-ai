# License Credits + Shorts Distill Fix

**Created:** 2026-07-20 · **Branch:** `feat/ops-observability-validation` · **Status:** phase 01 implemented (497 tests green); phases 02-04 not started

## Why this plan exists

A multi-agent audit swept the pipeline for YouTube "inauthentic content" exposure, render fingerprinting, and ops health. Ten candidate fixes went through a value-vs-quality-regression triage where each one also got an adversary arguing it was a mistake. **Six were rejected because shipping them would make the channel worse.** What remains is this plan.

The audit's main negative result is worth stating up front so nobody re-derives it: **the pipeline is not at meaningful risk from the inauthentic-content policy.** That policy is monetization-only (no strikes, no removals — see `plans/reports/` for the verbatim clauses), `containsSyntheticMedia=True` is already set on every upload, and the content carries per-topic hand-written POV, a fail-closed research gate, and a sources block in every main description. The real defect the audit surfaced was a **licence** one, unrelated to that policy.

## Phases

| # | Phase | Priority | Status | Summary |
|---|---|---|---|---|
| 01 | [Shorts image-credit attribution](phase-01-shorts-image-credit-attribution.md) | **P0** | **done** (manual Studio paste outstanding) | 3 published Shorts embed CC BY-SA stills with zero attribution; 5 more rendered and queued to do the same. Description builder drops `image_credits`; the parent→child still copy writes no `Asset` row. |
| 02 | [Shorts distill reveal separation](phase-02-shorts-distill-reveal-separation.md) | P1 | not started | Shorts from one parent converge on the same closing question (0.74–0.89 similarity in one batch) because `_distill_parent` protects only `payoffs[0]` while the parent can hold two nodes describing the same event. |
| 03 | [Publish parent-link + analytics metric fix](phase-03-publish-parent-link-and-analytics-metric-fix.md) | P1 | not started | A Short can ship a `youtu.be` link to a parent whose recorded go-live is still in the future. Separately, the CTR query requests metric identifiers the Analytics API does not have, returning HTTP 400 on every video on every run. |
| 04 | [Narration cliché rule extension](phase-04-narration-cliche-rule-extension.md) | P2 · **optional** | not started | Prompt-only edit. 10 of 11 scripts close on the same abstraction; the `not just X, but Y` tic survives in the newest scripts via contracted forms. 0 lines of Python. |

## Key constraints

- **Phase 01 step 1 needs no merge.** There is no `videos.update` path anywhere in `src/`, so the three already-public placements are cured only by manual YouTube Studio description edits. The code change is prevention for the queued Shorts.
- **Attribution does not cure ShareAlike.** CC BY-SA 2.0/3.0 have no 30-day cure clause (unlike 4.0 §6(a)), so those licences already terminated automatically. Re-adding credit is good faith, not reinstatement — phase 01 recommends evaluating a public-domain swap for the three images.
- **Phases 01 and 03 both edit `build_short_description`** and `tests/test_shorts_publish_metadata.py`. No signature changes, so order is free; whoever lands second rebases.
- Phases 02 and 04 are independent of everything else.

## Explicit do-not-change list

These were investigated and are correct as-is. Changing them is a regression:

- `RETENTION_MIN_VIEWS = 200` (`analytics_puller.py`) — `retention_curve` already holds ~300 rows across 3 videos; the top video has 928 views. The gate is satisfied.
- The Shorts title rule forcing the entity/year anchor after the hook (`short_script_generator.py`) — it is what keeps the unique hook inside the ~30 chars a feed shows. The two best-performing Shorts (928 and 758 views) use exactly that shape.
- Ken Burns `i % 2` motion alternation — documented, test-guarded, and with a 2-element vocabulary "randomising" only means repeating a direction ~50% of the time.
- The music duration filter — the longest-track preference is hard, so a longer added track permanently evicts the field-proven bed from every future main.
- The ambient-glow constants — the claim that the modulation dominates the luminance spectrum was measured and is false (rank 5, 4.2× below content/cut energy).
- Uniform subtitle / headline / thumbnail typography — brand consistency, explicitly permitted by the policy text.
- LLM sampling (no temperature, no seed on either provider) — already maximally varied.

## Known debt, deliberately out of scope

- `uploads.publish_at` / `privacy` / `status` are write-once at insert and never reconciled against YouTube (all 19 rows still read `private` / `scheduled`). Every consumer therefore reads *intent*, not *fact*. Phase 03 works around it conservatively rather than fixing it.
- `videos.title` diverges from both `script.json` and the live YouTube title on at least one Short — the DB is not a reliable source for published metadata.
- `DEFAULT_WORD_TARGET = 1800` vs delivered 1025–1497 words (17–43% undershoot), and 9 of 10 long-forms landing in a 439–469s band. Needs an operator decision, not a code fix.

## The bigger question this plan does not address

Lifetime views: **Shorts 2558 across 12 uploads** (top 928 / 758 / 364) vs **long-form 66 across 4 measured** (top 39). Shorts work; long-form does not. This plan is housekeeping — packaging and first-30s retention on long-form is where the actual leverage is, and it needs its own investigation.

## Unresolved questions

1. ~~Swap the three CC BY-SA images for public-domain equivalents?~~ Decided 2026-07-20: credit and keep; PD swap is a standing follow-up, not scheduled.
2. Ship phase 04 now, or defer until the long-form question is answered?
3. ~~Is parent→short image reuse intentional?~~ Decided 2026-07-20: reuse stays, but one image must not span several shorts of the same family — sibling seeding shipped in phase 01.
4. Was any MAIN video published before the archival credit block existed, i.e. does the same gap exist on long-form? Not audited.
