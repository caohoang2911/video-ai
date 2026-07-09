"""Monthly OAuth token keep-alive.

A YouTube refresh token from a Desktop OAuth client expires only if unused for ~6 months.
A running scheduler publishes often enough to keep it alive, but a quiet stretch (paused
channel, no approved videos) could let it lapse -- so refresh it on a fixed cadence regardless,
and alert loudly on failure since a dead token silently breaks every future upload.
"""

from __future__ import annotations

from ..config import settings
from ..logging_setup import get_logger

log = get_logger("ops.keepalive")


def refresh_token() -> bool:
    """Force an OAuth refresh; True on success, False when unconfigured. Raises are left to the
    caller (the scheduler job) to log as an alert -- a failed refresh is a real outage."""
    if settings.missing(["YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"]):
        log.info("keepalive: YouTube not fully configured -> skipping")
        return False
    # build_credentials() forces an immediate refresh up front (see its docstring), so simply
    # constructing it exercises the refresh token; a bad/expired token raises here.
    from ..publisher.oauth_headless import build_credentials

    build_credentials()
    log.info("keepalive: OAuth token refreshed OK")
    return True
