"""TTS provider fallback chain: ElevenLabs -> OpenAI TTS-1 -> Chatterbox (optional/local) ->
edge-tts. ElevenLabs Starter is 30k chars/month (~3 videos) -- nowhere near enough for P0
volume, so quota/429 must fall through to a cheap paid tier before the always-free tier.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..config import settings
from ..cost.budget_guard import BudgetExceeded, check_and_reserve, record_actual
from ..cost.estimator import estimate_step
from ..logging_setup import get_logger
from .tts_chunker import TextChunk

log = get_logger("tts_providers")

EDGE_TTS_VOICE = "en-US-ChristopherNeural"
OPENAI_TTS_VOICE = "onyx"
_ELEVENLABS_MODEL = "eleven_multilingual_v2"  # only model that supports previous_request_ids stitching


class ProviderUnavailable(Exception):
    """Provider isn't configured (missing key/package) -- skip without charging anything."""


class ProviderFailed(Exception):
    """Provider was attempted and errored (429/quota/network) -- try the next tier."""


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

    chars_billed = len(text) + len(prev_text or "")
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
            previous_text=prev_text,
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


def synthesize_openai_tts(text: str, out_path: Path, *, video_id: int, voice: str = OPENAI_TTS_VOICE) -> None:
    if not settings.OPENAI_API_KEY:
        raise ProviderUnavailable("openai: OPENAI_API_KEY not set")

    from openai import OpenAI  # deferred for the same reason as elevenlabs above

    estimated = estimate_step("openai", chars=len(text))
    ledger_id = check_and_reserve(
        estimated, step="tts_openai", provider="openai", video_id=video_id, units=len(text)
    )
    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.audio.speech.create(model="tts-1", voice=voice, input=text)
        response.stream_to_file(str(out_path))
    except Exception as exc:
        record_actual(ledger_id, 0.0)
        raise ProviderFailed(f"openai tts-1: {exc}") from exc

    record_actual(ledger_id, estimated)


_chatterbox_model = None  # module-level singleton -- only loaded if this tier is actually reached


def synthesize_chatterbox(text: str, out_path: Path) -> None:
    """Free local TTS -- only exercised when both paid tiers are exhausted/misconfigured."""
    global _chatterbox_model
    try:
        if _chatterbox_model is None:
            from chatterbox.tts import ChatterboxTTS  # heavy + optional; not a base dependency

            _chatterbox_model = ChatterboxTTS.from_pretrained(device="mps")
        import torchaudio

        wav = _chatterbox_model.generate(text)
        torchaudio.save(str(out_path), wav, _chatterbox_model.sr)
    except Exception as exc:
        raise ProviderFailed(f"chatterbox: {exc}") from exc


def synthesize_edge_tts(text: str, out_path: Path, voice: str = EDGE_TTS_VOICE) -> None:
    """Free, always-available last resort. edge_tts is async -- wrap it for sync call sites."""
    import edge_tts

    async def _run() -> None:
        await edge_tts.Communicate(text, voice=voice).save(str(out_path))

    asyncio.run(_run())


def synthesize_chunk(chunk: TextChunk, out_path: Path, *, video_id: int, prev_request_ids: list[str]) -> str:
    """Walk the fallback chain; returns the provider name that actually produced audio.

    `prev_request_ids` is mutated in place so the ElevenLabs stitching context survives
    across chunks even when the fallback chain is invoked mid-narration.
    """
    try:
        rid = synthesize_elevenlabs(
            chunk.text,
            out_path,
            video_id=video_id,
            prev_text=chunk.prev_text,
            next_text=chunk.next_text,
            prev_request_ids=prev_request_ids,
        )
        if rid:
            prev_request_ids.append(rid)
        return "elevenlabs"
    except (ProviderUnavailable, ProviderFailed, BudgetExceeded) as exc:
        log.warning("elevenlabs unavailable/failed -> falling back to openai tts-1: %s", exc)

    try:
        synthesize_openai_tts(chunk.text, out_path, video_id=video_id)
        return "openai"
    except (ProviderUnavailable, ProviderFailed, BudgetExceeded) as exc:
        log.warning("openai tts-1 unavailable/failed -> falling back to chatterbox: %s", exc)

    try:
        synthesize_chatterbox(chunk.text, out_path)
        return "chatterbox"
    except (ProviderUnavailable, ProviderFailed) as exc:
        log.warning("chatterbox unavailable/failed -> falling back to edge-tts: %s", exc)

    synthesize_edge_tts(chunk.text, out_path)
    return "edge_tts"
