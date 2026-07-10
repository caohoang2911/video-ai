"""Dashboard route: reuses the `ops.health` snapshot + `ops.validation` verdict — no status
query is re-implemented here, the panel just renders what the CLI already computes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request

from ..ops import channel_stats, health, validation
from . import analytics_view
from .charts import views_sparkline
from .rendering import render

router = APIRouter()


@router.get("/")
def dashboard(request: Request):
    snap = health.snapshot()
    verdict = asdict(validation.evaluate())
    return render(request, "dashboard.html", {
        "health": snap,
        "validation": verdict,
        "channel": channel_stats.load_channel_stats(),
        "views_svg": views_sparkline(analytics_view.trend_series()["views"]),
    })
