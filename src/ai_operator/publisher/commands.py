"""CLI commands for the publisher package — mounted by cli.py via `register(app)`."""

from __future__ import annotations

import typer

from ..logging_setup import get_logger, setup_logging
from . import ab_variants
from .authorize_once import DEFAULT_CLIENT_SECRETS_PATH
from .authorize_once import run as run_authorize
from .publish import publish as publish_video

log = get_logger("publisher.cli")


def register(app: typer.Typer) -> None:
    """Mount `authorize`, `publish`, and `set-winner` on the shared CLI app."""
    app.command("authorize")(authorize_cmd)
    app.command("publish")(publish_cmd)
    app.command("set-winner")(set_winner_cmd)


def authorize_cmd(
    client_secrets: str = typer.Option(
        DEFAULT_CLIENT_SECRETS_PATH, "--client-secrets", help="OAuth Desktop App JSON path"
    ),
) -> None:
    """One-time interactive OAuth flow — prints YT_REFRESH_TOKEN to paste into .env."""
    setup_logging()
    run_authorize(client_secrets)


def publish_cmd(
    video_id: int = typer.Option(..., "--video-id", help="videos.id to publish (state=approved)"),
    publish_at: str | None = typer.Option(
        None, "--publish-at", help="ISO-8601 UTC schedule time (default: now)"
    ),
    title: str | None = typer.Option(None, "--title", help="Override the chosen title"),
) -> None:
    """Upload an approved video to YouTube (private, scheduled via publishAt)."""
    setup_logging()
    yt_id = publish_video(video_id, publish_at_iso=publish_at, title_override=title)
    typer.echo(f"published video {video_id} -> https://youtu.be/{yt_id}")


def set_winner_cmd(
    video_id: int = typer.Option(..., "--video-id"),
    title: str | None = typer.Option(None, "--title", help="Human-observed winning title"),
    thumb: str | None = typer.Option(None, "--thumb", help="Path to the winning thumbnail variant"),
) -> None:
    """Record the manually-observed Studio A/B winner (title and/or thumbnail)."""
    setup_logging()
    if not title and not thumb:
        raise typer.BadParameter("provide --title and/or --thumb")
    ab_variants.set_winner(video_id, title=title, thumb=thumb)
    typer.echo(f"recorded A/B winner for video {video_id}")
