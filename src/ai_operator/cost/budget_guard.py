"""Monthly budget hard-cap. A single error loop must never drain the API budget.

`check_and_reserve` writes a pending ledger row so the reserved estimate counts toward
the month total immediately (spent = sum of actual_cost, falling back to estimated_cost).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from ..config import settings
from ..db.engine import SessionLocal
from ..db.models_ops import CostLedger
from ..logging_setup import get_logger

log = get_logger("budget")


class BudgetExceeded(Exception):
    """Raised when an estimated cost would exceed the remaining monthly budget."""


def current_ym() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def month_spent(ym: str | None = None) -> float:
    ym = ym or current_ym()
    spent_expr = func.coalesce(
        func.sum(func.coalesce(CostLedger.actual_cost, CostLedger.estimated_cost)), 0.0
    )
    with SessionLocal() as s:
        total = s.scalar(select(spent_expr).where(CostLedger.ym == ym))
    return float(total or 0.0)


def budget_remaining() -> float:
    return settings.MONTHLY_BUDGET - month_spent()


def check_and_reserve(
    estimated: float,
    *,
    step: str,
    provider: str,
    video_id: int | None = None,
    units: float = 0.0,
) -> int:
    """Raise BudgetExceeded if estimate blows the cap; else persist a pending ledger row.

    Returns the ledger row id — pass to `record_actual` once the real cost is known.
    """
    remaining = budget_remaining()
    if estimated > remaining:
        msg = (
            f"est ${estimated:.4f} > remaining ${remaining:.2f} "
            f"(step={step}, provider={provider})"
        )
        log.error("BudgetExceeded: %s", msg)
        _alert(msg)
        raise BudgetExceeded(msg)

    with SessionLocal() as s:
        row = CostLedger(
            video_id=video_id,
            step=step,
            provider=provider,
            units=units,
            estimated_cost=estimated,
            ym=current_ym(),
        )
        s.add(row)
        s.commit()
        return row.id


def record_actual(ledger_id: int, actual_cost: float) -> None:
    """Replace the reserved estimate with the measured cost after the API call."""
    with SessionLocal() as s:
        row = s.get(CostLedger, ledger_id)
        if row is not None:
            row.actual_cost = actual_cost
            s.commit()


def _alert(msg: str) -> None:
    # Telegram alerting is wired in phase 05; log-level alert for now.
    log.warning("BUDGET ALERT: %s", msg)
