"""Feed the human-observed A/B winners back into content selection.

YouTube's Test & Compare is Studio-only (no API), so a human records the winning title/
thumbnail via `set-winner`. This exposes those winners as a hint the content engine can bias
toward -- what actually won with the audience, not a guess.
"""

from __future__ import annotations

from sqlalchemy import select

from ..db.engine import SessionLocal
from ..db.models import Upload
from ..logging_setup import get_logger

log = get_logger("ops.feedback")


def winner_hints() -> dict:
    """`{winning_titles: [...], winning_thumbnails: [...]}` from recorded A/B winners.
    Newest last; empty lists when nothing has been recorded yet."""
    with SessionLocal() as s:
        rows = s.scalars(
            select(Upload).where(Upload.winning_title.is_not(None)).order_by(Upload.id)
        ).all()
    return {
        "winning_titles": [r.winning_title for r in rows if r.winning_title],
        "winning_thumbnails": [r.winning_thumbnail for r in rows if r.winning_thumbnail],
    }
