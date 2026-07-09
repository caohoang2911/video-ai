"""CLI for the ops package — mounted by cli.py via `register(app)`."""

from __future__ import annotations

from typing import Optional

import typer

from ..logging_setup import setup_logging
from . import analytics_puller, keepalive, pipeline_runner, scheduler


def register(app: typer.Typer) -> None:
    @app.command("run-scheduler")
    def run_scheduler_cmd() -> None:
        """Foreground always-on operator: produce / publish (jittered) / analytics / keepalive."""
        setup_logging()
        scheduler.run_scheduler()

    @app.command("run-pipeline")
    def run_pipeline_cmd(
        video_id: Optional[int] = typer.Option(None, "--video-id", help="Advance an existing video"),
        topic_id: Optional[int] = typer.Option(None, "--topic-id", help="Produce a new video from this topic"),
        motion: bool = typer.Option(False, "--motion/--stills-only", help="Fetch motion b-roll (needs a stock-video key)"),
    ) -> None:
        """Run the per-step pipeline (audio -> visuals -> assemble -> review) for one video."""
        setup_logging()
        if video_id is not None:
            vid = pipeline_runner.run_video(video_id, motion=motion)
        else:
            vid = pipeline_runner.run_new(topic_id, motion=motion)
        typer.echo(f"pipeline ran -> video {vid}" if vid else "pipeline: nothing to do (no topic)")

    @app.command("pull-analytics")
    def pull_analytics_cmd() -> None:
        """Pull YouTube Analytics for every uploaded video into the analytics table."""
        setup_logging()
        typer.echo(f"analytics updated: {analytics_puller.pull_all()} video(s)")

    @app.command("keepalive")
    def keepalive_cmd() -> None:
        """Force an OAuth token refresh so the refresh token never lapses."""
        setup_logging()
        typer.echo("OAuth token refreshed" if keepalive.refresh_token() else "YouTube not configured")
