"""Operational tables: analytics, KV app-state, cost ledger, topic embedding history."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow


class Analytics(Base):
    """Per-video metric snapshot pulled from YouTube Analytics API (phase 07)."""

    __tablename__ = "analytics"

    id: Mapped[int] = mapped_column(primary_key=True)
    youtube_video_id: Mapped[str] = mapped_column(String(32), index=True)
    as_of_date: Mapped[date] = mapped_column(Date)
    views: Mapped[int] = mapped_column(Integer, default=0)
    watch_time_min: Mapped[float] = mapped_column(Float, default=0.0)
    avg_view_pct: Mapped[float] = mapped_column(Float, default=0.0)   # retention %
    ctr: Mapped[float] = mapped_column(Float, default=0.0)
    rpm: Mapped[float] = mapped_column(Float, default=0.0)
    est_revenue: Mapped[float] = mapped_column(Float, default=0.0)
    raw: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RetentionCurve(Base):
    """Audience-retention curve buckets (YouTube Analytics `audienceWatchRatio` per
    `elapsedVideoTimeRatio`). The API returns a cumulative snapshot, so each pull REPLACES
    a video's rows wholesale — history would only duplicate the same converging curve."""

    __tablename__ = "retention_curve"

    id: Mapped[int] = mapped_column(primary_key=True)
    youtube_video_id: Mapped[str] = mapped_column(String(32), index=True)
    elapsed_ratio: Mapped[float] = mapped_column(Float)              # 0.0-1.0 bucket position
    watch_ratio: Mapped[float] = mapped_column(Float, default=0.0)   # can exceed 1.0 (rewatches)
    relative_perf: Mapped[float | None] = mapped_column(Float, default=None)  # vs YT average
    pulled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppState(Base):
    """Simple KV store: daily quota used, last_publish_at, weekly_count, etc."""

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(String(1000), default=None)


class CostLedger(Base):
    """Running cost record — budget guard sums actual_cost WHERE ym=current month."""

    __tablename__ = "cost_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id"), default=None)
    step: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(24))   # elevenlabs|anthropic|openai|fal|...
    units: Mapped[float] = mapped_column(Float, default=0.0)  # chars or tokens
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost: Mapped[float | None] = mapped_column(Float, default=None)
    ym: Mapped[str] = mapped_column(String(7), index=True)    # YYYY-MM
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TopicHistory(Base):
    """Embedding of every produced topic — semantic dedup (cosine >= threshold)."""

    __tablename__ = "topic_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_name: Mapped[str] = mapped_column(String(300))
    embedding: Mapped[bytes] = mapped_column(LargeBinary)   # float32[384] as raw bytes
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    """Single-table work queue. The web control panel writes `pending` rows; the scheduler's
    drain loop claims and runs them against the existing pipeline (web never runs heavy work).
    `idempotency_key` collapses double-clicks: enqueue reuses an existing pending/running row
    with the same key instead of inserting a duplicate."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    command: Mapped[str] = mapped_column(String(40), index=True)  # gen-audio|assemble|publish|...
    video_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id"), default=None)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), default=None)
    params: Mapped[dict | None] = mapped_column(JSON, default=None)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)  # pending|running|done|failed
    idempotency_key: Mapped[str] = mapped_column(String(120), index=True)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
