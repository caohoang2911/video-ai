"""Sentence-safe chunking for narration TTS.

Cutting text mid-clause makes TTS prosody trail off wrong at the seam, so we always split
at a sentence boundary. Short narrations synth in one request; long ones are grouped into
sentence-safe chunks whose cross-seam prosody is carried by ElevenLabs request-id stitching
(no repeated-tail overlap — repeating a chunk's tail would re-speak seconds of narration).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CHUNK_CHARS = 800
WORDS_PER_MINUTE = 150  # typical narrated-documentary TTS pace, used only to pick 1-shot vs chunked
SINGLE_SHOT_THRESHOLD_SEC = 5 * 60
DRAMATIC_PAUSE = '<break time="1.5s" />'
_DRAMATIC_ENDINGS = ("...", "—")  # ellipsis / em-dash: heuristic for a dramatic beat
# The script LLM marks reflective rests with a literal [REST] between sentences; TTS renders
# them as real silence long enough for the music bed to swell and the viewer to absorb the beat.
REST_PAUSE = '<break time="2.2s" />'
_REST_MARKER = re.compile(r"\s*\[REST\]")

# Split only on sentence-ending punctuation followed by whitespace -- never inside a clause
# (a lone "." inside e.g. "Dr." would need abbreviation handling, but narration scripts are
# generated prose without such abbreviations, so this stays intentionally simple).
_SENTENCE_END = re.compile(r"(?<=[.!?:])\s+")


@dataclass
class TextChunk:
    text: str
    prev_text: str | None  # ElevenLabs `previous_text` context (ignored if request-id chain active)
    next_text: str | None
    has_overlap_head: bool  # True if this chunk repeats the previous chunk's tail (crossfade point)


def estimate_duration_sec(text: str) -> float:
    """Rough narration length so we can pick 1-shot vs chunked without having synthed audio yet."""
    words = len(text.split())
    return words / WORDS_PER_MINUTE * 60.0


def split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation; a sentence is never broken mid-clause."""
    text = text.strip()
    if not text:
        return []
    return [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]


def _with_dramatic_break(sentence: str) -> str:
    """Insert an ElevenLabs SSML-style pause after a dramatic beat (ellipsis / em-dash)."""
    if sentence.endswith(_DRAMATIC_ENDINGS):
        return f"{sentence} {DRAMATIC_PAUSE}"
    return sentence


def _group_sentences(sentences: list[str], max_chars: int) -> list[str]:
    """Greedy-pack whole sentences into <=max_chars groups (never split a sentence)."""
    groups: list[str] = []
    current = ""
    for sent in sentences:
        sent = _with_dramatic_break(sent)
        candidate = f"{current} {sent}".strip() if current else sent
        if len(candidate) > max_chars and current:
            groups.append(current)
            current = sent
        else:
            current = candidate
    if current:
        groups.append(current)
    return groups


def _build_chunks(groups: list[str]) -> list[TextChunk]:
    """Build TTS chunks carrying prev/next context text for prosody, but with NO repeated-tail
    overlap in the spoken audio. Cross-chunk continuity is handled by ElevenLabs request-id
    stitching (see tts_providers); repeating the previous chunk's tail here would re-speak
    several seconds of narration at every seam."""
    chunks: list[TextChunk] = []
    for i, group in enumerate(groups):
        chunks.append(
            TextChunk(
                text=group,
                prev_text=groups[i - 1] if i > 0 else None,
                next_text=groups[i + 1] if i + 1 < len(groups) else None,
                has_overlap_head=False,
            )
        )
    return chunks


def chunk_narration(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[TextChunk]:
    """Return TTS-ready chunks: single chunk under 5min estimated, else sentence-safe + overlap."""
    # Swap rest markers for a spoken-silence break BEFORE sentence splitting so both the
    # single-shot and the chunked path carry it.
    text = _REST_MARKER.sub(f" {REST_PAUSE}", text)
    sentences = split_sentences(text)
    if not sentences:
        return []
    if estimate_duration_sec(text) < SINGLE_SHOT_THRESHOLD_SEC:
        return [TextChunk(text=text.strip(), prev_text=None, next_text=None, has_overlap_head=False)]
    groups = _group_sentences(sentences, max_chars)
    return _build_chunks(groups)
