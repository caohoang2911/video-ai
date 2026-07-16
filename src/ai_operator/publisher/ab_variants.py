"""Manual YouTube Studio A/B workflow.

YouTube's "Test & Compare" (title/thumbnail A/B) is Studio-only — there is no
public API to submit variants or read a winner. Instead: print a checklist for a
human to set the test up in Studio, and expose `set_winner` so the human-observed
result gets recorded for phase 07 to feed back into topic/thumbnail generation.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from ..db.engine import SessionLocal
from ..db.models import Upload
from ..logging_setup import get_logger

log = get_logger("publisher.ab")


def discover_thumb_variants(video_path: str) -> list[str]:
    """Find phase-04 thumbnail variants (thumb_a/b/c.jpg) next to the rendered video."""
    out_dir = Path(video_path).parent
    candidates = (out_dir / f"thumb_{c}.jpg" for c in ("a", "b", "c"))
    return [str(p) for p in candidates if p.exists()]


def _latest_upload(s, video_id: int) -> Upload | None:
    return s.scalar(
        select(Upload).where(Upload.video_id == video_id).order_by(Upload.id.desc())
    )


def submit(video_id: int, title_options: list[dict], thumb_paths: list[str]) -> None:
    """Print the manual Studio A/B checklist and mark `ab_status='running'`.

    Idempotent: once `ab_status` is set, a second call is a no-op — a Studio test
    can only be observed and recorded here, not re-submitted through this CLI.
    """
    with SessionLocal() as s:
        upload_row = _latest_upload(s, video_id)
        if upload_row is None:
            log.warning("no upload row for video %s — publish before submitting A/B", video_id)
            return
        if upload_row.ab_status:
            log.info("A/B already %s for video %s — skipping re-submit", upload_row.ab_status, video_id)
            return
        upload_row.ab_status = "running"
        s.commit()

    _print_checklist(video_id, title_options, thumb_paths)


def _print_checklist(video_id: int, title_options: list[dict], thumb_paths: list[str]) -> None:
    lines = [
        f"--- Manual YouTube Studio A/B checklist (video_id={video_id}) ---",
        "1. Open YouTube Studio -> Content -> select this video -> 'Test & compare'.",
        "2. Title test: add these variants (2-3):",
        # title_options are {title, thumbnail_text} dicts loaded from script.json (or built
        # dict-shaped in publish.py) — read the title, never render the whole dict.
        *[f"   - {t.get('title', '')}" for t in title_options[:3]],
        "3. Thumbnail test: upload these variants:",
        *[f"   - {p}" for p in thumb_paths[:3]],
        "4. After YouTube finishes the test, record the winner with:",
        f"   operator set-winner --video-id {video_id} --title \"<winning title>\" --thumb <winning thumb path>",
    ]
    print("\n".join(lines))
    log.info("printed manual Studio A/B checklist for video %s", video_id)


def mark_running(video_id: int) -> None:
    """Flag that the operator has set the Studio test up (ab_status='running'), so the panel
    can track which published videos have an active A/B test vs none. Idempotent."""
    with SessionLocal() as s:
        upload_row = _latest_upload(s, video_id)
        if upload_row is None:
            raise ValueError(f"no upload row for video {video_id}")
        upload_row.ab_status = "running"
        s.commit()


def set_winner(video_id: int, title: str | None = None, thumb: str | None = None) -> None:
    """Record the human-observed A/B winner (phase 07 reads this to close the loop)."""
    with SessionLocal() as s:
        upload_row = _latest_upload(s, video_id)
        if upload_row is None:
            raise ValueError(f"no upload row for video {video_id}")
        if title:
            upload_row.winning_title = title
        if thumb:
            upload_row.winning_thumbnail = thumb
        upload_row.ab_status = "done"
        s.commit()
    log.info("recorded A/B winner for video %s (title=%s, thumb=%s)", video_id, bool(title), bool(thumb))
