"""Free-text replies the bot is waiting on: an `_OTHER` reason, or new metadata after an
EDIT_* decision. Pending state lives in AppState (see app_state_store), not RAM, so a
bot restart mid-conversation doesn't strand the reviewer's next message.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ..config import settings
from ..db.engine import SessionLocal
from ..db.models import Video
from ..logging_setup import get_logger
from .app_state_store import clear, get_json
from .decision_finalize import finalize_decision

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
        _apply_metadata_edit(video_id, text)
        await update.message.reply_text(f"Metadata updated for video #{video_id}.")
        return

    # no pending prompt for this chat -> a stray message, nothing to do


def _apply_metadata_edit(video_id: int, text: str) -> None:
    """Parse `field: value` lines (title/description/tags) and patch the Video row.

    P0 scope is metadata-only — re-rendering script/media from an edit is deferred
    (re-running the assembler/TTS steps would re-trigger paid API calls).
    """
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip().lower()] = value.strip()

    with SessionLocal() as s:
        video = s.get(Video, video_id)
        if video is None:
            log.warning("edit reply for unknown video %s", video_id)
            return
        if "title" in fields:
            video.title = fields["title"]
        if "description" in fields:
            video.description = fields["description"]
        if "tags" in fields:
            video.tags = [t.strip() for t in fields["tags"].split(",") if t.strip()]
        s.commit()
