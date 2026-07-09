"""Pull per-video metrics from the YouTube Analytics API into the `analytics` table.

Read-only (no budget). Runs daily; early windows for a fresh upload legitimately return no
rows, which is tolerated (skipped, not an error). Requires the `yt-analytics.readonly` scope
already granted at authorize time; unconfigured is a safe no-op.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select

from ..config import settings
from ..db.engine import SessionLocal
from ..db.models import Upload
from ..db.models_ops import Analytics
from ..logging_setup import get_logger

log = get_logger("ops.analytics_puller")

_METRICS = "views,estimatedMinutesWatched,averageViewPercentage"


def _service():
    from googleapiclient.discovery import build

    from ..publisher.oauth_headless import build_credentials

    return build("youtubeAnalytics", "v2", credentials=build_credentials(), cache_discovery=False)


def _query_video(service, youtube_video_id: str, as_of: date) -> dict | None:
    """One Analytics row for a video, or None when the API has no data yet (fresh upload)."""
    resp = service.reports().query(
        ids="channel==MINE", startDate="2005-01-01", endDate=as_of.isoformat(),
        metrics=_METRICS, filters=f"video=={youtube_video_id}",
    ).execute()
    rows = resp.get("rows") or []
    if not rows:
        return None
    views, minutes, avg_pct = (rows[0] + [0, 0, 0])[:3]
    return {"views": int(views), "watch_time_min": float(minutes), "avg_view_pct": float(avg_pct)}


def _upsert(youtube_video_id: str, as_of: date, metrics: dict) -> None:
    with SessionLocal() as s:
        row = s.scalar(
            select(Analytics).where(
                Analytics.youtube_video_id == youtube_video_id, Analytics.as_of_date == as_of
            )
        )
        if row is None:
            row = Analytics(youtube_video_id=youtube_video_id, as_of_date=as_of)
            s.add(row)
        row.views = metrics["views"]
        row.watch_time_min = metrics["watch_time_min"]
        row.avg_view_pct = metrics["avg_view_pct"]
        s.commit()


def pull_all(as_of: date | None = None) -> int:
    """Refresh analytics for every uploaded video; returns how many rows were written."""
    if settings.missing(["YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"]):
        log.info("analytics: YouTube not fully configured -> skipping")
        return 0
    as_of = as_of or datetime.now(timezone.utc).date()  # UTC to match the scheduler's clock

    with SessionLocal() as s:
        yt_ids = [
            u.youtube_video_id for u in s.scalars(select(Upload).where(Upload.youtube_video_id.is_not(None)))
        ]
    if not yt_ids:
        return 0

    service = _service()
    written = 0
    for yt_id in yt_ids:
        try:
            metrics = _query_video(service, yt_id, as_of)
            if metrics is None:
                continue  # no data yet for this (fresh) upload
            _upsert(yt_id, as_of, metrics)  # inside the try -> one video's write failure can't abort the rest
            written += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("analytics update failed for %s: %s", yt_id, exc)
    return written
