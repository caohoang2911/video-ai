"""CLI for the control panel: `run-web`. Mounted automatically by cli.py (it imports this
module and calls `register`)."""

from __future__ import annotations

import typer

from ..config import settings
from ..logging_setup import get_logger, setup_logging

log = get_logger("web.commands")


def register(app: typer.Typer) -> None:
    @app.command("run-web")
    def run_web(
        host: str = typer.Option(settings.WEB_HOST, "--host", help="Bind address (default loopback-only)"),
        port: int = typer.Option(settings.WEB_PORT, "--port", help="TCP port"),
    ) -> None:
        """Serve the local control panel + JSON API (no auth — bind stays on 127.0.0.1)."""
        setup_logging()
        import uvicorn  # local import: uvicorn is only needed for this long-lived process

        from .app import create_app

        log.info("control panel on http://%s:%s (Ctrl-C to stop)", host, port)
        uvicorn.run(create_app(), host=host, port=port)
