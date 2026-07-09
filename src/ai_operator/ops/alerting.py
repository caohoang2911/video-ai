"""Best-effort operator alerts: log always, and push to the Telegram review chat when it's
configured, so an unattended loop's real problems (char quota exhausted, dead OAuth token)
aren't lost in a log file no one is tailing. Alerting must never raise into the caller."""

from __future__ import annotations

import asyncio

from ..config import settings
from ..logging_setup import get_logger

log = get_logger("ops.alerting")


def alert(message: str) -> None:
    """Log a warning and, when Telegram is configured, push `message` to the review chat."""
    log.warning("ALERT: %s", message)
    if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID):
        return
    try:
        asyncio.run(_send(message))
    except Exception as exc:  # noqa: BLE001 - a failed alert must never break the job it warns about
        log.error("telegram alert delivery failed: %s", exc)


async def _send(message: str) -> None:
    from telegram import Bot

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    await bot.send_message(chat_id=settings.TELEGRAM_CHAT_ID, text=f"[operator] {message}")
