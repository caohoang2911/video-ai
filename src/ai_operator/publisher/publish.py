"""Orchestrates one video's publish: throttle/quota guard -> OAuth service -> body
-> resumable upload -> thumbnail -> DB writes -> state transition -> A/B checklist.

Idempotent at two layers: `checkpoint` (fast local record, closes the crash window
right after YouTube accepts the upload) and the `uploads` DB row (durable record
other phases read). Either one finding a prior youtube_video_id skips re-upload.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from .. import checkpoint
from ..config import settings
from ..db.engine import SessionLocal
from ..db.models import Upload, Video
from ..db.state_machine import VideoState, assert_transition
from ..logging_setup import get_logger
from . import ab_variants, metadata_builder, quota_throttle, thumbnail_setter, youtube_uploader
from .oauth_headless import build_service

log = get_logger("publisher.publish")

_STEP = "youtube_upload"


def publish(
    video_id: int,
    publish_at_iso: str | None = None,
    title_override: str | None = None,
) -> str:
    """Publish `video_id` (must be state=approved) to YouTube; return youtube_video_id."""
    publish_at_iso = _parse_publish_at(publish_at_iso)

    with SessionLocal() as s:
        video = s.get(Video, video_id)
        if video is None:
            raise ValueError(f"video {video_id} not found")
        video_path, thumb_path, script_path = video.video_path, video.thumb_path, video.script_path
        state, title, tags, description = video.state, video.title, video.tags, video.description
        existing = s.scalar(
            select(Upload).where(Upload.video_id == video_id).order_by(Upload.id.desc())
        )
        existing_yt_id = existing.youtube_video_id if existing else None

    cached = checkpoint.artifacts_of(video_id, _STEP)
    youtube_video_id = existing_yt_id or (cached or {}).get("youtube_video_id")

    script = (
        metadata_builder.load_script(script_path)
        if script_path
        else {
            "title_options": [title] if title else [],
            "tags": tags or [],
            "description": description or "",
            "sources": [],
        }
    )
    # Operator edits (title/description/tags) are written to the DB Video row only (by the
    # review bot), so they must override the original script.json here — otherwise a
    # review-time correction is silently dropped and the uncorrected metadata ships.
    # script.json-only fields (e.g. sources) are preserved.
    if title:
        script["title_options"] = [title, *[t for t in script.get("title_options", []) if t != title]]
    if description:
        script["description"] = description
    if tags:
        script["tags"] = tags

    if youtube_video_id is None:
        if not video_path:
            raise ValueError(f"video {video_id} has no video_path")
        assert_transition(state, VideoState.PUBLISHED)  # fail fast, before spending quota
        quota_throttle.ensure_can_publish()

        body = metadata_builder.build_upload_body(
            script,
            publish_at_iso=publish_at_iso,
            category_id=settings.YT_CATEGORY_ID,
            title_override=title_override,
        )
        service = build_service()
        youtube_video_id = youtube_uploader.upload(service, video_path, body)
        # persist the instant YouTube accepts the video — narrows the crash-retry window
        checkpoint.write(video_id, _STEP, {"youtube_video_id": youtube_video_id})
        quota_throttle.reserve_insert()

        if thumb_path and thumbnail_setter.set_thumbnail(service, youtube_video_id, thumb_path):
            quota_throttle.reserve_thumbnail()

        log.info("published video %s -> youtube %s", video_id, youtube_video_id)
    else:
        log.info("video %s already uploaded as %s — skipping upload", video_id, youtube_video_id)

    _ensure_upload_row(video_id, youtube_video_id, publish_at_iso)
    _try_submit_ab(video_id, video_path, script)
    return youtube_video_id


def _ensure_upload_row(video_id: int, youtube_video_id: str, publish_at_iso: str) -> None:
    """Create the `uploads` row + flip state to published, unless already recorded."""
    with SessionLocal() as s:
        already = s.scalar(
            select(Upload).where(
                Upload.video_id == video_id, Upload.youtube_video_id == youtube_video_id
            )
        )
        video = s.get(Video, video_id)
        if video is not None and video.state != VideoState.PUBLISHED.value:
            assert_transition(video.state, VideoState.PUBLISHED)
            video.state = VideoState.PUBLISHED.value

        if already is None:
            s.add(
                Upload(
                    video_id=video_id,
                    youtube_video_id=youtube_video_id,
                    publish_at=datetime.fromisoformat(publish_at_iso.replace("Z", "+00:00")),
                    privacy="private",
                    status="scheduled",
                )
            )
        s.commit()


def _try_submit_ab(video_id: int, video_path: str | None, script: dict) -> None:
    """Best-effort Studio A/B checklist submission — never fails a publish."""
    try:
        thumbs = ab_variants.discover_thumb_variants(video_path) if video_path else []
        ab_variants.submit(video_id, script.get("title_options") or [], thumbs)
    except Exception as exc:  # deliberately broad: A/B bookkeeping must never fail a publish
        log.warning("A/B submit skipped for video %s (non-blocking): %s", video_id, exc)


def _parse_publish_at(value: str | None) -> str:
    """Normalize to ISO-8601 UTC with a 'Z' suffix (YouTube's expected format).
    Defaults to "now" — still requires privacyStatus=private per the API, which
    then flips to public at that instant automatically."""
    if not value:
        dt = datetime.now(timezone.utc)
    else:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")
