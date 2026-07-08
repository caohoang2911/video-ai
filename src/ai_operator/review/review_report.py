"""Weekly review-quality report — the rubber-stamp guard.

If a reviewer only ever taps PASS_*, that is a signal the gate is decorative rather than
real, so we surface it loudly instead of letting a policy-critical gate quietly degrade.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..db.engine import SessionLocal
from ..db.models import Decision
from ..logging_setup import get_logger
from . import decision_codes as dc

log = get_logger("review.report")

# 100% approval across >= this many decisions in the window is the rubber-stamp signal.
_RUBBER_STAMP_MIN_DECISIONS = 3


def weekly_report(weeks: int | None = 1) -> dict:
    """Decision breakdown since `weeks` ago (None = all-time)."""
    since = (
        datetime(1970, 1, 1, tzinfo=timezone.utc)
        if weeks is None
        else datetime.now(timezone.utc) - timedelta(weeks=weeks)
    )
    with SessionLocal() as s:
        rows = list(s.execute(select(Decision).where(Decision.created_at >= since)).scalars())

    total = len(rows)
    passed = sum(1 for r in rows if r.decision_code in (dc.PASS_POLICY, dc.PASS_QUALITY))
    rejected = sum(1 for r in rows if r.decision_code.startswith(dc.REJECT_POLICY_PREFIX))
    edited = sum(1 for r in rows if r.decision_code.startswith(dc.EDIT_PREFIX))
    held = sum(1 for r in rows if r.decision_code == dc.HOLD_RERUN)

    approval_pct = (passed / total * 100) if total else 0.0
    rubber_stamp = total >= _RUBBER_STAMP_MIN_DECISIONS and approval_pct >= 100.0

    return {
        "since": since.isoformat(),
        "total_decisions": total,
        "passed": passed,
        "rejected": rejected,
        "edited": edited,
        "held": held,
        "approval_pct": round(approval_pct, 1),
        "avg_review_seconds": _avg_gap_seconds(rows),
        "rubber_stamp_alert": rubber_stamp,
    }


def _avg_gap_seconds(rows: list[Decision]) -> float:
    """Proxy for "review time": gap between consecutive decisions on the same video
    (e.g. policy pass -> quality pass). Exact dwell-time isn't tracked (no sent_at column).
    """
    by_video: dict[int, list[datetime]] = {}
    for r in rows:
        by_video.setdefault(r.video_id, []).append(r.created_at)

    gaps: list[float] = []
    for timestamps in by_video.values():
        timestamps.sort()
        gaps.extend((b - a).total_seconds() for a, b in zip(timestamps, timestamps[1:]))
    return round(sum(gaps) / len(gaps), 1) if gaps else 0.0
