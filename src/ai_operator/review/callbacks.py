"""Callback-query dispatch: every inline-keyboard tap funnels through `handle_callback`.

Two kinds of taps: (1) a *menu* tap (`REJECT_POLICY`, `EDIT`, `CHECKLIST`, `CHK_*`) that
only re-renders the keyboard and never touches the DB decision trail; (2) a *terminal*
decision code (`PASS_POLICY`, `REJECT_POLICY_AUDIO`, ...) that writes the audit row and
moves `videos.state` via `decision_finalize.finalize_decision`.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ..config import settings
from ..db.engine import SessionLocal
from ..db.models import Video
from ..logging_setup import get_logger
from . import decision_codes as dc
from .app_state_store import set_json
from .checklist import render_checklist, toggle_item
from .decision_finalize import finalize_decision
from .keyboards import reason_picker_keyboard, tier1_keyboard, tier2_keyboard

log = get_logger("review.callbacks")

_OPEN_REJECT_POLICY = "REJECT_POLICY"
_OPEN_EDIT = "EDIT"
_OPEN_CHECKLIST = "CHECKLIST"
_CHECKLIST_BACK = "CHK_BACK"
_CHECKLIST_PREFIX = "CHK_"


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat = query.message.chat if query.message else None
    if chat is None or str(chat.id) != settings.TELEGRAM_CHAT_ID:
        await query.answer("Unauthorized", show_alert=True)
        log.warning("dropped callback from non-whitelisted chat %s", chat.id if chat else "?")
        return

    await query.answer()  # required: clears the tap spinner regardless of what happens next
    code, _, vid_raw = (query.data or "").partition(":")
    try:
        video_id = int(vid_raw)
    except ValueError:
        log.warning("malformed callback_data %r", query.data)
        return

    if code == _OPEN_REJECT_POLICY:
        await query.edit_message_reply_markup(
            reply_markup=reason_picker_keyboard(dc.REJECT_POLICY_PREFIX, dc.POLICY_REJECT_REASONS, video_id)
        )
        return
    if code == _OPEN_EDIT:
        await query.edit_message_reply_markup(
            reply_markup=reason_picker_keyboard(dc.EDIT_PREFIX, dc.QUALITY_EDIT_REASONS, video_id)
        )
        return
    if code == _OPEN_CHECKLIST:
        await query.edit_message_reply_markup(reply_markup=render_checklist(video_id))
        return
    if code == _CHECKLIST_BACK:
        await query.edit_message_reply_markup(reply_markup=_current_tier_keyboard(video_id))
        return
    if code.startswith(_CHECKLIST_PREFIX):
        toggle_item(video_id, code[len(_CHECKLIST_PREFIX):].lower())
        await query.edit_message_reply_markup(reply_markup=render_checklist(video_id))
        return

    if not dc.is_final(code):
        log.warning("unknown decision code %r for video %s", code, video_id)
        return

    if dc.requires_free_text(code):
        set_json(f"review_pending:{chat.id}", {"video_id": video_id, "code": code})
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text(f"Reply with the reason text for {code} (video #{video_id}).")
        return

    await finalize_decision(ctx, chat.id, video_id, code, reason=None, query=query)


def _current_tier_keyboard(video_id: int):
    """Which keyboard to restore on "Back" — tier is determined by the video's live state."""
    with SessionLocal() as s:
        video = s.get(Video, video_id)
        state = video.state if video else None
    return tier2_keyboard(video_id) if state == "policy_ok" else tier1_keyboard(video_id)
