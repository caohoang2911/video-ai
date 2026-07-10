"""Channel-level stats (subscribers, total views, video count) from the YouTube Data API v3,
cached as a single snapshot in AppState.

Read-only, no budget; unconfigured OAuth is a safe no-op. Revenue/RPM is intentionally NOT
fetched here — that needs the `yt-analytics-monetary.readonly` scope, which this channel has
not granted (adding it would force a re-authorize). Subscribers/views/videos come from the
already-granted `youtube` scope.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..config import settings
from ..db.engine import SessionLocal
from ..db.models_ops import AppState
from ..logging_setup import get_logger

log = get_logger("ops.channel_stats")

_KEY = "channel_stats"
_YT_KEYS = ["YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"]


def pull_channel_stats() -> dict | None:
    """Fetch + persist channel statistics. Returns the snapshot dict, or None when OAuth is
    unconfigured or the API has nothing (never raises — analytics refresh must not break on it)."""
    if settings.missing(_YT_KEYS):
        log.info("channel_stats: YouTube not configured -> skipping")
        return None
    try:
        from ..publisher.oauth_headless import build_service  # deferred: needs OAuth libs + creds

        service = build_service()
        resp = service.channels().list(part="statistics", mine=True).execute()
    except Exception as exc:  # noqa: BLE001 - optional stat; log and no-op, don't abort the pull
        log.warning("channel_stats: fetch failed: %s", exc)
        return None

    items = resp.get("items") or []
    if not items:
        return None
    st = items[0].get("statistics", {})
    stats = {
        # subscriberCount is absent when a channel hides it -> default 0
        "subscribers": int(st.get("subscriberCount", 0) or 0),
        "total_views": int(st.get("viewCount", 0) or 0),
        "video_count": int(st.get("videoCount", 0) or 0),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(stats)
    log.info(
        "channel_stats: subs=%s views=%s videos=%s",
        stats["subscribers"], stats["total_views"], stats["video_count"],
    )
    return stats


def _save(stats: dict) -> None:
    with SessionLocal() as s:
        row = s.get(AppState, _KEY)
        if row is None:
            row = AppState(key=_KEY)
            s.add(row)
        row.value = json.dumps(stats)
        s.commit()


def load_channel_stats() -> dict | None:
    """Read the cached channel-stats snapshot for the web layer, or None if never pulled."""
    with SessionLocal() as s:
        row = s.get(AppState, _KEY)
    if row is None or not row.value:
        return None
    try:
        return json.loads(row.value)
    except (ValueError, TypeError):
        return None
