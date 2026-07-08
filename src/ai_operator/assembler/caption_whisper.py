"""Segment-level burn-in captions via faster-whisper.

Apple Silicon has no Metal/MPS backend for CTranslate2, so this always runs CPU int8
(`base.en`, ~8-15s for a 10-minute mp3 on M1 Max). Word-level timestamps are skipped on
purpose: they multiply the TextClip count 10x+ for no P0 benefit and become the actual
render bottleneck (MoviePy re-rasterizes text per clip via Pillow).
"""

from __future__ import annotations

from pathlib import Path

from moviepy import TextClip

from ..logging_setup import get_logger

log = get_logger("assembler.captions")

CAPTION_Y = 900          # fixed vertical position for 1920x1080 output, clear of subjects
CAPTION_FONT_SIZE = 48
CAPTION_WIDTH = 1600

_MODEL = None  # lazy singleton: importing this module must not force a ~140MB model load


def _model():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel

        _MODEL = WhisperModel("base.en", device="cpu", compute_type="int8")
    return _MODEL


def transcribe(mp3_path: str | Path) -> list[dict]:
    """Return segment-level captions: [{start, end, text}], in chronological order.

    faster-whisper's `segments` is a lazy generator -- must be consumed exactly once here.
    """
    segments, _info = _model().transcribe(str(mp3_path), language="en", word_timestamps=False)
    return [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]


def build_text_clips(captions: list[dict], font: str | None) -> list[TextClip]:
    """Segment-level TextClip list, positioned near the bottom for burn-in captions."""
    clips = []
    for cap in captions:
        if not cap["text"]:
            continue
        clip = TextClip(
            text=cap["text"], font=font, font_size=CAPTION_FONT_SIZE, color="white",
            stroke_color="black", stroke_width=2, method="caption",
            size=(CAPTION_WIDTH, None), duration=cap["end"] - cap["start"],
        )
        clip = clip.with_start(cap["start"]).with_position(("center", CAPTION_Y))
        clips.append(clip)
    return clips
