"""Aggregations behind the cost-ledger page: current-month spend vs the monthly budget
cap, provider/step breakdowns, per-day spend series, and the all-time month history.

Spend rule (actual cost when recorded, else the reserved estimate) is imported from
cost.budget_guard so the page always agrees with what the guard enforces.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from ..config import settings
from ..cost.budget_guard import SPENT_EXPR, current_ym
from ..db.engine import SessionLocal
from ..db.models_ops import CostLedger


def _budget(spent: float) -> dict:
    """Spend vs the monthly cap, with a display level for the progress bar color."""
    monthly = settings.MONTHLY_BUDGET
    pct = round(100 * spent / monthly, 1) if monthly else 0.0
    level = "bad" if pct >= 90 else "warn" if pct >= 70 else "ok"
    return {
        "monthly": monthly,
        "spent": round(spent, 2),
        "remaining": round(monthly - spent, 2),
        "pct": pct,
        "bar_pct": min(pct, 100.0),
        "level": level,
    }


def overview() -> dict:
    ym = current_ym()
    with SessionLocal() as s:
        providers = s.execute(
            select(CostLedger.provider, func.count(), SPENT_EXPR)
            .where(CostLedger.ym == ym)
            .group_by(CostLedger.provider)
            .order_by(SPENT_EXPR.desc())
        ).all()
        steps = s.execute(
            select(CostLedger.step, CostLedger.provider, func.count(), SPENT_EXPR)
            .where(CostLedger.ym == ym)
            .group_by(CostLedger.step, CostLedger.provider)
            .order_by(SPENT_EXPR.desc())
        ).all()
        by_day = dict(
            s.execute(
                select(func.date(CostLedger.created_at), SPENT_EXPR)
                .where(CostLedger.ym == ym)
                .group_by(func.date(CostLedger.created_at))
            ).all()
        )
        videos, video_spend = s.execute(
            select(func.count(func.distinct(CostLedger.video_id)), SPENT_EXPR)
            .where(CostLedger.ym == ym, CostLedger.video_id.is_not(None))
        ).one()
        pending = s.scalar(
            select(func.count()).where(CostLedger.ym == ym, CostLedger.actual_cost.is_(None))
        )
        history = s.execute(
            select(CostLedger.ym, CostLedger.provider, func.count(), SPENT_EXPR)
            .group_by(CostLedger.ym, CostLedger.provider)
            .order_by(CostLedger.ym.desc(), SPENT_EXPR.desc())
        ).all()

    spent = sum(float(total) for _, _, total in providers)

    def _share(cost: float) -> float:
        return round(100 * cost / spent, 1) if spent else 0.0

    today = datetime.now(timezone.utc)
    return {
        "ym": ym,
        "budget": _budget(spent),
        "calls": sum(int(n) for _, n, _ in providers),
        "videos": int(videos),
        "avg_per_video": round(float(video_spend) / videos, 2) if videos else 0.0,
        "pending": int(pending or 0),
        "providers": [
            {"provider": p, "calls": int(n), "cost": round(float(c), 2), "share": _share(float(c))}
            for p, n, c in providers
        ],
        "steps": [
            {"step": st, "provider": p, "calls": int(n),
             "cost": round(float(c), 2), "share": _share(float(c))}
            for st, p, n, c in steps
        ],
        # per-day series from the 1st to today (UTC); gap days render as zero bars
        "daily": [round(float(by_day.get(f"{ym}-{d:02d}", 0.0)), 2)
                  for d in range(1, today.day + 1)],
        "history": [
            {"ym": m, "provider": p, "calls": int(n), "cost": round(float(c), 2)}
            for m, p, n, c in history
        ],
    }
