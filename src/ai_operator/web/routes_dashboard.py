"""Dashboard route: reuses the `ops.health` snapshot + `ops.validation` verdict — no status
query is re-implemented here, the panel just renders what the CLI already computes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request

from ..ops import health, validation
from .rendering import render

router = APIRouter()


@router.get("/")
def dashboard(request: Request):
    snap = health.snapshot()
    verdict = asdict(validation.evaluate())
    return render(request, "dashboard.html", {"health": snap, "validation": verdict})
