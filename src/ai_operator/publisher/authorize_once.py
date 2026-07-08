"""One-time manual OAuth bootstrap — mints the refresh token used at runtime.

Run interactively exactly once per Google account (`operator authorize`): it opens
a local browser consent screen, then prints the refresh_token to paste into `.env`
as `YT_REFRESH_TOKEN`. Nothing in the pipeline calls this at runtime — it exists
only because a human must consent once before headless publishing is possible.
"""

from __future__ import annotations

from google_auth_oauthlib.flow import InstalledAppFlow

from ..logging_setup import get_logger
from .oauth_headless import SCOPES

log = get_logger("publisher.authorize")

DEFAULT_CLIENT_SECRETS_PATH = "client_secret.json"


def run(client_secrets_path: str = DEFAULT_CLIENT_SECRETS_PATH) -> str:
    """Launch the local-server OAuth consent flow; return (and print) refresh_token.

    `client_secrets_path` is the OAuth "Desktop app" JSON downloaded from Google
    Cloud Console (gitignored, never committed). `prompt=consent` forces Google to
    reissue a refresh_token even on a repeat authorization of the same account —
    otherwise a second run can silently omit it.
    """
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not creds.refresh_token:
        raise RuntimeError(
            "No refresh_token returned. Revoke prior access at "
            "https://myaccount.google.com/permissions and re-run — Google only "
            "issues a refresh_token when consent is freshly granted."
        )
    print("YT_REFRESH_TOKEN=" + creds.refresh_token)
    log.info("authorization complete — refresh_token minted (value not logged)")
    return creds.refresh_token
