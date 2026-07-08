"""Persist a review decision (audit trail row) + move the video's lifecycle state.

Both writes happen together, in one transaction, and only after the transition is
confirmed legal — a stale/duplicate button tap (e.g. a retried Telegram update) must
raise instead of silently double-recording a decision or double-charging downstream steps.
"""

from __future__ import annotations

from ..db import SessionLocal, VideoState, assert_transition
from ..db.models import Decision, Video
from ..logging_setup import get_logger
from . import decision_codes as dc

log = get_logger("review.decision_store")


def record_decision(video_id: int, code: str, reason: str | None = None) -> VideoState:
    """Write the `decisions` audit row + transition `videos.state`. Returns the new state.

    Raises `InvalidTransition` (from `ai_operator.db`) if the video already moved past the
    state this code expects — the caller should treat that as "already decided", not crash.
    """
    target = dc.CODE_TARGET_STATE[code]
    tier = dc.tier_of(code)
    with SessionLocal() as s:
        video = s.get(Video, video_id)
        if video is None:
            raise ValueError(f"video {video_id} not found")
        assert_transition(video.state, target)  # raises InvalidTransition if stale
        s.add(Decision(video_id=video_id, tier=tier, decision_code=code, reason=reason))
        video.state = target.value
        if code.startswith(dc.REJECT_POLICY_PREFIX) and reason:
            video.reject_reason = reason
        s.commit()
        log.info("video %s: %s -> %s (tier=%s)", video_id, code, target.value, tier)
        return target
