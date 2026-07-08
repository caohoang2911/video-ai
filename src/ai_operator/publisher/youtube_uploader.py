"""Resumable YouTube video upload with exponential backoff + restart-on-404.

A ~10-minute documentary upload can take minutes on a home connection; chunked
resumable upload lets a network blip retry just the current chunk instead of the
whole file, and only a 404 (expired ~7-day session URI) forces a full restart.
"""

from __future__ import annotations

import time

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from ..logging_setup import get_logger

log = get_logger("publisher.uploader")

CHUNK_SIZE = 8 * 1024 * 1024  # multiple of 256KB, per YouTube's resumable-upload requirement
MAX_CHUNK_RETRIES = 8
MAX_RESTARTS = 1  # one 404 restart; a second 404 in a row means something else is wrong


class _ResumableSessionExpired(Exception):
    """Internal signal: the resumable session URI 404'd — restart the whole upload."""


def upload(service, video_path: str, body: dict) -> str:
    """Upload `video_path` with `body` metadata; return the new YouTube video id."""
    for attempt in range(MAX_RESTARTS + 1):
        try:
            return _upload_once(service, video_path, body)
        except _ResumableSessionExpired:
            if attempt == MAX_RESTARTS:
                raise
            log.warning("resumable session expired (404) — restarting upload from scratch")
    raise AssertionError("unreachable: loop always returns or raises")


def _upload_once(service, video_path: str, body: dict) -> str:
    media = MediaFileUpload(video_path, mimetype="video/mp4", chunksize=CHUNK_SIZE, resumable=True)
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    retry = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                log.info("upload progress: %d%%", int(status.progress() * 100))
        except HttpError as exc:
            if exc.resp.status == 404:
                raise _ResumableSessionExpired from exc
            if exc.resp.status >= 500 and retry < MAX_CHUNK_RETRIES:
                sleep_s = min(2**retry, 64)
                log.warning(
                    "upload chunk failed (%s) — retry %d/%d in %ds",
                    exc.resp.status, retry, MAX_CHUNK_RETRIES, sleep_s,
                )
                time.sleep(sleep_s)
                retry += 1
                continue
            raise
    return response["id"]
