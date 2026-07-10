"""One-screen operator health snapshot over the rotating log + DB (no metrics stack).

Read-only aggregate powering `operator health`: pipeline state counts, monthly USD budget,
ElevenLabs char quota, YouTube daily quota, last publish, recent errors tailed from the log,
retention/CTR averages, and output/ disk usage. Per-child disk sizes surface any per-video
working tree that missed the post-encode / post-publish cleanup (a stuck `output/<id>/`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from ..config import LOG_DIR, OUTPUT_DIR, settings
from ..cost import elevenlabs_char_guard as char_guard
from ..cost.budget_guard import budget_remaining, current_ym, month_spent
from ..db.engine import SessionLocal
from ..db.models import Upload, Video
from ..db.models_ops import Analytics
from ..publisher import quota_throttle

_LOG_TAIL_BYTES = 200_000                 # ~last few thousand lines of the rotating log
_ERROR_MARKERS = ("ERROR", "ALERT")       # the log formatter emits levelname + our ALERT prefix


def _state_counts() -> dict[str, int]:
    with SessionLocal() as s:
        rows = s.execute(select(Video.state, func.count()).group_by(Video.state)).all()
    return {state: int(n) for state, n in rows}


def _last_publish() -> str | None:
    """ISO timestamp of the most recent confirmed upload (scheduled go-live if set)."""
    with SessionLocal() as s:
        row = s.scalar(
            select(Upload)
            .where(Upload.youtube_video_id.is_not(None))
            .order_by(Upload.created_at.desc())
        )
    if row is None:
        return None
    when = row.publish_at or row.created_at
    return when.isoformat() if when else None


def latest_analytics_per_video() -> list[Analytics]:
    """Each video's newest analytics snapshot (dedup many daily rows to one per video).
    Public: the web analytics view reuses this so the 'newest per video' rule lives in one place."""
    with SessionLocal() as s:
        rows = s.scalars(
            select(Analytics).order_by(Analytics.youtube_video_id, Analytics.as_of_date.desc())
        ).all()
    latest: dict[str, Analytics] = {}
    for a in rows:
        latest.setdefault(a.youtube_video_id, a)  # first seen per id = newest (desc order)
    return list(latest.values())


def _analytics_averages() -> dict:
    rows = latest_analytics_per_video()
    if not rows:
        return {"videos": 0, "avg_views": 0.0, "avg_retention_pct": 0.0, "avg_ctr": 0.0}
    n = len(rows)
    return {
        "videos": n,
        "avg_views": round(sum(a.views for a in rows) / n, 1),
        "avg_retention_pct": round(sum(a.avg_view_pct for a in rows) / n, 1),
        "avg_ctr": round(sum(a.ctr for a in rows) / n, 2),
    }


def recent_errors(limit: int = 5) -> list[str]:
    """Last `limit` ERROR/ALERT lines tailed from the rotating operator log."""
    log_file = LOG_DIR / "operator.log"
    if not log_file.exists():
        return []
    try:
        with log_file.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - _LOG_TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    hits = [ln for ln in tail.splitlines() if any(m in ln for m in _ERROR_MARKERS)]
    return hits[-limit:]


def _safe_size(path: Path) -> int:
    """`path` size in bytes, or 0 if it vanished mid-scan (the always-on loop prunes
    output/ concurrently, so a read-only health scan must tolerate a racing delete)."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _dir_size(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += _safe_size(f)
        except OSError:
            continue  # entry disappeared between rglob and is_file -> skip
    return total


def disk_usage() -> dict:
    """Total output/ bytes + per-immediate-child bytes. A numeric child name is a per-video
    working tree; a lingering large one means cleanup was skipped."""
    if not OUTPUT_DIR.exists():
        return {"total_bytes": 0, "per_dir": {}}
    per_dir: dict[str, int] = {}
    total = 0
    for child in sorted(OUTPUT_DIR.iterdir()):
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        size = _dir_size(child) if is_dir else _safe_size(child)
        if is_dir:
            per_dir[child.name] = size
        total += size
    return {"total_bytes": total, "per_dir": per_dir}


def snapshot(error_limit: int = 5) -> dict:
    """One-screen operator status as a plain dict (JSON-serializable)."""
    char = char_guard.check_char_quota()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "states": _state_counts(),
        "budget": {
            "ym": current_ym(),
            "spent": round(month_spent(), 2),
            "monthly_budget": settings.MONTHLY_BUDGET,
            "remaining": round(budget_remaining(), 2),
        },
        "char_quota": {
            "ym": char.ym, "used": char.chars_used, "quota": char.quota,
            "pct_used": round(char.pct_used * 100, 1), "alert": char.alert,
            "exhausted": char.exhausted,
        },
        "yt_quota": {
            "used_today": quota_throttle.quota_used_today(),
            "remaining": quota_throttle.quota_remaining(),
        },
        "last_publish": _last_publish(),
        "analytics": _analytics_averages(),
        "recent_errors": recent_errors(error_limit),
        "disk": disk_usage(),
    }


def _mib(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MiB"


def render(snap: dict) -> str:
    """Human one-screen table of a `snapshot()`."""
    b, c, q, a = snap["budget"], snap["char_quota"], snap["yt_quota"], snap["analytics"]
    states = ", ".join(f"{k}={v}" for k, v in sorted(snap["states"].items())) or "(none)"
    ctr = f"{a['avg_ctr']}%" if a["avg_ctr"] else "n/a"  # 0 = CTR not measured yet (fresh/low-reach)
    lines = [
        f"operator health @ {snap['generated_at']}",
        "-" * 60,
        f"pipeline   : {states}",
        f"budget     : ${b['spent']:.2f} / ${b['monthly_budget']:.2f}  (remaining ${b['remaining']:.2f}, {b['ym']})",
        f"chars(11L) : {c['used']:,}/{c['quota']:,} ({c['pct_used']}%)"
        + ("  EXHAUSTED" if c["exhausted"] else "  ALERT" if c["alert"] else ""),
        f"yt quota   : used {q['used_today']} / remaining {q['remaining']} today",
        f"last pub   : {snap['last_publish'] or '(never)'}",
        f"analytics  : {a['videos']} vids  avg_views={a['avg_views']}  "
        f"retention={a['avg_retention_pct']}%  ctr={ctr}",
        f"disk       : output/ = {_mib(snap['disk']['total_bytes'])}",
    ]
    for name, size in sorted(snap["disk"]["per_dir"].items()):
        lines.append(f"             {name:>10} = {_mib(size)}")
    errs = snap["recent_errors"]
    lines.append(f"recent err : {len(errs)}")
    lines.extend(f"  {e}" for e in errs)
    return "\n".join(lines)
