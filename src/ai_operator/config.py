"""Central settings loaded from .env via pydantic-settings.

All API keys are Optional so the foundation (db init, cost/checkpoint logic) works
with no .env present. Never log the *values* here — only key names when missing.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project paths (this file is src/operator/config.py -> project root is parents[2])
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
CHECKPOINT_DIR = OUTPUT_DIR / "checkpoints"
LOG_DIR = OUTPUT_DIR / "logs"
PROMPTS_DIR = PROJECT_ROOT / "prompts"


def ensure_dirs() -> None:
    """Create runtime directories (idempotent)."""
    for d in (DATA_DIR, OUTPUT_DIR, CHECKPOINT_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- content (phase 02) ---
    ANTHROPIC_API_KEY: str | None = None
    # Optional Anthropic-compatible gateway (self-hosted router/proxy). None -> official
    # api.anthropic.com. The endpoint must speak the Messages API (/v1/messages) format.
    ANTHROPIC_BASE_URL: str | None = None
    # Optional OpenAI-compatible LLM gateway (e.g. self-hosted 9router). Set LLM_GATEWAY_URL
    # to route script/hook generation through it instead of the official Anthropic API;
    # unset -> official Anthropic path stays the default. The gateway speaks OpenAI
    # /v1/chat/completions format, so model ids may carry a provider prefix (cc/…).
    LLM_GATEWAY_URL: str | None = None
    LLM_GATEWAY_KEY: str | None = None            # falls back to ANTHROPIC_API_KEY if unset
    LLM_GATEWAY_MODEL: str = "cc/claude-opus-4-8"
    GEMINI_API_KEY: str | None = None
    # Flag-only independent fact cross-check (Wikipedia + adversarial LLM) after research_gate.
    # Never blocks a video; annotates citations with fact_status for the human reviewer. Set
    # False to skip (e.g. Wikipedia outage or to save the extra LLM call).
    FACT_CROSSCHECK_ENABLED: bool = True

    # --- tts (phase 03) ---
    ELEVENLABS_API_KEY: str | None = None
    ELEVENLABS_VOICE_ID: str | None = None
    OPENAI_API_KEY: str | None = None

    # --- visuals (phase 03) ---
    PEXELS_API_KEY: str | None = None
    PIXABAY_API_KEY: str | None = None
    FAL_KEY: str | None = None
    # Which generator serves the last-resort still tier (maps/illustrations/stock misses).
    # "fal_flux": fal.ai FLUX.1-dev first (faster + higher quality, ~$0.025/image, commercial
    # output license via fal), with local SDXL as the OFFLINE fallback when fal/network fails.
    # "sdxl": local SDXL first (free, fully offline) with fal as fallback — rollback / no-network.
    IMAGE_GEN_BACKEND: str = "fal_flux"
    # Operator kill-switch: comma-separated source names ("pixabay,pexels,wikimedia") turned
    # OFF without removing their API keys — e.g. a provider keeps returning content-mismatched
    # hits for the channel's niche.
    DISABLED_VISUAL_SOURCES: str = ""
    # Thumbnail hero: minimum CLIP cosine relevance (subject vs image) an archival photo must
    # clear to face the video — blocks good-looking but wrong-subject archives (e.g. the wrong
    # ship's livery). Below it the hero falls back to a synthetic FLUX drama frame. CLIP cosine
    # for a relevant photo lands ~0.20-0.30; raise to be stricter. Gate is skipped if CLIP is
    # unavailable (no torch/model) so render never blocks on it.
    THUMB_RELEVANCE_MIN: float = 0.22
    # Enhance the primary thumbnail hero (real archival) through FLUX Kontext — subject-
    # preserving relight+grade, ~$0.04/video. Off => PIL grade only (no fal call).
    THUMBNAIL_KONTEXT_ENHANCE: bool = True
    # Char allowance of the operator's ACTUAL ElevenLabs plan (dashboard "credits"). The old
    # hard-coded Creator-tier assumption let the pipeline plan spend far past a smaller
    # plan's real wall. Default stays Creator (100k); set to your plan in .env.
    ELEVENLABS_MONTHLY_CHAR_QUOTA: int = 100_000

    # --- youtube (phase 06) ---
    YT_CLIENT_ID: str | None = None
    YT_CLIENT_SECRET: str | None = None
    YT_REFRESH_TOKEN: str | None = None
    YT_CHANNEL_ID: str | None = None

    # --- telegram (phase 05) ---
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None

    # --- infra / guardrails (phase 01) ---
    DB_URL: str = "sqlite:///data/operator.db"
    MONTHLY_BUDGET: float = 500.0
    LOG_LEVEL: str = "INFO"

    # --- channel config (phase 02/06) ---
    NICHE: str = "Forgotten Disasters of History"
    # Shown on branded render surfaces (Shorts end card); matches the live YouTube channel.
    CHANNEL_NAME: str = "Their Final Hours"
    # Public channel page; linked from the control panel sidebar.
    CHANNEL_URL: str = "https://www.youtube.com/@their-final-hours"
    YT_CATEGORY_ID: str = "27"  # 27 = Education
    WEEKLY_VIDEO_CAP: int = 3
    # Word-by-word "karaoke" captions on Shorts (ASS burn); long-form keeps plain SRT.
    # Falls back to SRT automatically when whisper yields no word timestamps.
    SHORTS_KARAOKE_CAPTIONS: bool = True

    # Case of the Short's top-band curiosity headline: "title" renders it as authored
    # (editorial look, matches the reference), "upper" uppercases it (louder). A/B design pick.
    SHORTS_HEADLINE_CASE: str = "title"

    # --- web control panel (local only) ---
    # Bind loopback only: the panel has no auth, so it must never listen on 0.0.0.0.
    WEB_HOST: str = "127.0.0.1"
    WEB_PORT: int = 8000

    def missing(self, keys: list[str]) -> list[str]:
        """Return the subset of `keys` that are unset/empty (for pre-flight checks)."""
        return [k for k in keys if not getattr(self, k, None)]


settings = Settings()
