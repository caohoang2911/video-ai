"""FastAPI application factory for the local control panel.

Binds to 127.0.0.1 only (see web.commands) — there is no auth by design; the trust boundary
is the loopback interface. Each router is included twice: once at "" (server-rendered HTML) and
once under "/api" (JSON), so the UI and its JSON API share one set of handlers (DRY). Heavy
work is never run in-process here — control POSTs enqueue jobs the scheduler drains.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..config import OUTPUT_DIR
from . import routes_actions, routes_dashboard, routes_ops, routes_topics, routes_videos

STATIC_DIR = Path(__file__).parent / "static"

# Routers mounted at both "" (HTML) and "/api" (JSON) via content negotiation.
_ROUTERS = (
    routes_dashboard.router,
    routes_videos.router,
    routes_ops.router,
    routes_topics.router,
    routes_actions.router,
)


def create_app(output_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="AI Operator Control Panel", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def no_store(request, call_next):
        # Live operational data: forbid browser/proxy caching of pages, API responses AND
        # static css/js (tiny files; a stale stylesheet against new markup shatters the layout).
        # Only /media (large render artifacts, immutable per video) keeps default caching.
        response = await call_next(request)
        if not request.url.path.startswith("/media"):
            response.headers["Cache-Control"] = "no-store"
        return response

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Read-only mount of the render output tree so the panel can preview final.mp4 / thumbnails.
    media_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    for router in _ROUTERS:
        app.include_router(router)              # HTML at "/..."
        app.include_router(router, prefix="/api")  # JSON at "/api/..."
    return app
