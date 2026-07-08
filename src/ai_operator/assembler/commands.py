"""CLI for the assemble step -- mounted into the shared Typer app by cli.py."""

from __future__ import annotations

import typer

from ..logging_setup import get_logger, setup_logging
from .thumbnail_generator import generate as generate_thumbnails
from .video_builder import assemble_video

log = get_logger("assembler.cli")


def register(app: typer.Typer) -> None:
    @app.command("assemble")
    def assemble(
        video_id: int = typer.Option(..., "--video-id", help="Video row id to assemble."),
    ) -> None:
        """Render final.mp4 (Ken Burns + captions + ducked music + branding), then
        generate the 3 thumbnail variants for later manual A/B."""
        setup_logging()
        result = assemble_video(video_id)
        typer.echo(f"Rendered {result['video_path']} ({result['duration_sec']}s)")

        thumbs = generate_thumbnails(video_id)
        typer.echo(f"Thumbnails: {', '.join(thumbs)}")
