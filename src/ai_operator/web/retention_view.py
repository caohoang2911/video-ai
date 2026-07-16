"""Read-layer for the video-detail retention panel: own-curve sparkline points (inline
SVG polyline, no JS charting), hook-zone readouts (% of starters still watching at 2/5/10s
-- the actionable numbers for hook iteration), and a sibling-shorts overlay so a parent
page compares its shorts' curves angle-vs-angle at a glance. Pure/read-only."""

from __future__ import annotations

from sqlalchemy import select

from ..db.engine import SessionLocal
from ..db.models import Upload, Video
from ..db.models_ops import Analytics, RetentionCurve

# Sparkline viewBox; y is clamped to watch_ratio 1.2 so overlaid curves share one scale
# (audienceWatchRatio exceeds 1.0 when loops/rewatches beat the video length).
_W, _H = 100.0, 40.0
_Y_MAX = 1.2
_HOOK_SECONDS = (2, 5, 10)


def _yt_id(s, video_id: int) -> str | None:
    return s.scalar(
        select(Upload.youtube_video_id)
        .where(Upload.video_id == video_id, Upload.youtube_video_id.is_not(None))
        .order_by(Upload.id.desc())
    )


def _curve(s, yt_id: str) -> list[RetentionCurve]:
    return list(s.scalars(
        select(RetentionCurve)
        .where(RetentionCurve.youtube_video_id == yt_id)
        .order_by(RetentionCurve.elapsed_ratio)
    ))


def _points(rows: list[RetentionCurve]) -> str:
    """`x,y x,y ...` for an SVG polyline in the fixed _W x _H viewBox."""
    pts = []
    for r in rows:
        x = r.elapsed_ratio * _W
        y = _H - (min(r.watch_ratio, _Y_MAX) / _Y_MAX) * _H
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def _at_ratio(rows: list[RetentionCurve], ratio: float) -> float:
    nearest = min(rows, key=lambda r: abs(r.elapsed_ratio - ratio))
    return round(nearest.watch_ratio * 100.0, 1)


def _hook_zone(rows: list[RetentionCurve], duration_sec: int | None) -> list[dict]:
    """% of starters still present N seconds in. Needs the video duration to translate
    seconds into the curve's elapsed-ratio axis."""
    if not duration_sec:
        return []
    return [
        {"sec": t, "pct": _at_ratio(rows, t / duration_sec)}
        for t in _HOOK_SECONDS if t < duration_sec
    ]


def retention_panel(video_id: int, duration_sec: int | None) -> dict | None:
    """Panel dict for video_detail.html, or None when the video was never uploaded.
    `points` is None while the video hasn't accumulated enough traffic for a curve --
    the template shows an explicit "not enough data yet" state, never a blank chart.
    `views` anchors interpretation (a 200-view curve is directional, not gospel)."""
    with SessionLocal() as s:
        yt_id = _yt_id(s, video_id)
        if yt_id is None:
            return None
        rows = _curve(s, yt_id)
        views = s.scalar(
            select(Analytics.views)
            .where(Analytics.youtube_video_id == yt_id)
            .order_by(Analytics.as_of_date.desc())
        )
        siblings = []
        for child in s.scalars(select(Video).where(Video.parent_id == video_id).order_by(Video.id)):
            child_yt = _yt_id(s, child.id)
            child_rows = _curve(s, child_yt) if child_yt else []
            if child_rows:
                siblings.append({
                    "video_id": child.id,
                    "title": (child.title or f"short {child.id}")[:60],
                    "points": _points(child_rows),
                })
    return {
        "views": views,
        "points": _points(rows) if rows else None,
        "hook_zone": _hook_zone(rows, duration_sec) if rows else [],
        "siblings": siblings,  # shorts of a parent that already have curves
    }
