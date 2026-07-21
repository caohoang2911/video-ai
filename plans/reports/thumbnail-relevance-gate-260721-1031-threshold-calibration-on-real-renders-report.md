# Thumbnail relevance gate — calibration on real renders

**Date:** 2026-07-21 | **Branch:** feat/ops-observability-validation
**Question:** is `THUMB_RELEVANCE_MIN = 0.5` right? (never calibrated on real output)
**Answer:** yes, keep 0.5 — but the threshold was never the problem.

## Method

46 archival candidates across 14 rendered videos (6 events), scored with the live Gemini
vision backend against (a) their own event subject and (b) a mismatched event subject as a
negative control. Verdicts spot-checked by eye against the source images.

## What the numbers say

Scores are **near-binary**, not continuous:

| band | meaning | example |
|---|---|---|
| 1.0 | real depiction of the event | St. Francis dam ruin; Lusitania photo |
| ~0.2 | AI-generated illustration OF the event | video 25 beat_03, video 3 beat_06 (both carry an "AI-Generated" watermark) |
| 0.0 | unrelated, or wrong event | every single wrong-subject control |

- Wrong-subject control: **0.0 across the board — zero false positives.** The gate discriminates.
- Nothing ever landed between 0.2 and 1.0. **Any threshold in (0.25, 0.9) behaves identically**,
  so 0.5 is safe and the only real choice is whether to admit the 0.2 band. It should not be
  admitted: that band is AI illustrations, exactly what a "real archival photo" hero must not be.
- `.env.example` shipped `THUMB_RELEVANCE_MIN=0.22` with a comment reading "Min CLIP relevance …
  0.20-0.30 typical" — a **leftover from the CLIP era**, wrong scale for a Gemini 0..1 judgment,
  and it admits the illustration band. Fixed to 0.5.

## The actual defect (why calibration was impossible)

`gemini-2.5-flash` free tier allows **5 requests/minute**. The gate fires one call per candidate
back-to-back, with no pacing and no retry. A normal 6-image pool outran the quota, every call
after the wall returned `None`, and `None` means **keep the image unjudged** — the gate was
silently off for most images in production. The fail-loud alert only fired when *no* image
scored at all, so partial blindness (the case that actually happens) was invisible.

Measured: `gemini-3.1-flash-lite` served 12 calls in 10s with no rejection, and judges this
question at least as well (validated case-by-case below).

## Second defect: "depicts the subject" ≠ "can face the video"

The old prompt asked only whether the image *depicts* the subject. Faithful depictions that
make terrible thumbnails scored 1.0:

- video 28 `beat_04` — a **museum scale model of MS Estonia in a glass display case**, 1.0, and
  `thumbnail_frame_score.usable()` passes it. It was one render away from being the channel face.
- video 35 `beat_03` — a **modern memorial plaque**, 1.0, also usable.

Reworded prompt (show the thing ITSELF; 0.0 for memorial / plaque / sign / museum display or
scale model / map / modern photo of the site today) re-scored all six spot-check cases correctly,
including both above → 0.0, while real depictions held at 1.0.

Complementary guard confirmed working: video 3 `beat_04` (a 1917 newspaper ad about the Halifax
disaster) scores a legitimate 1.0 and is dropped by `usable()`. Gate and frame-score cover
different failure modes; neither is redundant.

## Changes shipped

- `GEMINI_VISION_MODEL` setting, default `gemini-3.1-flash-lite` (chosen for free-tier quota).
- One bounded retry on quota rejections; permanent errors still fail fast.
- Relevance prompt excludes memorials / museum pieces / modern site photos by name.
- Alert now fires when **half a pool** goes unjudged, not only when nothing scores.
- `others` fallthrough pool is frame-score shortlisted before gating (a 40-frame stock pool
  was 40 vision calls to judge frames that could never win a variant slot). Nothing skips the gate.
- `.env.example` threshold 0.22 → 0.5 with the CLIP-scale trap documented.

End-to-end re-run after the change: v35 keeps the dam ruin and drops the plaque; v25 keeps the
Lusitania photo; v28 now passes **nothing** (museum model correctly rejected) and falls through
to the synthetic FLUX hero as designed. 519 tests pass.

## Unresolved

- v28 (MS Estonia) has no gate-passing archival at all → every thumbnail is synthetic. Worth
  checking whether the Commons search for that event is returning anything usable at all.
- Video 3's Asset rows register the same file under several `kind`s (re-render residue), so one
  file can enter both pools and take two A/B slots. Not reproducible on videos 35-38 — legacy
  rows only, left alone.
- The `_complete_gemini` TEXT fallback still uses `gemini-2.5-flash` at 5 req/min. Harmless while
  Anthropic is primary; would throttle badly if Anthropic ever goes down mid-run.
