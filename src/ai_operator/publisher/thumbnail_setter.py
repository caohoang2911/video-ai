"""Custom thumbnail upload — best-effort, never blocks publishing.

`thumbnails.set` does not require phone verification per current YouTube docs, but
permission/quota errors are still treated as non-fatal: a missing custom thumbnail
is a cosmetic loss, not a reason to fail an otherwise-successful publish.
"""

from __future__ import annotations

import os

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from ..logging_setup import get_logger

log = get_logger("publisher.thumbnail")

MAX_THUMB_BYTES = 2 * 1024 * 1024  # YouTube limit: <=2MB, JPEG/PNG (ideally 1280x720)


def set_thumbnail(service, youtube_video_id: str, thumb_path: str) -> bool:
    """Attempt to set the custom thumbnail; return True on success, False on any
    (logged) failure so the caller can continue the publish flow regardless."""
    try:
        size = os.path.getsize(thumb_path)
    except OSError as exc:
        log.warning("thumbnail file error for %s (non-blocking): %s", youtube_video_id, exc)
        return False

    if size > MAX_THUMB_BYTES:
        log.warning("thumbnail %s is %d bytes > 2MB cap — skipping", thumb_path, size)
        return False

    try:
        media = MediaFileUpload(thumb_path, mimetype="image/jpeg")
        service.thumbnails().set(videoId=youtube_video_id, media_body=media).execute()
        return True
    except HttpError as exc:
        log.warning("thumbnails.set failed for %s (non-blocking): %s", youtube_video_id, exc)
        return False
