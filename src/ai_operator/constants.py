"""Provider pricing + tunable thresholds — single source of truth.

Prices are USD list-rate estimates (2026); update HERE when a provider changes pricing
so the cost estimator/budget guard stay accurate. A safety buffer is applied on top.
"""

from __future__ import annotations

# --- TTS ---
ELEVENLABS_USD_PER_1K_CHARS = 0.30      # effective Starter/Creator rate ballpark
OPENAI_TTS1_USD_PER_1M_CHARS = 15.0     # OpenAI tts-1

# --- LLM (Anthropic) — USD per 1M tokens {input, output} ---
ANTHROPIC_PRICES = {
    "claude-sonnet-5": {"in": 3.0, "out": 15.0},
    "claude-opus-4-8": {"in": 5.0, "out": 25.0},
    "claude-haiku-4-5": {"in": 1.0, "out": 5.0},
}
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"

# --- Image gen ---
FAL_FLUX_USD_PER_IMAGE = 0.025
FAL_KONTEXT_USD_PER_IMAGE = 0.04  # FLUX.1 Kontext [pro] image-edit — pricier than dev gen

# --- Estimation safety ---
COST_BUFFER = 1.10  # +10% headroom on every estimate

# --- Topic dedup ---
DEDUP_EMBED_MODEL = "all-MiniLM-L6-v2"  # ~90MB, CPU, 384-dim
DEDUP_COSINE_THRESHOLD = 0.85           # >= this vs history => duplicate topic

# --- YouTube quota (units) ---
YT_QUOTA_DAILY = 10_000
YT_COST_INSERT = 1600
YT_COST_THUMBNAIL = 50
YT_COST_UPDATE = 50
YT_QUOTA_ALERT_BELOW = 2000
