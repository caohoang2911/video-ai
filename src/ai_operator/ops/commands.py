"""CLI for the ops package — mounted by cli.py via `register(app)`."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import typer

from ..logging_setup import setup_logging
from . import analytics_puller, dependency_check, health, keepalive, pipeline_runner, scheduler, validation


def register(app: typer.Typer) -> None:
    @app.command("run-scheduler")
    def run_scheduler_cmd() -> None:
        """Foreground always-on operator: produce / publish (jittered) / analytics / keepalive."""
        setup_logging()
        dependency_check.warn_if_missing()  # surface a drifted venv at boot, not mid-job
        scheduler.run_scheduler()

    @app.command("run-pipeline")
    def run_pipeline_cmd(
        video_id: Optional[int] = typer.Option(None, "--video-id", help="Advance an existing video"),
        topic_id: Optional[int] = typer.Option(None, "--topic-id", help="Produce a new video from this topic"),
        motion: bool = typer.Option(False, "--motion/--stills-only", help="Fetch motion b-roll (needs a stock-video key)"),
        gen_all: bool = typer.Option(False, "--gen-all", help="Generate every beat with SDXL (skip stock; period-accurate)"),
    ) -> None:
        """Run the per-step pipeline (audio -> visuals -> assemble -> review) for one video."""
        setup_logging()
        if video_id is not None:
            vid = pipeline_runner.run_video(video_id, motion=motion, gen_all=gen_all)
        else:
            vid = pipeline_runner.run_new(topic_id, motion=motion, gen_all=gen_all)
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

    @app.command("health")
    def health_cmd(json_out: bool = typer.Option(False, "--json", help="Emit the raw snapshot dict")) -> None:
        """One-screen operator status: states, budget, quotas, last publish, errors, disk."""
        setup_logging()
        snap = health.snapshot()
        typer.echo(json.dumps(snap, indent=2, default=str) if json_out else health.render(snap))

    @app.command("validation-report")
    def validation_report_cmd(
        window: int = typer.Option(20, "--window", help="Number of most-recent published videos to evaluate"),
        json_out: bool = typer.Option(False, "--json", help="Emit the raw result dict"),
    ) -> None:
        """P0 go/no-go: aggregate the window and emit PASS_P0 / KILL_P0 / INSUFFICIENT_DATA."""
        setup_logging()
        result = validation.evaluate(window=window)
        typer.echo(json.dumps(asdict(result), indent=2, default=str) if json_out else validation.render(result))
