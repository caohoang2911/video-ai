---
phase: 1
title: "Voice consistency + revoice gate"
status: done
priority: P1
effort: "3-4h"
dependencies: []
---

# Phase 1: Voice consistency + revoice gate

## Overview
Enforce ONE brand voice (ElevenLabs) as the only publishable narration. TTS becomes per-video
single-provider (no mixing). Any fallback marks the video `needs_revoice` and the publisher refuses
to upload it until it is re-voiced with ElevenLabs. This closes the CRITICAL "voice changes per video"
inauthenticity gap. `revoice` is a full teardown+rebuild (re-synth → invalidate the render → re-render),
not a narration-only patch — otherwise `final.mp4` keeps the stale voice baked in. ElevenLabs tier =
Creator (100k chars/mo, see plan.md "Locked decisions"); a monthly CHARACTER ledger (not just the USD
budget) throttles cadence, and the brand voice must be a distinctive/cloned ElevenLabs voice, not a
default preset everyone else uses.

## Requirements
- Functional: 1 video = exactly 1 TTS provider; only ElevenLabs output is publishable; fallback (edge-tts)
  produces a reviewable draft but sets `needs_revoice=True`; publisher blocks `needs_revoice` videos;
  `revoice` is a full teardown+rebuild — re-synth narration via ElevenLabs, delete the stale `final.mp4`
  + invalidate the `assemble` checkpoint, drive state back to `VOICED` so `assemble` re-runs, and clear
  `needs_revoice` only after a clean re-render.
- Functional: a monthly ElevenLabs CHARACTER ledger (not just the USD `budget_guard` cap) tracks usage
  against the Creator tier's 100k chars/mo and alerts at 70% (~70k); ElevenLabs synth is per-chunk
  resumable (checkpoint each chunk's audio + request-id) so a late failure retries only the missing
  tail, never discards completed chunks or drops the whole narration to edge-tts.
- Functional: `ELEVENLABS_VOICE_ID` must be a custom/cloned or deliberately distinctive voice (not a
  popular default preset) — provenance recorded, since a widely-reused default voice is itself an
  inauthenticity signal.
- Non-functional: budget-guarded (both USD and char ledger); idempotent (checkpoint); no ToS-violating
  audio ever published (edge-tts draft only); `previous_text=None` whenever `previous_request_ids` is
  non-empty (ElevenLabs ignores `previous_text` in that case; avoids double-billing the overlap chars).

## Architecture
Current `media/tts_providers.py` falls back PER CHUNK → can mix providers within one video. Change to
PER VIDEO: try ElevenLabs for the whole narration; on quota/failure, re-synthesize the whole narration
with edge-tts and flag. `Video.needs_revoice` (new column) gates the publisher. edge-tts stays because
the draft is never published (no commercial ToS breach); OpenAI/Chatterbox dropped from the P0 chain
(different voice = pointless for a single-brand-voice channel).

`revoice` cannot be a narration-only patch: `assemble` already baked the old audio into `final.mp4`,
and the assembler's "already done" checks (checkpoint + `state==rendered`) would just reuse the stale
render. `revoice` is therefore full teardown+rebuild, in order: (1) force ElevenLabs re-synth of
narration.mp3 (invalidate the `tts_narration` checkpoint entry); (2) delete `output/<id>/final.mp4` and
invalidate the `assemble` checkpoint entry; (3) drive `Video.state` back to `VOICED` so `assemble`
re-enters its render branch; (4) clear `needs_revoice` LAST, only after the ElevenLabs render succeeds
end-to-end — never optimistically.

Per-chunk resumability: `tts_narrator.synthesize` currently writes chunk audio to a `TemporaryDirectory`
that vanishes on any failure, forcing a full discard-and-retry (re-billing already-synthesized chars).
Checkpoint each chunk's audio path + ElevenLabs request-id as it completes; on retry, skip chunks
already checkpointed and synthesize only the missing tail. `previous_request_ids` stitching still
applies (ElevenLabs ignores `previous_text` once `previous_request_ids` is set — pass `previous_text=None`
in that branch to stop double-counting the overlap chars in the billed length).

The ElevenLabs monthly CHARACTER ledger reuses `CostLedger` (already populated: `tts_providers.py`
passes `provider="elevenlabs", units=chars_billed` on every call) — sum `units` where
`provider='elevenlabs' AND ym=current_month`, alert at 70% of the tier's char quota (Creator = 100k,
see plan.md "Locked decisions"). This is a NEW, separate guard from `budget_guard`'s USD cap: ElevenLabs
spend at P1 cadence never approaches the $500 ceiling, so the USD guard alone never catches the char wall.

## Related Code Files
- Modify: `src/ai_operator/db/models.py` (add `Video.needs_revoice: bool = False`)
- Modify: `src/ai_operator/checkpoint.py` (add `invalidate(video_id, step)` — remove a step's entry so
  it re-runs; used by `revoice` to invalidate `tts_narration` + `assemble`)
- Modify: `src/ai_operator/media/tts_providers.py` (per-video provider selection; ElevenLabs → edge-tts
  only; per-chunk resumable synth support; `previous_text=None` when `previous_request_ids` non-empty;
  return provider used)
- Modify: `src/ai_operator/media/tts_narrator.py` (whole-narration single provider; checkpoint EACH
  chunk's audio + request-id so a retry resumes from the missing tail; set `needs_revoice` when
  provider != elevenlabs)
- Create: `src/ai_operator/cost/elevenlabs_char_guard.py` (monthly ElevenLabs CHARACTER ledger: sum
  `CostLedger.units` where `provider='elevenlabs'` for the current `ym`; 70% alert threshold against
  the Creator 100k/mo quota; reused by phase 06's publish/produce jobs)
- Modify: `src/ai_operator/publisher/publish.py` (raise/skip when `video.needs_revoice`)
- Modify: `src/ai_operator/media/commands.py` (add `revoice --video-id` = full teardown+rebuild;
  `gen-audio` unchanged entry)
- Reference: `src/ai_operator/assembler/video_builder.py` (STEP="assemble" name + `final.mp4` path
  convention + the idempotent re-render-from-VOICED behavior that `revoice` drives back into)
- Reference: `config.ELEVENLABS_VOICE_ID` (already in settings — the locked brand voice)
- Reference: `docs/user-setup-checklist.md` (add a note: document the chosen custom/cloned or
  deliberately distinctive ElevenLabs voice + provenance, and the Creator tier ($22/mo, 100k chars/mo) signup)

## Implementation Steps
1. Add `needs_revoice` boolean to `Video`; delete dev `data/operator.db` + `operator init-db` (fresh, no data).
2. `checkpoint.py`: add `invalidate(video_id, step)` — drop that step's entry from the checkpoint file
   (inverse of `write`), so a later `is_done(video_id, step)` returns False and the step re-enters.
3. `tts_providers.py`: replace per-chunk fallback with `synthesize_video(chunks, ...) -> provider_name`:
   try ElevenLabs per chunk (keep request-id stitching; `previous_text=None` once `previous_request_ids`
   is non-empty); on a late per-chunk failure, retry only the missing tail chunks (never discard
   already-synthesized chunks); if ElevenLabs is unavailable/quota-exhausted from the FIRST chunk,
   re-run ALL chunks via edge-tts. Never interleave providers within one video. Return which provider
   was used.
4. `tts_narrator.py`: checkpoint each chunk's audio path + ElevenLabs request-id as it completes (not
   just the final concat); on resume, skip already-checkpointed chunks. After concat, if provider !=
   "elevenlabs" → set `Video.needs_revoice=True` (+ log). Checkpoint records provider used.
5. `elevenlabs_char_guard.py`: `month_chars_used(ym=None) -> int` (sum `CostLedger.units` where
   `provider='elevenlabs'`); `check_char_quota()` logs/alerts at 70% of the Creator 100k/mo quota;
   read by `tts_providers.py` before starting ElevenLabs synth and by phase 06's publish/produce jobs.
6. `publish.py`: at the top of `publish()`, load `needs_revoice`; if True → raise a clear error
   ("video N needs re-voice with the brand voice before publish") and do not spend quota.
7. `commands.py`: `revoice --video-id X` = full teardown+rebuild: (a) invalidate the `tts_narration`
   checkpoint + force ElevenLabs re-synth; (b) delete `output/<id>/final.mp4` if present + invalidate
   the `assemble` checkpoint; (c) drive `Video.state` back to `VOICED` (idempotent guard: only if not
   already VOICED); (d) clear `needs_revoice` ONLY after the ElevenLabs re-synth succeeds. Alert via
   budget/log if ElevenLabs still unavailable (leave `needs_revoice=True`, state unchanged).
8. Verify: compile + import; unit-check provider selection (mock quota fail → edge path sets flag);
   mock a late-chunk failure → resume synthesizes only the missing tail; `publish()` refuses a
   `needs_revoice` video; `revoice` on a rendered video deletes `final.mp4` + resets state to VOICED.

## Success Criteria
- [ ] `Video.needs_revoice` column exists; `init-db` on fresh DB includes it.
- [ ] A simulated ElevenLabs failure produces a single-provider (edge) narration with `needs_revoice=True`.
- [ ] Within one video, audio is never a mix of two providers.
- [ ] `publish()` refuses to upload a `needs_revoice=True` video (no quota spent).
- [ ] `revoice --video-id` on an already-rendered video: re-synthesizes via ElevenLabs, deletes the
      stale `final.mp4`, invalidates the `assemble` checkpoint, drives state back to `VOICED` (so a
      subsequent `assemble` actually re-renders with the new audio), and clears `needs_revoice` LAST.
- [ ] A simulated late-chunk ElevenLabs failure resumes from the missing tail chunk only (already-
      checkpointed chunks are not re-billed/re-synthesized).
- [ ] The monthly ElevenLabs CHARACTER ledger (`elevenlabs_char_guard`) correctly sums `CostLedger.units`
      for `provider='elevenlabs'` and alerts at 70% of the Creator 100k/mo quota (unit-tested at the
      boundary, key-free).
- [ ] `ELEVENLABS_VOICE_ID` documented as a custom/cloned or deliberately distinctive voice (not a
      popular default preset); provenance recorded.
- [ ] Key-free pytest unit tests under `tests/` cover: checkpoint invalidate/resume, char-ledger
      threshold boundaries, and `needs_revoice` gating — no live API keys required.
- [ ] compile + import clean.

## Risk Assessment
- edge-tts ToS: mitigated by never publishing edge output (draft-only) — documented in code comment.
- Quota churn (frequent revoice): acceptable at the ~1-1.5/week (~5/mo) target cadence reconciled to
  the ElevenLabs Creator tier (100k chars/mo); monitor via `elevenlabs_char_guard`; Chatterbox
  brand-clone is a P1 option if painful.
- ElevenLabs char quota exhaustion mid-month: `elevenlabs_char_guard`'s 70% alert gives lead time;
  phase 06's publish/produce jobs skip + alert (not silently over-flag) once exhausted.
- Fresh-DB reset loses any dev rows: none exist yet (pre-runtime).
