# Phase 01 — Ken Burns Motion Upgrade (pan + amplitude + freeze fix)

Priority: HIGH | Status: done | Effort: S (~half day)

## Context links

- `src/ai_operator/assembler/kenburns_ffmpeg.py` (whole file, ~90 lines)
- Callers: `src/ai_operator/assembler/segment_builder.py:121`, `src/ai_operator/assembler/short_builder.py:85,179`
- Advisor feedback: images read as "dead" despite existing zoompan

## Key insights (verified)

- `ZOOM_STEP=0.0015` @ 24fps = 0.036/s. Shorts beat ~5-7s → zoom 1.0→~1.2 only. Perceptible but weak on phone.
- `MAX_ZOOM=1.3` reached at (1.3-1.0)/0.036 ≈ **8.3s → motion freezes for remainder of beat**.
  Long-form beats run 8-20s (`beat_timing.py`) → dead motion tail on most long-form beats. Likely the real
  "ảnh chết" the advisor saw if reviewing a main video.
- No x/y expression passed to zoompan → defaults x=0,y=0 → zoom anchors TOP-LEFT corner, not center.
  Unintentional drift; reads as sloppy framing on portraits/faces.

## Requirements

1. Zoom step scales with beat duration: always reach target zoom exactly at beat end, never freeze.
   `step = (target_zoom - 1.0) / frames` computed per segment instead of global constant.
2. Center-anchored zoom by default: `x='iw/2-(iw/zoom/2)'`, `y='ih/2-(ih/zoom/2)'`.
3. Add lateral pan variants (left→right, right→left) alternated per beat alongside in/out zoom,
   caller-controlled the same way `zoom_in` is today (extend to a small enum/param, keep signature simple).
4. Shorts get higher target zoom than long-form (e.g. shorts 1.35-1.4, long-form keep ~1.25-1.3 —
   exact values are render-and-eyeball, expose as constants, not config).

## Related code files

- Modify: `assembler/kenburns_ffmpeg.py` (zoom expr, pan expr, per-duration step)
- Modify: `assembler/short_builder.py`, `assembler/segment_builder.py` (pass motion variant)
- Tests: extend `tests/test_ffmpeg_encode.py` or new `tests/test_kenburns_motion.py`
  (assert expr math: step*frames == target-1.0; no `min(...cap)` freeze form)

## Implementation steps

1. Refactor `render_segment` zoom expr: compute `step` from `duration`; drop global `ZOOM_STEP` usage
   (keep constant only as long-form default target reference if needed).
2. Add centered x/y expr; add `motion` param (`zoom_in|zoom_out|pan_lr|pan_rl`), default preserves
   current caller behavior (i%2 alternation maps to 4-cycle).
3. Update both callers to cycle through variants.
4. Re-render one existing short + one long-form video locally; eyeball motion continuity (no freeze,
   no corner-anchored drift).

## Success criteria

- Every segment moves for 100% of its duration regardless of length (unit test on expr math).
- Visual check: one regenerated short shows visibly stronger, varied motion; archival grade still applies.

## Risks

- zoompan sub-pixel jitter at higher zoom on 2x-upscaled source — already mitigated by existing 2x upscale;
  verify at 1.4 target.
- Cached rendered segments: `segments/` work dirs are deleted post-render; no stale-cache concern.
- Do NOT re-render already-published videos; applies to future renders only.
