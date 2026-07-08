"""Expose a rendered final.mp4 as an HTTP(S) URL for Telegram's send_video(video=url).

Preferred: Cloudflare R2 (S3-compatible) presigned GET — it expires, so a leaked link
doesn't leave the unpublished cut world-readable forever (see phase security notes).
Falls back to a local static file server (dev/localhost only; needs a public IP or
tunnel for Telegram's servers to actually reach it — acceptable P0 limitation).

R2 is configured via plain env vars (not `ai_operator.config.settings`, which is a
foundation file this phase must not edit): R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME, optional R2_PRESIGN_EXPIRY_SEC (default 24h).
"""

from __future__ import annotations

import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import load_dotenv

from ..config import OUTPUT_DIR
from ..logging_setup import get_logger

log = get_logger("review.media_host")

# R2_* aren't part of ai_operator.config.Settings (foundation-owned schema this phase must
# not extend), so load .env into os.environ ourselves to read them — no-op if already loaded.
load_dotenv()

_server_lock = threading.Lock()
_server_started = False


def get_media_url(video_id: int, local_path: Path) -> str:
    """Return a URL Telegram can fetch `local_path` from. R2 first, local server fallback."""
    url = _r2_presigned_url(video_id, local_path)
    if url:
        return url
    return _local_http_url(local_path)


def _r2_presigned_url(video_id: int, local_path: Path) -> str | None:
    account_id = os.environ.get("R2_ACCOUNT_ID")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket = os.environ.get("R2_BUCKET_NAME")
    if not (account_id and access_key and secret_key and bucket):
        return None  # R2 not configured -> caller falls back to the local server

    try:
        import boto3  # optional runtime dep: only needed when R2 env vars are set
    except ImportError:
        log.warning("R2 env vars set but boto3 not installed; falling back to local host")
        return None

    expiry = int(os.environ.get("R2_PRESIGN_EXPIRY_SEC", "86400"))
    key = f"{video_id}/{local_path.name}"
    try:
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        client.upload_file(str(local_path), bucket, key)
        return client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expiry
        )
    except Exception:
        log.exception("R2 upload/presign failed for video %s; falling back to local host", video_id)
        return None


def _local_http_url(local_path: Path) -> str:
    port = int(os.environ.get("MEDIA_HOST_PORT", "8090"))
    _ensure_server_started(port)
    base = os.environ.get("MEDIA_HOST_PUBLIC_URL", f"http://localhost:{port}")
    rel = local_path.relative_to(OUTPUT_DIR).as_posix()
    return f"{base.rstrip('/')}/{rel}"


def _ensure_server_started(port: int) -> None:
    global _server_started
    with _server_lock:
        if _server_started:
            return
        handler = partial(SimpleHTTPRequestHandler, directory=str(OUTPUT_DIR))
        httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
        thread = threading.Thread(target=httpd.serve_forever, name="media-host", daemon=True)
        thread.start()
        _server_started = True
        log.info("local media host serving %s on port %d", OUTPUT_DIR, port)
