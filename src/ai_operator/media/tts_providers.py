"""TTS providers for ONE brand voice: ElevenLabs (the only publishable narrator) with an
edge-tts draft-only fallback. A single video is never a mix of two providers -- mixing
would itself be an inauthenticity signal, and `Video.needs_revoice` exists precisely to
force a full re-synth back onto ElevenLabs whenever edge-tts had to stand in.

OpenAI TTS-1 and the local Chatterbox clone are intentionally NOT in this chain: a
different-sounding fallback voice is pointless for a single-brand-voice channel (the point
of the ElevenLabs voice is that it's the ONE consistent narrator across every video).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path

from ..config import settings
from ..cost import elevenlabs_char_guard as char_guard
from ..cost.budget_guard import BudgetExceeded, check_and_reserve, record_actual
from ..cost.estimator import estimate_step
from ..logging_setup import get_logger
from .tts_chunker import TextChunk

log = get_logger("tts_providers")

EDGE_TTS_VOICE = "en-US-ChristopherNeural"
_ELEVENLABS_MODEL = "eleven_multilingual_v2"  # only model that supports previous_request_ids stitching


class ProviderUnavailable(Exception):
    """Provider isn't configured (missing key) -- skip without charging anything."""


class ProviderFailed(Exception):
    """Provider was attempted (or pre-flighted) and can't proceed -- 429/quota/network/char-cap."""


def synthesize_elevenlabs(
    text: str,
    out_path: Path,
    *,
    video_id: int,
    prev_text: str | None,
    next_text: str | None,
    prev_request_ids: list[str],
) -> str | None:
    """Returns the ElevenLabs request-id (for chaining) or None if the header was absent."""
    if not settings.ELEVENLABS_API_KEY or not settings.ELEVENLABS_VOICE_ID:
        raise ProviderUnavailable("elevenlabs: ELEVENLABS_API_KEY/ELEVENLABS_VOICE_ID not set")

    from elevenlabs.client import ElevenLabs  # deferred: keep this module importable without the SDK too

    # ElevenLabs ignores `previous_text` once `previous_request_ids` is supplied -- passing
    # both would silently drop prev_text server-side while still billing its chars against
    # `units` below, double-counting the overlap. Null it out here so this is the ONE place
    # that invariant is enforced, regardless of what the caller passes in.
    effective_prev_text = None if prev_request_ids else prev_text
    chars_billed = len(text) + len(effective_prev_text or "")
    estimated = estimate_step("elevenlabs", chars=chars_billed)
    ledger_id = check_and_reserve(
        estimated, step="tts_elevenlabs", provider="elevenlabs", video_id=video_id, units=chars_billed
    )
    try:
        client = ElevenLabs(api_key=settings.ELEVENLABS_API_KEY)
        r = client.text_to_speech.with_raw_response.convert(
            voice_id=settings.ELEVENLABS_VOICE_ID,
            text=text,
            model_id=_ELEVENLABS_MODEL,
            output_format="mp3_44100_128",
            voice_settings={
                "stability": 0.6,
                "similarity_boost": 0.8,
                "style": 0.0,
                "use_speaker_boost": True,
            },
            previous_text=effective_prev_text,
            next_text=next_text,
            previous_request_ids=(prev_request_ids[-3:] or None),
        )
        # request-id must be read from the raw response BEFORE consuming r.data (Iterator[bytes]);
        # r._response is the verified way to reach it on elevenlabs==2.56 (r.headers wraps the same
        # dict but the raw-response accessor is what the SDK's own docs/tests exercise).
        request_id = r._response.headers.get("request-id")
        with open(out_path, "wb") as f:
            for chunk_bytes in r.data:
                f.write(chunk_bytes)
    except Exception as exc:
        record_actual(ledger_id, 0.0)
        raise ProviderFailed(f"elevenlabs: {exc}") from exc

    record_actual(ledger_id, estimated)
    return request_id


def synthesize_edge_tts(text: str, out_path: Path, voice: str = EDGE_TTS_VOICE) -> None:
    """Free, always-available draft-only fallback -- never the audio that gets published.
    edge_tts is async -- wrap it for our sync call sites."""
    import edge_tts  # deferred: keep this module importable without the SDK too

    async def _run() -> None:
        await edge_tts.Communicate(text, voice=voice).save(str(out_path))

    asyncio.run(_run())


def _synth_elevenlabs_chunk(
    chunk: TextChunk, out_path: Path, *, video_id: int, prev_request_ids: list[str]
) -> str | None:
    """One ElevenLabs attempt, gated by the monthly character quota so we never place a call
    we already know would blow the Creator-tier ceiling."""
    status = char_guard.check_char_quota()
    if status.exhausted:
        raise ProviderFailed(
            f"elevenlabs monthly char quota exhausted: {status.chars_used}/{status.quota} chars for {status.ym}"
        )
    return synthesize_elevenlabs(
        chunk.text,
        out_path,
        video_id=video_id,
        prev_text=chunk.prev_text,
        next_text=chunk.next_text,
        prev_request_ids=prev_request_ids,
    )


def synthesize_video(
    chunks: Sequence[TextChunk],
    chunk_paths: Sequence[Path],
    *,
    video_id: int,
    done_indices: set[int],
    prev_request_ids: list[str],
    on_chunk_done: Callable[[int, str, str | None], None],
) -> str:
    """Synthesize every chunk NOT in `done_indices` with exactly one provider for the whole
    video. Returns "elevenlabs" or "edge_tts" (best-effort hint; a caller that persists
    per-chunk provider records should treat those records as authoritative).

    Resume semantics: `done_indices` chunks were already synthesized by a prior attempt --
    never re-billed/re-synthesized here. Provider selection is per-VIDEO, decided by what
    happens on the very first chunk this call attempts:
    - a from-scratch attempt (`done_indices` empty) whose FIRST chunk fails on ElevenLabs
      (quota/unavailable/failed) falls back to edge-tts for the ENTIRE narration -- a single
      provider for the whole video, never a mix;
    - a failure on any LATER chunk (or when resuming a partially-completed video) does NOT
      fall back to edge -- that would mix providers with the already-ElevenLabs-synthesized
      head. It raises instead, leaving every already-synthesized chunk untouched, so the
      next attempt retries only the missing tail against ElevenLabs.
    """
    pending = [i for i in range(len(chunks)) if i not in done_indices]
    if not pending:
        return "elevenlabs"  # nothing left to do -- caller derives the real provider from its own records

    first_idx = pending[0]
    try:
        rid = _synth_elevenlabs_chunk(
            chunks[first_idx], chunk_paths[first_idx], video_id=video_id, prev_request_ids=prev_request_ids
        )
    except (ProviderUnavailable, ProviderFailed, BudgetExceeded) as exc:
        if done_indices:
            raise ProviderFailed(
                f"elevenlabs failed resuming video {video_id} at chunk {first_idx}: {exc}"
            ) from exc
        log.warning(
            "video %s: elevenlabs unavailable on the first chunk -> synthesizing the entire "
            "narration via edge-tts (draft only; needs_revoice will be set): %s", video_id, exc,
        )
        for i in pending:
            synthesize_edge_tts(chunks[i].text, chunk_paths[i])
            on_chunk_done(i, "edge_tts", None)
        return "edge_tts"

    if rid:
        prev_request_ids.append(rid)
    on_chunk_done(first_idx, "elevenlabs", rid)

    for i in pending[1:]:
        rid = _synth_elevenlabs_chunk(chunks[i], chunk_paths[i], video_id=video_id, prev_request_ids=prev_request_ids)
        if rid:
            prev_request_ids.append(rid)
        on_chunk_done(i, "elevenlabs", rid)

    return "elevenlabs"
