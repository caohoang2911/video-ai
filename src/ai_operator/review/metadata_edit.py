"""Apply a metadata-only edit (title / description / tags) to a Video row.

Extracted so BOTH transports reuse the same write: the Telegram bot parses a free-text reply
into fields (`parse_edit_text`), the web panel posts fields directly from a form — then both
call `apply_metadata_edit`. No re-render / re-TTS happens here (that would re-trigger paid API
calls); P0 edit scope is metadata only.
"""

from __future__ import annotations

from ..db.engine import SessionLocal
from ..db.models import Video
from ..logging_setup import get_logger

log = get_logger("review.metadata_edit")

_EDITABLE = ("title", "description", "tags")


def parse_edit_text(text: str) -> dict[str, str]:
    """Parse `field: value` lines into a {field: value} dict (title/description/tags)."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key in _EDITABLE:
            fields[key] = value.strip()
    return fields


def apply_metadata_edit(video_id: int, fields: dict[str, str]) -> bool:
    """Patch the Video's title/description/tags from `fields`. `tags` is a comma-separated
    string split into a list. Returns False if the video is missing, else True."""
    with SessionLocal() as s:
        video = s.get(Video, video_id)
        if video is None:
            log.warning("metadata edit for unknown video %s", video_id)
            return False
        if fields.get("title"):
            video.title = fields["title"]
        if fields.get("description") is not None and fields["description"] != "":
            video.description = fields["description"]
        if fields.get("tags") is not None:
            video.tags = [t.strip() for t in fields["tags"].split(",") if t.strip()]
        s.commit()
    log.info("metadata edited for video %s: %s", video_id, sorted(fields))
    return True
