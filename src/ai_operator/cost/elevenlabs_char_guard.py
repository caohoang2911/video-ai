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

from ..db.engine import SessionLocal
from ..db.models_ops import CostLedger
from ..logging_setup import get_logger
from .budget_guard import current_ym

log = get_logger("elevenlabs_char_guard")

CREATOR_TIER_MONTHLY_CHAR_QUOTA = 100_000  # ElevenLabs Creator plan ($22/mo) chars/mo allowance
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
    used = month_chars_used(ym)
    pct = used / CREATOR_TIER_MONTHLY_CHAR_QUOTA
    status = CharQuotaStatus(
        ym=ym,
        chars_used=used,
        quota=CREATOR_TIER_MONTHLY_CHAR_QUOTA,
        pct_used=pct,
        alert=pct >= ALERT_THRESHOLD_PCT,
        exhausted=pct >= 1.0,
    )
    if status.exhausted:
        log.error(
            "ElevenLabs monthly char quota EXHAUSTED: %d/%d chars (%.0f%%) for %s",
            used, CREATOR_TIER_MONTHLY_CHAR_QUOTA, pct * 100, ym,
        )
    elif status.alert:
        log.warning(
            "ElevenLabs monthly char quota at %.0f%%: %d/%d chars for %s",
            pct * 100, used, CREATOR_TIER_MONTHLY_CHAR_QUOTA, ym,
        )
    return status
