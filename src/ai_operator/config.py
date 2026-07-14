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

    # --- tts (phase 03) ---
    ELEVENLABS_API_KEY: str | None = None
    ELEVENLABS_VOICE_ID: str | None = None
    OPENAI_API_KEY: str | None = None

    # --- visuals (phase 03) ---
    PEXELS_API_KEY: str | None = None
    PIXABAY_API_KEY: str | None = None
    FAL_KEY: str | None = None
    # Operator kill-switch: comma-separated source names ("pixabay,pexels,wikimedia") turned
    # OFF without removing their API keys — e.g. a provider keeps returning content-mismatched
    # hits for the channel's niche.
    DISABLED_VISUAL_SOURCES: str = ""
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
    YT_CATEGORY_ID: str = "27"  # 27 = Education
    WEEKLY_VIDEO_CAP: int = 3

    # --- web control panel (local only) ---
    # Bind loopback only: the panel has no auth, so it must never listen on 0.0.0.0.
    WEB_HOST: str = "127.0.0.1"
    WEB_PORT: int = 8000

    def missing(self, keys: list[str]) -> list[str]:
        """Return the subset of `keys` that are unset/empty (for pre-flight checks)."""
        return [k for k in keys if not getattr(self, k, None)]


settings = Settings()
