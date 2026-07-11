"""Monthly ElevenLabs CHARACTER ledger -- separate from `budget_guard`'s USD cap.

ElevenLabs' Creator tier bills as a hard 100k-characters/month allowance, not a USD figure.
At P1 cadence (~5 videos/mo), total ElevenLabs USD spend never approaches the monthly USD
budget guard's ceiling, so that guard alone never catches this quota wall. This module sums
the same `CostLedger` rows `tts_providers.py` already writes on every ElevenLabs call
(`provider="elevenlabs", units=chars_billed`) against the Creator tier's char quota, and
warns with enough lead time (70%) to react before ElevenLabs starts hard-rejecting requests
mid-month.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

import time

import requests

from ..config import settings
from ..db.engine import SessionLocal
from ..db.models_ops import CostLedger
from ..logging_setup import get_logger
from .budget_guard import current_ym

log = get_logger("elevenlabs_char_guard")

# ElevenLabs subscription endpoint = the SOURCE OF TRUTH for usage (what the dashboard
# shows). The local ledger counts per ATTEMPT — including tries that fell back to free
# edge-tts — so it overstates real spend; it stays as the offline/no-key fallback only.
_SUBSCRIPTION_URL = "https://api.elevenlabs.io/v1/user/subscription"
_LIVE_TTL_SEC = 600  # cache the lookup; dashboard renders + produce gates share one call
_live_cache: tuple[float, tuple[int, int] | None] | None = None


def _live_subscription() -> tuple[int, int] | None:
    """(chars_used, quota) straight from ElevenLabs; None when key missing/offline
    (callers then fall back to the internal ledger). Cached for _LIVE_TTL_SEC."""
    global _live_cache
    if not settings.ELEVENLABS_API_KEY:
        return None
    now = time.monotonic()
    if _live_cache is not None and now - _live_cache[0] < _LIVE_TTL_SEC:
        return _live_cache[1]
    try:
        r = requests.get(
            _SUBSCRIPTION_URL, headers={"xi-api-key": settings.ELEVENLABS_API_KEY}, timeout=6
        )
        r.raise_for_status()
        data = r.json()
        value = (int(data["character_count"]), int(data["character_limit"]))
    except Exception as exc:  # noqa: BLE001 - offline/API error must not kill quota checks
        log.warning("elevenlabs subscription lookup failed (%s) -> using internal ledger", exc)
        value = None
    _live_cache = (now, value)  # failures cached too: no 6s hang on every dashboard render
    return value

# Default = Creator plan ($22/mo). The REAL wall is the operator's actual plan — override
# with ELEVENLABS_MONTHLY_CHAR_QUOTA in .env (e.g. 40000 for the Starter-tier dashboard).
CREATOR_TIER_MONTHLY_CHAR_QUOTA = 100_000


def monthly_quota() -> int:
    """Char allowance of the configured plan (.env override, defaults to Creator tier)."""
    return settings.ELEVENLABS_MONTHLY_CHAR_QUOTA or CREATOR_TIER_MONTHLY_CHAR_QUOTA
ALERT_THRESHOLD_PCT = 0.70  # gives lead time to react before ElevenLabs starts hard-rejecting


@dataclass(frozen=True)
class CharQuotaStatus:
    ym: str
    chars_used: int
    quota: int
    pct_used: float
    alert: bool      # >= ALERT_THRESHOLD_PCT of quota used
    exhausted: bool   # >= 100% of quota used -- callers should skip, not silently over-flag


def month_chars_used(ym: str | None = None) -> int:
    """Sum `CostLedger.units` for `provider='elevenlabs'` in month `ym` (default: current)."""
    ym = ym or current_ym()
    with SessionLocal() as s:
        total = s.scalar(
            select(func.coalesce(func.sum(CostLedger.units), 0.0)).where(
                CostLedger.provider == "elevenlabs", CostLedger.ym == ym
            )
        )
    return int(total or 0)


def check_char_quota(ym: str | None = None) -> CharQuotaStatus:
    """Compute this month's ElevenLabs char usage vs the Creator tier quota.

    Logs a warning at/above the alert threshold and an error once exhausted -- callers
    (ElevenLabs synth, phase 06's produce/publish jobs) decide what to DO with the result
    (skip + alert rather than silently flagging videos `needs_revoice` past the wall).
    """
    ym = ym or current_ym()
    live = _live_subscription()
    if live is not None:
        used, quota = live  # số thật từ ElevenLabs (đúng cái dashboard hiển thị)
    else:
        used, quota = month_chars_used(ym), monthly_quota()  # fallback: sổ nội bộ
    pct = used / quota
    status = CharQuotaStatus(
        ym=ym,
        chars_used=used,
        quota=quota,
        pct_used=pct,
        alert=pct >= ALERT_THRESHOLD_PCT,
        exhausted=pct >= 1.0,
    )
    if status.exhausted:
        log.error(
            "ElevenLabs monthly char quota EXHAUSTED: %d/%d chars (%.0f%%) for %s",
            used, quota, pct * 100, ym,
        )
    elif status.alert:
        log.warning(
            "ElevenLabs monthly char quota at %.0f%%: %d/%d chars for %s",
            pct * 100, used, quota, ym,
        )
    return status
