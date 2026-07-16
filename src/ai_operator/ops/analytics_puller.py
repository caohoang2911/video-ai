"""Pull per-video metrics from the YouTube Analytics API into the `analytics` table.

Read-only (no budget). Runs daily; early windows for a fresh upload legitimately return no
rows, which is tolerated (skipped, not an error). Requires the `yt-analytics.readonly` scope
already granted at authorize time; unconfigured is a safe no-op.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import delete, select

from ..config import settings
from ..db.engine import SessionLocal
from ..db.models import Upload
from ..db.models_ops import Analytics, RetentionCurve
from ..logging_setup import get_logger
from . import channel_stats

log = get_logger("ops.analytics_puller")

_METRICS = "views,estimatedMinutesWatched,averageViewPercentage"
# Thumbnail impressions CTR — queried separately (see _query_ctr): impressions data is often
# missing for a fresh/low-reach upload, and keeping it off the core query means such a video
# still records views/retention instead of the whole pull failing on a CTR-metric quirk.
_CTR_METRICS = "impressions,impressionsClickThroughRate"
# Bucketed retention curve (which SECOND loses viewers, not just the average). Optional like
# CTR: only queried once a video has enough traffic for the curve to mean anything — below
# the threshold the buckets are a handful of sessions, pure noise, and a wasted API call.
_RETENTION_METRICS = "audienceWatchRatio,relativeRetentionPerformance"
RETENTION_MIN_VIEWS = 200


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


def _query_ctr(service, youtube_video_id: str, as_of: date) -> float | None:
    """Thumbnail impressions CTR (%) for a video, or None when it can't be measured yet.

    impressionsClickThroughRate is already percentage-scaled (0-100), matching
    averageViewPercentage and validation's PASS_CTR_PCT. Optional: any failure or empty
    result leaves CTR unmeasured (callers keep the row's default) rather than aborting."""
    try:
        resp = service.reports().query(
            ids="channel==MINE", startDate="2005-01-01", endDate=as_of.isoformat(),
            metrics=_CTR_METRICS, filters=f"video=={youtube_video_id}",
        ).execute()
    except Exception as exc:  # noqa: BLE001 - CTR is optional; never break the core pull
        log.info("analytics: CTR unavailable for %s: %s", youtube_video_id, exc)
        return None
    rows = resp.get("rows") or []
    if not rows:
        return None
    ctr = (rows[0] + [0, 0])[1]  # row = [impressions, impressionsClickThroughRate]
    return float(ctr)


def _query_retention(service, youtube_video_id: str, as_of: date) -> list[dict]:
    """Retention buckets for one video: [{elapsed_ratio, watch_ratio, relative_perf}].
    Optional like CTR — any failure or empty result returns [] and the core pull goes on."""
    try:
        resp = service.reports().query(
            ids="channel==MINE", startDate="2005-01-01", endDate=as_of.isoformat(),
            metrics=_RETENTION_METRICS, dimensions="elapsedVideoTimeRatio",
            filters=f"video=={youtube_video_id}",
        ).execute()
    except Exception as exc:  # noqa: BLE001 - curve is optional; never break the core pull
        log.info("analytics: retention curve unavailable for %s: %s", youtube_video_id, exc)
        return []
    out = []
    for row in resp.get("rows") or []:
        row = list(row) + [None, None]
        out.append({
            "elapsed_ratio": float(row[0]),
            "watch_ratio": float(row[1] or 0.0),
            "relative_perf": None if row[2] is None else float(row[2]),
        })
    return out


def _replace_curve(youtube_video_id: str, points: list[dict]) -> None:
    """Swap a video's curve rows for the fresh snapshot in one transaction."""
    with SessionLocal() as s:
        s.execute(delete(RetentionCurve).where(RetentionCurve.youtube_video_id == youtube_video_id))
        s.add_all(RetentionCurve(youtube_video_id=youtube_video_id, **p) for p in points)
        s.commit()


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
        if metrics.get("ctr") is not None:  # only overwrite when measured -> keep a prior good value
            row.ctr = metrics["ctr"]
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
            ctr = _query_ctr(service, yt_id, as_of)
            if ctr is not None:
                metrics["ctr"] = ctr
            _upsert(yt_id, as_of, metrics)  # inside the try -> one video's write failure can't abort the rest
            written += 1
            if metrics["views"] >= RETENTION_MIN_VIEWS:
                points = _query_retention(service, yt_id, as_of)
                if points:
                    _replace_curve(yt_id, points)
        except Exception as exc:  # noqa: BLE001
            log.warning("analytics update failed for %s: %s", yt_id, exc)

    # Channel-level snapshot (subscribers/total views/videos) — separate, optional: its failure
    # must never discard the per-video rows just written.
    try:
        channel_stats.pull_channel_stats()
    except Exception as exc:  # noqa: BLE001
        log.warning("analytics: channel-stats fetch failed: %s", exc)
    return written
