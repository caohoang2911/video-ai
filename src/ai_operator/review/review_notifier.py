"""Send a rendered video to the reviewer's Telegram chat and open the TIER-1 policy gate.

Uploads of a ~10-min 1080p mp4 can exceed what Telegram's Bot API upload path handles
smoothly, so we host the file at a URL and hand Telegram that URL instead of the raw
bytes (`send_video(video=url)`); a few retries, then a plain-link fallback message, so
the gate never silently stalls because of a single flaky send.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from telegram import Bot
from telegram.error import TelegramError

from ..config import settings
from ..db import SessionLocal, VideoState, assert_transition
from ..db.models import Video
from ..logging_setup import get_logger
from .caption import build_caption
from .keyboards import tier1_keyboard
from .media_host import get_media_url

log = get_logger("review.notifier")

_SEND_ATTEMPTS = 3


def notify(video_id: int) -> None:
    """Push `video_id` (state=rendered, or re-notify from editing) to the reviewer chat.

    Sets `videos.state=pending_review` once the message (or its link fallback) is sent.
    """
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not configured")

    with SessionLocal() as s:
        video = s.get(Video, video_id)
        if video is None:
            raise ValueError(f"video {video_id} not found")
        if not video.video_path:
            raise ValueError(f"video {video_id} has no video_path (not rendered yet)")
        # Fail fast before any network call. Idempotent: a video already PENDING_REVIEW
        # (operator re-sends the preview) has no self-loop, so only assert when advancing.
        if video.state != VideoState.PENDING_REVIEW.value:
            assert_transition(video.state, VideoState.PENDING_REVIEW)
        video_path = Path(video.video_path)
        caption = build_caption(video)

    url = get_media_url(video_id, video_path)
    keyboard = tier1_keyboard(video_id, preview_url=url)

    sent = asyncio.run(_send(url, caption, keyboard))
    if not sent:
        raise RuntimeError(f"could not notify reviewer for video {video_id} (all send attempts failed)")

    with SessionLocal() as s:
        video = s.get(Video, video_id)
        video.state = VideoState.PENDING_REVIEW.value
        s.commit()


async def _send(url: str, caption: str, keyboard) -> bool:
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    for attempt in range(_SEND_ATTEMPTS):
        try:
            await bot.send_video(
                chat_id=settings.TELEGRAM_CHAT_ID,
                video=url,
                caption=caption,
                reply_markup=keyboard,
                supports_streaming=True,
            )
            return True
        except TelegramError:
            log.warning("send_video attempt %d/%d failed", attempt + 1, _SEND_ATTEMPTS, exc_info=True)
            await asyncio.sleep(2**attempt)

    try:
        await bot.send_message(
            chat_id=settings.TELEGRAM_CHAT_ID,
            text=f"{caption}\n\nPreview: {url}",
            reply_markup=keyboard,
        )
        return True
    except TelegramError:
        log.exception("fallback send_message also failed")
        return False
