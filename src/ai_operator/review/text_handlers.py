"""Free-text replies the bot is waiting on: an `_OTHER` reason, or new metadata after an
EDIT_* decision. Pending state lives in AppState (see app_state_store), not RAM, so a
bot restart mid-conversation doesn't strand the reviewer's next message.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ..config import settings
from ..logging_setup import get_logger
from .app_state_store import clear, get_json
from .decision_finalize import finalize_decision
from .metadata_edit import apply_metadata_edit, parse_edit_text

log = get_logger("review.text_handlers")


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None or str(chat.id) != settings.TELEGRAM_CHAT_ID:
        return  # ignore anyone outside the whitelisted reviewer chat

    text = (update.message.text or "").strip() if update.message else ""
    if not text:
        return

    reason_key = f"review_pending:{chat.id}"
    pending_reason = get_json(reason_key)
    if pending_reason:
        clear(reason_key)
        await finalize_decision(
            ctx, chat.id, pending_reason["video_id"], pending_reason["code"], reason=text
        )
        return

    edit_key = f"edit_pending:{chat.id}"
    pending_edit = get_json(edit_key)
    if pending_edit:
        clear(edit_key)
        video_id = pending_edit["video_id"]
        apply_metadata_edit(video_id, parse_edit_text(text))  # shared writer (web reuses it too)
        await update.message.reply_text(f"Metadata updated for video #{video_id}.")
        return

    # no pending prompt for this chat -> a stray message, nothing to do
