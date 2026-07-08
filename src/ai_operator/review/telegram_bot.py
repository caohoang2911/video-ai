"""Wire the Telegram Application: handlers + the blocking long-polling loop.

Long polling only (no webhook) — no public IP/HTTPS needed. python-telegram-bot raises a
409 Conflict if a second poller starts on the same bot token, so a file lock gives a fast,
clear local error instead of two instances silently fighting over updates.
"""

from __future__ import annotations

import fcntl
from typing import IO

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..config import DATA_DIR, settings
from ..logging_setup import get_logger
from .callbacks import handle_callback
from .text_handlers import handle_text

log = get_logger("review.bot")

_LOCK_PATH = DATA_DIR / "review_bot.lock"


def build_application() -> Application:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    # concurrent_updates(False): handlers run sequentially -> avoids concurrent SQLite writers
    app = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .concurrent_updates(False)
        .build()
    )
    app.add_handler(CommandHandler("start", _start_cb))
    app.add_handler(CommandHandler("chatid", _chatid_cb))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app


async def _start_cb(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "AI Operator review bot online. Use /chatid to fetch this chat's id."
    )


async def _chatid_cb(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    # Deliberately not whitelist-gated: this is the bootstrap step that discovers the
    # chat_id to put in .env, so it must work before TELEGRAM_CHAT_ID is configured.
    await update.message.reply_text(f"chat_id = {update.effective_chat.id}")


def run_bot() -> None:
    """Foreground blocking entrypoint — single instance only (see module docstring)."""
    if not settings.TELEGRAM_CHAT_ID:
        log.warning("TELEGRAM_CHAT_ID not set — all callbacks/messages will be rejected")
    lock_file = _acquire_single_instance_lock()
    try:
        app = build_application()
        log.info("review bot starting long-polling")
        app.run_polling()  # sync/blocking — do not wrap in asyncio.run()
    finally:
        _release_lock(lock_file)


def _acquire_single_instance_lock() -> IO[str]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(_LOCK_PATH, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        fh.close()
        raise RuntimeError(
            "another review bot instance already holds the lock (single instance only)"
        ) from exc
    return fh


def _release_lock(fh: IO[str]) -> None:
    try:
        fcntl.flock(fh, fcntl.LOCK_UN)
    finally:
        fh.close()
