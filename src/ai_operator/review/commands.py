"""CLI surface for the review gate — mounted into the main Typer app by cli.py."""

from __future__ import annotations

import asyncio

import typer
from telegram import Bot

from ..config import settings
from ..logging_setup import get_logger, setup_logging
from .review_notifier import notify
from .review_report import weekly_report
from .telegram_bot import run_bot

log = get_logger("review.commands")


def register(app: typer.Typer) -> None:
    @app.command("run-bot")
    def run_bot_cmd() -> None:
        """Foreground long-polling review bot — single instance only (2 = 409 conflict)."""
        setup_logging()
        run_bot()

    @app.command("notify-review")
    def notify_review_cmd(
        video_id: int = typer.Option(..., "--video-id", help="Video row id (state=rendered)."),
    ) -> None:
        """Send a rendered video's preview + TIER-1 keyboard to the reviewer chat."""
        setup_logging()
        notify(video_id)
        typer.echo(f"Notified reviewer for video {video_id}.")

    @app.command("get-chat-id")
    def get_chat_id_cmd() -> None:
        """One-shot poll for the chat_id of the last message(s) sent to the bot.

        Do not run this while `run-bot` is already polling the same token — Telegram
        allows only one long-poll consumer per token (409 Conflict otherwise).
        """
        setup_logging()
        if not settings.TELEGRAM_BOT_TOKEN:
            typer.echo("TELEGRAM_BOT_TOKEN is not set.")
            raise typer.Exit(code=1)
        chat_ids = asyncio.run(_fetch_recent_chat_ids())
        if not chat_ids:
            typer.echo("No messages yet — send any message to the bot, then re-run this command.")
            return
        for cid in chat_ids:
            typer.echo(f"chat_id = {cid}")

    @app.command("review-report")
    def review_report_cmd(
        week: bool = typer.Option(True, "--week/--all", help="Trailing 7 days (default) vs all-time."),
    ) -> None:
        """Decision breakdown + rubber-stamp alert (100% approval over 3+ decisions)."""
        setup_logging()
        report = weekly_report(weeks=1 if week else None)
        typer.echo(
            f"since {report['since']}: {report['total_decisions']} decisions "
            f"(pass={report['passed']} reject={report['rejected']} "
            f"edit={report['edited']} hold={report['held']})"
        )
        typer.echo(
            f"approval: {report['approval_pct']}%  avg review gap: {report['avg_review_seconds']}s"
        )
        if report["rubber_stamp_alert"]:
            typer.echo("ALERT: approval is 100% — review may be rubber-stamping. Inspect manually.")


async def _fetch_recent_chat_ids() -> list[int]:
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    updates = await bot.get_updates()
    return sorted({u.effective_chat.id for u in updates if u.effective_chat})
