"""Weekly upload cadence + YouTube daily quota-unit guard.

YouTube's quota resets at midnight Pacific Time, not UTC — the "quota date" bucket
tracks the PT calendar date so the reset lines up with YouTube's own accounting.
Cadence (uploads/7 days) is checked against the `uploads` table directly so it
self-corrects even if `app_state` were ever wiped.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from ..config import settings
from ..constants import YT_COST_INSERT, YT_COST_THUMBNAIL, YT_QUOTA_ALERT_BELOW, YT_QUOTA_DAILY
from ..db.engine import SessionLocal
from ..db.models import Upload, Video
from ..db.models_ops import AppState
from ..logging_setup import get_logger

log = get_logger("publisher.quota")

_PT_OFFSET = timedelta(hours=-8)  # PST; DST drift (~1h) doesn't matter for a daily bucket
_QUOTA_DATE_KEY = "yt_quota_date"
_QUOTA_USED_KEY = "yt_quota_used"


class ThrottleExceeded(Exception):
    """Weekly upload cadence cap reached."""


class QuotaExceeded(Exception):
    """Not enough daily YouTube API quota units remaining."""


def _pt_today() -> str:
    return (datetime.now(timezone.utc) + _PT_OFFSET).strftime("%Y-%m-%d")


def uploads_last_7_days() -> int:
    """Count MAIN-video uploads with a confirmed youtube_video_id in the trailing 7 days.
    Shorts are excluded: the weekly cadence cap governs long-form only — shorts ride along
    with their parent and publish freely."""
    since = datetime.now(timezone.utc) - timedelta(days=7)
    with SessionLocal() as s:
        return s.scalar(
            select(func.count())
            .select_from(Upload)
            .join(Video, Video.id == Upload.video_id)
            .where(
                Upload.created_at >= since,
                Upload.youtube_video_id.is_not(None),
                Video.kind == "main",
            )
        ) or 0


def throttle_ok() -> bool:
    """True if another MAIN upload fits within the WEEKLY_VIDEO_CAP/7-day cadence."""
    return uploads_last_7_days() < settings.WEEKLY_VIDEO_CAP


def quota_used_today() -> int:
    with SessionLocal() as s:
        stored_date = s.get(AppState, _QUOTA_DATE_KEY)
        if stored_date is None or stored_date.value != _pt_today():
            return 0
        used = s.get(AppState, _QUOTA_USED_KEY)
        return int(used.value) if used and used.value else 0


def quota_remaining() -> int:
    return YT_QUOTA_DAILY - quota_used_today()


def reserve(units: int) -> int:
    """Record `units` spent against today's (PT) quota bucket; return remaining.

    The bucket auto-resets on PT date rollover — every call re-checks the stored
    date, so no cron/reset job is needed.
    """
    today = _pt_today()
    with SessionLocal() as s:
        date_row = s.get(AppState, _QUOTA_DATE_KEY)
        used_row = s.get(AppState, _QUOTA_USED_KEY)
        same_day = date_row is not None and date_row.value == today
        used = (int(used_row.value) if same_day and used_row and used_row.value else 0) + units

        if date_row is None:
            s.add(AppState(key=_QUOTA_DATE_KEY, value=today))
        else:
            date_row.value = today
        if used_row is None:
            s.add(AppState(key=_QUOTA_USED_KEY, value=str(used)))
        else:
            used_row.value = str(used)
        s.commit()

    remaining = YT_QUOTA_DAILY - used
    if remaining < YT_QUOTA_ALERT_BELOW:
        log.warning("YT quota remaining %d < alert threshold %d", remaining, YT_QUOTA_ALERT_BELOW)
    return remaining


def reserve_insert() -> int:
    return reserve(YT_COST_INSERT)


def reserve_thumbnail() -> int:
    return reserve(YT_COST_THUMBNAIL)


def ensure_can_publish(kind: str = "main") -> None:
    """Raise if the daily quota is exhausted, or — for MAIN videos only — the weekly
    cadence cap is reached. Shorts skip the cadence cap but still spend quota units."""
    if kind == "main" and not throttle_ok():
        raise ThrottleExceeded(
            f"weekly cap reached ({settings.WEEKLY_VIDEO_CAP}/7d) — publish later"
        )
    if quota_remaining() < YT_COST_INSERT:
        raise QuotaExceeded(f"insufficient YT quota remaining ({quota_remaining()})")
