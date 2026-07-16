"""Read-layer that assembles everything the analytics UI needs from existing data: channel
totals (Phase-1 snapshot), per-video latest rows, top/worst ranking, cumulative trend series
(from the daily `analytics` rows), and freshness. Pure/read-only — same dict serves HTML + JSON.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select

from ..db.engine import SessionLocal
from ..db.models import Upload, Video
from ..db.models_ops import Analytics
from ..ops import channel_stats
from ..ops.health import latest_analytics_per_video  # single source for "newest per video"

_TOP_N = 5


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, (datetime, date)) else v


def _kind_by_yt_id() -> dict[str, str]:
    """youtube_video_id -> videos.kind (main|short) so analytics rows can be labeled.
    Analytics rows only key on the YouTube id; the kind lives on the uploaded Video."""
    with SessionLocal() as s:
        return dict(
            s.execute(
                select(Upload.youtube_video_id, Video.kind)
                .join(Video, Video.id == Upload.video_id)
                .where(Upload.youtube_video_id.is_not(None))
            ).all()
        )


def _per_video(rows: list[Analytics], kinds: dict[str, str]) -> list[dict]:
    return [
        {
            "youtube_video_id": a.youtube_video_id,
            "kind": kinds.get(a.youtube_video_id),  # None when the upload row is gone
            "as_of_date": _iso(a.as_of_date),
            "views": a.views,
            "avg_view_pct": a.avg_view_pct,
            "ctr": a.ctr,
        }
        for a in rows
    ]


def trend_series() -> dict:
    """Per-pull-date channel series from the daily rows. `views` is a CUMULATIVE-to-date snapshot
    per video, so summing per date gives channel cumulative views over time; retention/CTR are
    averaged across the videos measured that date."""
    with SessionLocal() as s:
        rows = s.scalars(select(Analytics).order_by(Analytics.as_of_date)).all()
    by_date: dict[Any, dict] = {}
    for a in rows:
        d = by_date.setdefault(a.as_of_date, {"views": 0, "ret": [], "ctr": []})
        d["views"] += a.views
        d["ret"].append(a.avg_view_pct)
        if a.ctr:
            d["ctr"].append(a.ctr)
    dates = sorted(by_date)

    def _avg(xs: list[float]) -> float:
        return round(sum(xs) / len(xs), 1) if xs else 0.0

    return {
        "dates": [_iso(d) for d in dates],
        "views": [by_date[d]["views"] for d in dates],
        "retention": [_avg(by_date[d]["ret"]) for d in dates],
        "ctr": [round(_avg(by_date[d]["ctr"]), 2) for d in dates],
    }


def _freshness() -> dict:
    with SessionLocal() as s:
        last = s.scalar(select(func.max(Analytics.created_at)))
    channel = channel_stats.load_channel_stats() or {}
    return {"last_pull": _iso(last), "channel_fetched_at": channel.get("fetched_at")}


def overview() -> dict:
    """Everything the /analytics page + dashboard need, JSON-safe."""
    latest = latest_analytics_per_video()
    per_video = _per_video(latest, _kind_by_yt_id())
    ranked = sorted(per_video, key=lambda v: v["views"], reverse=True)
    return {
        "channel": channel_stats.load_channel_stats(),  # None until first pull
        "freshness": _freshness(),
        "per_video": per_video,
        "top": ranked[:_TOP_N],
        "worst": [v for v in reversed(ranked[-_TOP_N:])] if len(ranked) > _TOP_N else [],
        "trend": trend_series(),
    }
