# Auto-Shorts Implementation — Completion Report

Plan: `plans/260710-1047-auto-shorts-from-published-videos/` — all 6 phases done, 231/231 tests pass.

## Delivered
- **Data model**: `Video.kind` ("main"/"short") + `parent_id`; idempotent SQLite migration (`db/schema_migrations.py`) applied to live DB, 9 rows intact.
- **Short scripts**: `content/short_script_generator.py` + `short_schema.py` — 2-3 shorts per parent, curiosity-gap contract enforced by validators (question must end "?", narration 60-130 words, 3-5 beats).
- **Vertical render**: `assembler/short_builder.py` (1080×1920, blurred-pad + Ken Burns, burned captions, hook overlay beat 1, curiosity end card ≤60s). Landscape helpers parametrized via keyword defaults — landscape path unchanged (regression tests green).
- **Orchestration**: `ops/shorts_runner.py`; `gen-shorts` job registered (JOB_COMMANDS⇄DISPATCH parity); auto-enqueue after a MAIN publishes (kind-guarded, dedup, best-effort).
- **Publish + panel**: `#Shorts` + parent `youtu.be` link description variant; publish refused while parent not live; `/videos?kind=` filter, badges, parent↔children links, "Tạo lại Shorts" (force re-roll keeps published shorts).
- **Live proof**: shorts #10-12 (parent #9 General Slocum) rendered 1080×1920 @ 37-42s, state `rendered`, awaiting review. `script_path` backfilled post-fix.

## Review (code-reviewer subagent): DONE_WITH_CONCERNS → fixed
- **C1 fixed**: force-discard crashed on FK-enforced deps (CostLedger/Decision) AND rmtree'd files before DB commit. Now: per-child txn, fresh state re-check (closes publish race), detach cost rows (spend history kept), delete decisions/assets, DB-commit-first, then rmtree + checkpoint unlink. FK-on test added.
- **H1 fixed**: child `script_path` never set → published short would lose curiosity question/hashtags. Set at creation + asserted in tests + backfilled shorts 10-12.
- **M3 fixed**: FAILED mark now transition-guarded (pending_review has no FAILED edge).

## Deferred (low risk, tracked here)
- M4: panel "assemble" button on a short runs the landscape assembler (fails loudly, no corruption). Suggest kind-routing `_assemble` → `build_short`.
- Nitpicks: parent-upload query ordering; skip A/B submit for shorts; `ix_videos_kind` absent on migrated DBs; endcard text-file litter; hook overlay wrap at long text.

## Unresolved questions (need owner decision)
1. **Publish cadence sharing**: shorts consume the same 3/week upload throttle + approved-queue slots as mains. Intended? (Shorts thường đăng dày hơn main — có thể cần cap riêng.)
2. **Force re-roll discards `approved` (not-yet-published) shorts** — plan says "non-published", race now closed, but confirm approving-then-regenerating should drop the approval.
