"""Core content + publish tables. Ops/analytics tables live in models_ops.py."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow
from .state_machine import VideoState


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(200), index=True)
    title: Mapped[str] = mapped_column(String(300))
    angle: Mapped[str | None] = mapped_column(Text, default=None)          # unique POV = originality
    source_notes: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(20), default="backlog")     # backlog|used|rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), default=None)
    state: Mapped[str] = mapped_column(String(24), default=VideoState.DRAFT.value, index=True)
    # unique work-unit key: blocks duplicate create/charge/upload on retry
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)

    # A Short is a first-class child Video walking the SAME lifecycle/review gate/publish
    # path as a main; `kind` is the only discriminator, `parent_id` links to its main video.
    kind: Mapped[str] = mapped_column(String(8), default="main", index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id"), default=None)

    script_path: Mapped[str | None] = mapped_column(String(500), default=None)
    audio_path: Mapped[str | None] = mapped_column(String(500), default=None)
    video_path: Mapped[str | None] = mapped_column(String(500), default=None)
    thumb_path: Mapped[str | None] = mapped_column(String(500), default=None)

    title: Mapped[str | None] = mapped_column(String(300), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    tags: Mapped[list | None] = mapped_column(JSON, default=None)
    duration_sec: Mapped[int | None] = mapped_column(Integer, default=None)
    reject_reason: Mapped[str | None] = mapped_column(Text, default=None)
    # True whenever the narration was NOT synthesized end-to-end with the brand ElevenLabs
    # voice (edge-tts fallback draft) -- the publisher refuses to upload while this is set,
    # since a mixed/inconsistent narrator voice is itself an inauthenticity signal.
    needs_revoice: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Asset(Base):
    """Every acquired media item — for royalty-free audit + md5 dedup."""

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))          # stock|gen|music|video_broll
    source: Mapped[str] = mapped_column(String(24))        # pexels|pixabay|sdxl|fal|audio_library
    url_or_path: Mapped[str] = mapped_column(String(1000))
    license: Mapped[str | None] = mapped_column(String(120), default=None)
    md5: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Upload(Base):
    """One YouTube upload attempt per video (idempotent via youtube_video_id)."""

    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), index=True)
    youtube_video_id: Mapped[str | None] = mapped_column(String(32), default=None)
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    privacy: Mapped[str] = mapped_column(String(12), default="private")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|scheduled|published|failed
    error: Mapped[str | None] = mapped_column(Text, default=None)
    # A/B winner feedback (phase 06/07). NOTE: Test&Compare is Studio-only (no API) —
    # these hold the manually-observed winner so phase 07 can feed it back to phase 02.
    winning_title: Mapped[str | None] = mapped_column(String(300), default=None)
    winning_thumbnail: Mapped[str | None] = mapped_column(String(500), default=None)
    ab_status: Mapped[str | None] = mapped_column(String(16), default=None)  # none|running|done
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Decision(Base):
    """Structured review decision audit trail (phase 05) — non-binary codes + reason."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), index=True)
    tier: Mapped[str] = mapped_column(String(12))            # policy|quality
    decision_code: Mapped[str] = mapped_column(String(40))   # PASS_POLICY, REJECT_POLICY_AUDIO, ...
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
