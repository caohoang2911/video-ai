"""Segment-level captions via faster-whisper -> `{start, end, text}` dicts.

Apple Silicon has no Metal/MPS backend for CTranslate2, so this always runs CPU int8
(`base.en`, ~8-15s for a 10-minute mp3 on M1 Max). Word-level timestamps are skipped on
purpose: they multiply the cue count 10x+ for no P0 benefit. The render path turns these
segments into an SRT (`srt_writer`) and burns them with ffmpeg's `subtitles=` filter -- no
MoviePy/Pillow TextClip rasterization.
"""

from __future__ import annotations

from pathlib import Path

from ..logging_setup import get_logger

log = get_logger("assembler.captions")

_MODEL = None  # lazy singleton: importing this module must not force a ~140MB model load


def _model():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel

        _MODEL = WhisperModel("base.en", device="cpu", compute_type="int8")
    return _MODEL


def transcribe(mp3_path: str | Path, with_words: bool = False) -> list[dict]:
    """Return segment-level captions: [{start, end, text}], in chronological order.

    `with_words=True` adds `words: [{start, end, text}]` to each segment (karaoke caption
    timing for Shorts); the SRT path ignores the extra key, so callers can share one call.

    faster-whisper's `segments` is a lazy generator -- must be consumed exactly once here.
    """
    segments, _info = _model().transcribe(str(mp3_path), language="en", word_timestamps=with_words)
    out: list[dict] = []
    for s in segments:
        seg: dict = {"start": s.start, "end": s.end, "text": s.text.strip()}
        if with_words:
            seg["words"] = [
                {"start": w.start, "end": w.end, "text": w.word.strip()}
                for w in (s.words or []) if w.word.strip()
            ]
        out.append(seg)
    return out
