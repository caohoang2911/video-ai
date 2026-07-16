# Revoice UX: stale preview + approval reset — brainstorm & fix report

## Problem (user report, video #3)
Video #3 approved (PASS_POLICY + PASS_QUALITY 2026-07-12 03:10), user clicked revoice →
preview player broken ("không xem được video"), approval gone, no guidance on next step.

## Root cause (verified)
- Revoice job SUCCEEDED (job 57 done; narration.mp3 re-synth via ElevenLabs landed 16:14).
- By design `media/commands.py:revoice` deletes final.mp4 (old voice baked in) + drives state
  APPROVED→VOICED (new voice ⇒ must re-review). Data intact: script/imgs/thumbs all on disk.
- Bug: `video.video_path` in DB still pointed at deleted final.mp4; `_media_url()`
  (routes_videos.py) did not check file existence → template rendered `<video>` to a 404.
- UX gaps: no warning that revoice on an approved video tears down render + resets approval;
  no hint that `assemble` is the mandatory next step.

## Approaches considered
- Clear `video_path` in revoice command — fixes only this path, other stale pointers remain. NOT chosen (user opted out); display-layer check covers it anyway.
- Display-layer existence check — cheap, covers every stale-pointer case. CHOSEN.
- Manual assemble + hint vs auto-chain — user chose auto-chain (revoice intent = "new video with new voice"); render is local/free, low risk; enqueue dedup prevents double-render.

## Fixes applied (user-approved design)
1. **A — `web/routes_videos.py:_media_url`**: return None when artifact file no longer exists → template falls back to text instead of broken player. Covers thumb_url too.
2. **B — `web/templates/video_detail.html`**: preview fallback at state=voiced now says next step is assemble (auto-queued after revoice, or manual button).
3. **C — `web/templates/video_detail.html`**: revoice button on rendered/policy_ok/approved/published gets JS confirm warning about render teardown + approval reset.
4. **D — `ops/job_worker.py:_revoice`**: on success auto-enqueue `assemble` for same video. Failure path (ElevenLabs miss raises) never chains. CLI flow unchanged (echo already instructs).

## Validation
- Full suite: 256 passed (253 pre-existing + 3 new).
- New tests: `test_job_worker.py::test_revoice_success_chains_assemble`,
  `::test_revoice_failure_does_not_chain_assemble`,
  `test_web_read_views.py::test_media_url_is_none_for_deleted_artifact`.
- Import check: no ops↔web cycle (`web.job_queue` imports nothing from `ops`).

## Recovery for video #3
Old revoice ran pre-fix → assemble NOT auto-queued. User must click assemble once (or
`enqueue assemble --video-id 3`), then re-approve PASS_POLICY → PASS_QUALITY → publish.
Web/scheduler process must be restarted to pick up fixed code.

## Unresolved questions
- None blocking. Optional later: surface "duyệt lại sau khi render xong" reminder on the
  decision panel when a video re-enters rendered after a revoice (skipped: YAGNI for now).
