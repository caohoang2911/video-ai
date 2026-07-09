"""Operator CLI (typer).

Foundation commands + auto-mount of per-phase command modules. Each phase package may
expose a `commands.py` with `register(app: typer.Typer)`; it is mounted here if present,
so phases never edit this file (avoids shared-file churn).
"""

from __future__ import annotations

import importlib

import typer
from sqlalchemy import func, select

from .config import settings
from .cost.budget_guard import budget_remaining, current_ym, month_spent
from .db.engine import SessionLocal
from .db.engine import init_db as _init_db
from .db.models_ops import CostLedger
from .logging_setup import get_logger, setup_logging

app = typer.Typer(
    add_completion=False,
    help="AI Operator — faceless YouTube documentary pipeline",
)
log = get_logger("cli")

# phase command modules mounted opportunistically (created in later phases)
_PHASE_COMMAND_MODULES = (
    "content.commands",
    "media.commands",
    "assembler.commands",
    "review.commands",
    "publisher.commands",
    "ops.commands",
    "web.commands",
)


@app.command("init-db")
def init_db_cmd() -> None:
    """Create the SQLite schema + runtime directories."""
    setup_logging()
    _init_db()
    typer.echo("DB initialized.")


@app.command()
def status() -> None:
    """Show month-to-date budget usage."""
    setup_logging()
    typer.echo(
        f"Month {current_ym()}: spent ${month_spent():.2f} / "
        f"budget ${settings.MONTHLY_BUDGET:.2f} -> remaining ${budget_remaining():.2f}"
    )


@app.command()
def costs() -> None:
    """Cost ledger grouped by provider (current month)."""
    setup_logging()
    ym = current_ym()
    spent_expr = func.coalesce(
        func.sum(func.coalesce(CostLedger.actual_cost, CostLedger.estimated_cost)), 0.0
    )
    with SessionLocal() as s:
        rows = s.execute(
            select(CostLedger.provider, func.count(), spent_expr)
            .where(CostLedger.ym == ym)
            .group_by(CostLedger.provider)
        ).all()
    if not rows:
        typer.echo(f"No costs recorded for {ym}.")
        return
    for provider, n, total in rows:
        typer.echo(f"{provider:14} {n:4} calls  ${float(total):.2f}")


def _mount_phase_commands() -> None:
    for modname in _PHASE_COMMAND_MODULES:
        try:
            mod = importlib.import_module(f"ai_operator.{modname}")
        except ModuleNotFoundError:
            continue
        register = getattr(mod, "register", None)
        if callable(register):
            register(app)


_mount_phase_commands()


if __name__ == "__main__":
    app()
