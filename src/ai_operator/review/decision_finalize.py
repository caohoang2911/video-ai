"""Common tail of every TERMINAL review decision: write it, confirm it, and (for an
EDIT_* code) open the metadata-reply prompt.

Shared by the callback-tap path (has a `query` to edit in place) and the free-text
`_OTHER`-reason path (only has a plain chat message to reply into) so both end up with
an identical audit trail + confirmation UX.
"""

from __future__ import annotations

from datetime import datetime, timezone

from telegram.ext import ContextTypes

from ..db import InvalidTransition
from ..logging_setup import get_logger
from . import decision_codes as dc
from .app_state_store import set_json
from .decision_store import record_decision

log = get_logger("review.finalize")

_EDIT_PROMPT = (
    "Reply with new metadata, one field per line, e.g.:\n"
    "title: New title\ndescription: New description\ntags: tag1, tag2"
)


async def finalize_decision(
    ctx: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    video_id: int,
    code: str,
    reason: str | None,
    query=None,
) -> None:
    try:
        new_state = record_decision(video_id, code, reason=reason)
    except InvalidTransition:
        log.warning("stale decision tap for video %s (code=%s)", video_id, code)
        msg = "This video already moved past this review step."
        if query is not None:
            await query.edit_message_text(msg)
        else:
            await ctx.bot.send_message(chat_id, msg)
        return

    stamp = datetime.now(timezone.utc).strftime("%H:%M UTC")
    confirmation = f"{new_state.value.upper()} {stamp}\ndecision: {code}"
    if query is not None:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text(confirmation)
    else:
        await ctx.bot.send_message(chat_id, confirmation)

    if code.startswith(dc.EDIT_PREFIX):
        set_json(f"edit_pending:{chat_id}", {"video_id": video_id})
        await ctx.bot.send_message(chat_id, _EDIT_PROMPT)
