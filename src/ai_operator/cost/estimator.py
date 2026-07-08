"""Per-step API cost estimation (USD). Pricing lives in constants.py (single source)."""

from __future__ import annotations

from ..constants import (
    ANTHROPIC_PRICES,
    COST_BUFFER,
    DEFAULT_ANTHROPIC_MODEL,
    ELEVENLABS_USD_PER_1K_CHARS,
    FAL_FLUX_USD_PER_IMAGE,
    OPENAI_TTS1_USD_PER_1M_CHARS,
)


def estimate_elevenlabs(chars: int) -> float:
    return chars / 1000 * ELEVENLABS_USD_PER_1K_CHARS * COST_BUFFER


def estimate_openai_tts(chars: int) -> float:
    return chars / 1_000_000 * OPENAI_TTS1_USD_PER_1M_CHARS * COST_BUFFER


def estimate_anthropic(
    in_tokens: int, out_tokens: int, model: str = DEFAULT_ANTHROPIC_MODEL
) -> float:
    price = ANTHROPIC_PRICES.get(model, ANTHROPIC_PRICES[DEFAULT_ANTHROPIC_MODEL])
    raw = in_tokens / 1e6 * price["in"] + out_tokens / 1e6 * price["out"]
    return raw * COST_BUFFER


def estimate_fal_images(n: int) -> float:
    return n * FAL_FLUX_USD_PER_IMAGE * COST_BUFFER


def estimate_step(provider: str, **units) -> float:
    """Dispatch by provider. Free providers (edge-tts, chatterbox, stock) => 0.0."""
    provider = provider.lower()
    if provider == "elevenlabs":
        return estimate_elevenlabs(units.get("chars", 0))
    if provider == "openai":
        return estimate_openai_tts(units.get("chars", 0))
    if provider == "anthropic":
        return estimate_anthropic(
            units.get("in_tokens", 0),
            units.get("out_tokens", 0),
            units.get("model", DEFAULT_ANTHROPIC_MODEL),
        )
    if provider == "fal":
        return estimate_fal_images(units.get("images", 0))
    return 0.0
