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
from ..db.models import Asset, Upload, Video
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
        # Gate BEFORE any quota/checkpoint work: a fallback-voiced draft is never publishable
        # (mixed/inconsistent narrator voice is itself an inauthenticity signal) -- refuse
        # immediately rather than spending upload quota on something `revoice` must redo anyway.
        if video.needs_revoice:
            raise ValueError(
                f"video {video_id} needs re-voice with the brand voice before publish "
                f"(run `operator revoice --video-id {video_id}`)"
            )
        video_path, thumb_path, script_path = video.video_path, video.thumb_path, video.script_path
        state, title, tags, description = video.state, video.title, video.tags, video.description
        kind, parent_id = video.kind, video.parent_id
        existing = s.scalar(
            select(Upload).where(Upload.video_id == video_id).order_by(Upload.id.desc())
        )
        existing_yt_id = existing.youtube_video_id if existing else None

        # A Short funnels viewers to its parent — publishing one before the parent is live
        # would ship a dead link, so the parent's YouTube id is a hard prerequisite.
        parent_youtube_id = None
        sibling_youtube_id = None
        if kind == "short":
            parent_youtube_id = s.scalar(
                select(Upload.youtube_video_id).where(Upload.video_id == parent_id)
            )
            if not parent_youtube_id:
                raise ValueError(
                    f"short {video_id}: parent video {parent_id} is not on YouTube yet — "
                    f"publish the parent first"
                )
            # Newest LIVE sibling short -> one description cross-link. Backward-only: the
            # new short links an older live one; published descriptions are never edited.
            # A sibling still scheduled in the future is skipped -- its link would 404
            # (private) until its publish_at passes.
            now = datetime.now(timezone.utc)
            sibling_youtube_id = s.scalar(
                select(Upload.youtube_video_id)
                .join(Video, Video.id == Upload.video_id)
                .where(
                    Video.parent_id == parent_id, Video.id != video_id, Video.kind == "short",
                    Upload.youtube_video_id.is_not(None),
                    (Upload.publish_at.is_(None)) | (Upload.publish_at <= now),
                )
                .order_by(Upload.id.desc())
            )

    cached = checkpoint.artifacts_of(video_id, _STEP)
    youtube_video_id = existing_yt_id or (cached or {}).get("youtube_video_id")

    script = (
        metadata_builder.load_script(script_path)
        if script_path
        # No script.json (e.g. a manually-seeded upload): the on-the-wire `title_options`
        # shape is always list[{title, thumbnail_text}] dicts — never bare strings, or the
        # dict-access consumers below (pick_title, ab_variants) crash.
        else {
            "title_options": [{"title": title, "thumbnail_text": ""}] if title else [],
            "tags": tags or [],
            "description": description or "",
            "sources": [],
        }
    )
    # Operator edits (title/description/tags) are written to the DB Video row only (by the
    # review bot), so they must override the original script.json here — otherwise a
    # review-time correction is silently dropped and the uncorrected metadata ships.
    # script.json-only fields (e.g. sources) are preserved. Keep the dict shape: promote the
    # operator title to the front, drop any existing option with the same title.
    if title:
        script["title_options"] = [
            {"title": title, "thumbnail_text": ""},
            *[o for o in script.get("title_options", []) if o.get("title") != title],
        ]
    if description:
        script["description"] = description
    if tags:
        script["tags"] = tags
    # Archival-image attributions from Asset rows -> description credit block. CC BY lines
    # are a license requirement; PD/CC0 gets one provenance line. Same delivery path as
    # `music_credit`: injected into the script dict, rendered by build_description.
    script["image_credits"] = _image_credits(video_id)

    if youtube_video_id is None:
        if not video_path:
            raise ValueError(f"video {video_id} has no video_path")
        assert_transition(state, VideoState.PUBLISHED)  # fail fast, before spending quota
        quota_throttle.ensure_can_publish(kind=kind)  # weekly cadence cap: main only

        body = metadata_builder.build_upload_body(
            script,
            publish_at_iso=publish_at_iso,
            category_id=settings.YT_CATEGORY_ID,
            title_override=title_override,
            kind=kind,
            parent_youtube_id=parent_youtube_id,
            sibling_youtube_id=sibling_youtube_id,
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
    _try_enqueue_shorts(video_id)
    return youtube_video_id


def _image_credits(video_id: int) -> list[str]:
    """Attribution lines for the video's archival stills (Asset kind='archival').

    The asset row's license field holds `license | artist | file page URL` (written by
    asset_store.save_archival). CC BY / CC BY-SA require a full credit line; PD/CC0 need
    none, so all PD files collapse into one provenance line to save description space."""
    with SessionLocal() as s:
        rows = s.execute(
            select(Asset.license).where(Asset.video_id == video_id, Asset.kind == "archival")
        ).scalars().all()
    credits: list[str] = []
    public_domain_seen = False
    for lic in rows:
        parts = [p.strip() for p in (lic or "").split("|")]
        if len(parts) != 3:
            continue
        short, artist, page = parts
        if short.lower().startswith(("cc by", "cc-by")):
            credits.append(f"{artist} — {short} — {page}")
        else:
            public_domain_seen = True
    if public_domain_seen:
        credits.append("Public-domain photographs via Wikimedia Commons")
    return list(dict.fromkeys(credits))  # dedupe (same author across beats), keep order


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


def _try_enqueue_shorts(video_id: int) -> None:
    """A freshly-published MAIN video queues one gen-shorts job (the scheduler drains it).
    Kind-guarded so a published short never spawns shorts; best-effort — a queue hiccup
    must never fail a completed publish."""
    try:
        with SessionLocal() as s:
            video = s.get(Video, video_id)
            if video is None or video.kind != "main":
                return
            has_children = s.scalar(
                select(Video.id).where(Video.parent_id == video_id).limit(1)
            )
        if has_children:
            return
        from ..web.job_queue import enqueue  # local import: publisher must not need web at load

        enqueue("gen-shorts", video_id=video_id)
        log.info("enqueued gen-shorts for published main %s", video_id)
    except Exception as exc:  # deliberately broad: shorts are a follow-up, not part of publish
        log.warning("gen-shorts enqueue skipped for video %s (non-blocking): %s", video_id, exc)


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
