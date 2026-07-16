# Phase 02 — Word-Level Karaoke Captions + Beat-Boundary Cuts (shorts)

Priority: HIGH | Status: done | Effort: M (~1 day) | Depends: Phase 01 merged (touches same builder)

## Context links

- `src/ai_operator/assembler/caption_whisper.py:30-36` — segment-level only, `word_timestamps=False`
- `src/ai_operator/assembler/srt_writer.py`, `ffmpeg_encode.burn_and_mux` (`_PORTRAIT_SUB_STYLE`)
- `src/ai_operator/assembler/short_builder.py:72-74` — beats get `narration_dur / len(beats)` even split
- A/B infra exists: `src/ai_operator/publisher/ab_variants.py`

## Key insights

- "Text động theo nhịp lời thoại" = standard 2026 shorts pattern: word-by-word highlight (karaoke).
  faster-whisper supports `word_timestamps=True` at negligible extra cost on base.en/int8.
- Even time-split means image cuts land mid-sentence; snapping cuts to nearest caption-segment
  boundary makes visuals "follow the narration" with zero LLM/schema change.
- SRT cannot do karaoke; needs ASS (`\k` tags or per-word Dialogue events). ffmpeg `subtitles=` burns ASS fine.

## Requirements

1. `transcribe()` gains word timestamps (return shape: segments + optional words; keep old callers working —
   long-form SRT path unchanged).
2. New ASS writer for shorts: per-word highlight (current word gold/white pop, rest of line dimmed),
   style consistent with existing `_PORTRAIT_SUB_STYLE` (font, outline, margin).
3. Shorts only, behind a flag (config or per-run), default ON for new renders after visual QA;
   long-form keeps SRT burn.
4. Beat cut snapping: compute cumulative even-split boundaries, snap each to nearest whisper segment
   end within ±0.8s tolerance; per-beat durations passed to kenburns render (variable, not uniform).

## Related code files

- Modify: `assembler/caption_whisper.py` (word timestamps)
- Create: `assembler/ass_karaoke_writer.py` (kebab/snake per Python convention; ~100 lines)
- Modify: `assembler/short_builder.py` (variable beat durations, ASS path), `assembler/ffmpeg_encode.py`
  (burn accepts .ass — likely already works via `subtitles=` filter; verify)
- Tests: `tests/test_ass_karaoke_writer.py` (timing math, escaping), extend `tests/test_shorts_runner.py`
  render stub if needed

## Implementation steps

1. Extend transcribe with `word_timestamps=True`; adapt return without breaking `srt_writer` callers.
2. Write ASS generator: one Dialogue per caption segment with `\k` centisecond runs per word.
3. Snap beat boundaries to segment ends; feed variable durations into segment render loop.
4. Render 1 test short; QA readability (word pop speed, 2-line max, no overlap with pinned title
   overlay `_pinned_title_fx` or end card).
5. Flag wiring + default-on decision after QA.

## Success criteria

- Regenerated short: captions highlight word-by-word in sync with narration (±100ms eyeball).
- Image cuts land on sentence/phrase boundaries, not mid-word.
- Long-form pipeline output byte-path unchanged (SRT still used).

## Risks

- Whisper word timing drift on proper nouns → tolerance snapping only, never trust word times for cuts
  (segment ends are stable).
- ASS styling collision with pinned title zone → reuse existing margin constants.
- 60s cap: variable beat durations must still sum to narration_dur exactly (assert in code).
