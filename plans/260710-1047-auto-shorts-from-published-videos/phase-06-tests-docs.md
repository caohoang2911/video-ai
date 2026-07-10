---
phase: 6
title: "Tests & Docs"
status: completed
priority: P2
effort: "4h"
dependencies: [5]
---

# Phase 6: Tests & Docs

## Overview
Lock the shorts feature with pytest (schema/curiosity-gap, migration, runner, render dims, job
parity, auto-enqueue, publish metadata, review-gate parity) and document the flow — especially
the no-auto-publish rule.

## Requirements
- Functional: tests cover the curiosity-gap validator, the column migration (fresh + pre-existing
  table), child-short creation + idempotency, vertical output dims, `gen-shorts` DISPATCH parity,
  auto-enqueue-after-publish, and `#Shorts`+parent-link metadata.
- Non-functional: no network — LLM, TTS, ffmpeg, and YouTube are mocked; use the `temp_db`/`temp_db_fk` fixtures.

## Architecture
- Mock `short_script_generator`'s LLM client → fixed 2-3 shorts; assert validation + curiosity-gap.
- Mock `tts_narrator.synthesize` + `short_builder.build_short` in the runner test → assert 2-3
  child rows (kind=short, parent_id), idempotency, and `pending_review` landing.
- `build_short` dims: assert the ffmpeg command targets 1080×1920 (patch the encode boundary) —
  no real render.
- Migration test: apply on a table WITHOUT the columns → columns added; re-apply → no-op.

## Related Code Files
- Create:
  - `tests/test_short_schema.py` — curiosity-gap + length validators.
  - `tests/test_schema_migrations.py` — idempotent ADD COLUMN on fresh + legacy table.
  - `tests/test_shorts_runner.py` — child creation, idempotency, force-regenerate (discards non-published
    shorts + re-rolls), rejected-short-is-discarded (no rework), one-fails-others-survive, no-recurse.
  - `tests/test_regenerate_shorts_endpoint.py` — `POST /videos/{id}/regenerate-shorts` enqueues gen-shorts(force) for a main; 400/absent for a short.
  - `tests/test_short_builder_dims.py` — vertical dims / ≤60s (encode boundary mocked).
  - `tests/test_shorts_publish_metadata.py` — `#Shorts` + parent link; hashtags last; no auto-publish path.
- Modify:
  - `tests/test_job_worker.py` — extend the DISPATCH⇄JOB_COMMANDS parity assertion (now includes `gen-shorts`).
  - `docs/system-architecture.md` or `docs/deployment-guide.md` — shorts flow + review-gate + **no auto-publish** note.

## Implementation Steps
1. Write the unit tests above with all external boundaries mocked.
2. Runner test: seed a published main + parent script fixture; patch LLM/TTS/render; run
   `generate_shorts` → assert 2-3 child shorts, parent_id, idempotent re-run, no-recurse for kind=short.
3. Auto-enqueue test: simulate a main reaching `published` → assert one `gen-shorts` job enqueued
   (video.kind guard: a short reaching published enqueues nothing).
4. Publish-metadata test: approved short → `build_upload_body` contains `#Shorts` + parent URL, hashtags last.
5. Run full suite `PYTHONPATH=src .venv/bin/pytest -q`; fix failures (don't skip). Confirm landscape
   assembler tests still green (Phase 3 refactor).
6. Docs: concise; call out the human-review-gate requirement and that shorts never auto-publish.

## Success Criteria
- [ ] All new tests pass; existing suite still green (incl. unchanged landscape render).
- [ ] Curiosity-gap validator + migration idempotency + runner idempotency/no-recurse covered.
- [ ] Vertical dims asserted without a real render; no test hits a real provider.
- [ ] Docs describe the shorts flow + the no-auto-publish rule.

## Risk Assessment
- **Mocking depth:** patch at module boundaries (LLM client, `synthesize`, `build_short`, encode)
  so tests survive internal refactors.
- **ffmpeg-in-tests:** avoid real encodes — assert on constructed args/dims, not output bytes.

## Post-plan
After Phase 6 green: `/ck:journal` to capture the child-Video-as-short decision, the dims refactor,
and the curiosity-gap prompt learnings.
