---
phase: 3
title: "Vertical Render Path"
status: completed
priority: P1
effort: "6h"
dependencies: [1]
---

# Phase 3: Vertical Render Path

## Overview
A 1080×1920 (9:16) render path for shorts that reuses the existing assembler building blocks
(beat timing, Ken Burns, captions, branding, ffmpeg concat) but in portrait, with burned-in
captions and a curiosity-question end card.

## Requirements
- Functional: `build_short(short_video_id) -> final.mp4` renders a vertical clip from a
  `ShortScript` + reused parent assets + the short's narration; total ≤ 60s.
- Non-functional: reuse `kenburns_ffmpeg`, `caption_whisper`, `srt_writer`, `branding`,
  `ffmpeg_encode`, `beat_timing` — do NOT fork them; parametrize dimensions instead of copy-paste.

## Architecture
- Today `video_builder.py` hardcodes `WIDTH, HEIGHT, FPS = 1920, 1080, 24`. Introduce an
  **orientation/dimensions parameter** threaded through the render helpers (default landscape,
  so main videos are untouched), and a thin `assembler/short_builder.py` that drives them at
  1080×1920.
- **Landscape image → 9:16 framing:** Ken Burns pan within a portrait crop (safe center), OR a
  blurred-pad layout (image fit-to-width, blurred copy fills top/bottom). Pick blurred-pad as
  default (keeps the whole image, looks intentional); expose as a small setting.
- **Captions burned-in** (Shorts play muted): reuse `caption_whisper` → `srt_writer`, but render
  the SRT into the video (ffmpeg subtitles filter) at a mobile-legible size in the lower third.
- **End card:** last ~3s = the `curiosity_question` + a "▶ Full story on the channel" line
  (branding style), composited via the existing branding/ffmpeg path.
- Narration = the short's own `narration.mp3` (Phase 4 synthesizes it); beat durations via
  `beat_timing.compute_beat_durations` over the short's 3-5 beats so audio+picture stay locked.

## Related Code Files
- Create: `src/ai_operator/assembler/short_builder.py` — `build_short(video_id)` (portrait orchestration).
- Modify: `src/ai_operator/assembler/video_builder.py` — extract WIDTH/HEIGHT into a passed
  `dims` (default = landscape constant) so both builders share the segment logic.
- Modify (params only, no behavior change for landscape): `kenburns_ffmpeg.py`, `ffmpeg_encode.py`
  to accept target dims; `branding.py` end-card helper.
- Reuse: `caption_whisper`, `srt_writer`, `beat_timing`.

## Implementation Steps
1. Refactor landscape dims into a `RenderDims(w,h,fps)` passed into the shared helpers; default
   keeps `1920x1080x24` → run `test_ffmpeg_encode`/`test_segment_builder` to prove no regression.
2. `short_builder.build_short`: load `ShortScript` + short narration; per-beat portrait segments
   (blurred-pad + Ken Burns), concat, mux narration, burn captions, append end card → `final.mp4`.
3. Vertical-safe caption styling (position/size) + end-card composition.
4. Manual: render one short from a fixture → `ffprobe` shows 1080×1920, ≤60s, captions visible.

## Success Criteria
- [ ] `build_short` outputs a 1080×1920, ≤60s `final.mp4` with burned captions + curiosity end card.
- [ ] Landscape main-video render is byte-for-byte unchanged (existing assembler tests still green).
- [ ] Reused parent images render without ugly stretch (blurred-pad / safe Ken Burns).
- [ ] `short_builder.py` < 200 lines; zero duplicated ffmpeg logic (shared helpers, param'd dims).

## Risk Assessment
- **Refactor risk:** threading dims through shared helpers could regress landscape output → keep
  the landscape default identical + rely on existing assembler tests as the guard (TDD-friendly).
- **Caption burn-in cost/time:** extra ffmpeg pass; acceptable for a 40s clip. If Whisper on the
  short is redundant (we already have the exact narration text), generate the SRT from the known
  narration timing instead of re-transcribing (cheaper, more accurate) — prefer this.
