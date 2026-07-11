"""Shared view helpers: one Jinja2Templates instance + content negotiation.

Every read handler builds a JSON-safe context dict and calls `render(...)`. The SAME handler
serves HTML to a browser and JSON to an API client — a router is mounted twice (once at "",
once at "/api"), and `render` looks at the request path (or Accept header) to pick the format.
This keeps zero duplication between the web UI and its JSON API.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from ..db.engine import SessionLocal
from ..db.models import Video
from ..db.models_ops import Job

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _nav_counts() -> dict[str, int]:
    """Sidebar badge counts: videos awaiting operator review + queued jobs.
    Injected into HTML renders only — JSON API payloads stay untouched."""
    with SessionLocal() as s:
        review = s.scalar(
            select(func.count()).select_from(Video)
            .where(Video.state.in_(("rendered", "pending_review")))
        ) or 0
        jobs = s.scalar(
            select(func.count()).select_from(Job).where(Job.status == "pending")
        ) or 0
    return {"review": int(review), "jobs": int(jobs)}


def wants_json(request: Request) -> bool:
    """True when the caller wants JSON: an `/api/...` path, `?format=json`, or an
    `Accept: application/json` (but not a browser's `text/html` default)."""
    if request.url.path.startswith("/api"):
        return True
    if request.query_params.get("format") == "json":
        return True
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept


def render(
    request: Request, template_name: str, context: dict[str, Any], *, status_code: int = 200
) -> Response:
    """Render `context` as JSON or via `template_name` depending on the request."""
    if wants_json(request):
        return JSONResponse(context, status_code=status_code)
    return templates.TemplateResponse(
        request, template_name,
        {**context, "nav_counts": _nav_counts()},  # sidebar badges, HTML-only
        status_code=status_code,
    )


def action_result(
    request: Request, payload: dict[str, Any], redirect_to: str, *, status_code: int = 200
) -> Response:
    """Result of a control POST: JSON for API callers, else a 303 Post/Redirect/Get so a
    browser form submit lands back on a page (no resubmit on refresh)."""
    if wants_json(request):
        return JSONResponse(payload, status_code=status_code)
    return RedirectResponse(url=redirect_to, status_code=303)


def iso(value: Any) -> Any:
    """ISO-8601 string for a date/datetime, else the value unchanged (JSON-safe)."""
    return value.isoformat() if isinstance(value, (datetime, date)) else value
