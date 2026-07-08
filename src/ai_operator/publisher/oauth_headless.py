"""Headless OAuth: build an authenticated YouTube Data API v3 client from a stored
refresh token — no browser, no user interaction at runtime.

See `authorize_once.py` for the one-time interactive flow that mints the refresh
token in the first place (run manually, not part of the pipeline).
"""

from __future__ import annotations

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build

from ..config import settings
from ..logging_setup import get_logger

log = get_logger("publisher.oauth")

# Scopes cover upload + full manage (metadata/thumbnail edits) + analytics read
# (phase 07). Kept minimal — no broader "manage everything" scope requested.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

TOKEN_URI = "https://oauth2.googleapis.com/token"


class OAuthNotConfigured(Exception):
    """Raised when required YouTube OAuth settings are missing or the refresh
    token has been revoked/expired (6 months of inactivity kills it)."""


def _require_config() -> None:
    missing = settings.missing(["YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"])
    if missing:
        raise OAuthNotConfigured(f"missing settings: {', '.join(missing)}")


def build_credentials() -> Credentials:
    """Construct refresh-token Credentials and force an immediate refresh.

    `token=None` means the credentials start invalid, so every call needs one
    refresh up front; after that, `googleapiclient` refreshes lazily on its own
    whenever the access token is about to expire.
    """
    _require_config()
    creds = Credentials(
        token=None,
        refresh_token=settings.YT_REFRESH_TOKEN,
        token_uri=TOKEN_URI,
        client_id=settings.YT_CLIENT_ID,
        client_secret=settings.YT_CLIENT_SECRET,
        scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
    except RefreshError as exc:
        # Never log the token itself — only the fact that auth failed.
        raise OAuthNotConfigured(f"refresh_token rejected by Google: {exc}") from exc
    return creds


def build_service() -> Resource:
    """Build an authenticated `youtube` v3 client resource."""
    creds = build_credentials()
    return build("youtube", "v3", credentials=creds, cache_discovery=False)
