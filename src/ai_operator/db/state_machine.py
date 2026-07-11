"""Video lifecycle state machine — single source of truth for valid transitions.

Every pipeline phase reads/writes `videos.state`. Defining allowed transitions in ONE
place (DRY) prevents illegal jumps (e.g. publishing something never reviewed).
"""

from __future__ import annotations

from enum import Enum


class VideoState(str, Enum):
    DRAFT = "draft"                 # topic picked, nothing generated
    SCRIPTED = "scripted"           # script.json written (phase 02)
    VOICED = "voiced"               # narration.mp3 + visuals ready (phase 03)
    RENDERED = "rendered"           # final.mp4 assembled (phase 04)
    PENDING_REVIEW = "pending_review"  # sent to Telegram (phase 05)
    POLICY_OK = "policy_ok"         # TIER-1 policy pass; TIER-2 quality open
    APPROVED = "approved"           # TIER-2 quality pass -> publisher may pick up
    PUBLISHED = "published"         # uploaded to YouTube (phase 06)
    ANALYZED = "analyzed"           # analytics pulled (phase 07)
    # branches
    REJECTED = "rejected"           # policy/quality reject (rework loop)
    EDITING = "editing"             # metadata edit requested
    RERUN_QUEUED = "rerun_queued"   # HOLD_RERUN -> regenerate media
    FAILED = "failed"               # error at any step (retry-able)


class InvalidTransition(Exception):
    """Raised when an illegal state transition is attempted."""


# Allowed forward transitions.
_TRANSITIONS: dict[VideoState, set[VideoState]] = {
    VideoState.DRAFT: {VideoState.SCRIPTED, VideoState.FAILED},
    VideoState.SCRIPTED: {VideoState.VOICED, VideoState.REJECTED, VideoState.FAILED},
    VideoState.VOICED: {VideoState.RENDERED, VideoState.FAILED},
    VideoState.RENDERED: {
        # direct review from the web panel — the operator reviews in-place, no hand-off hop
        VideoState.POLICY_OK, VideoState.REJECTED, VideoState.EDITING,
        VideoState.PENDING_REVIEW,  # optional Telegram hand-off (secondary review path)
        VideoState.FAILED,
    },
    VideoState.PENDING_REVIEW: {
        VideoState.POLICY_OK, VideoState.REJECTED, VideoState.EDITING,
    },
    VideoState.POLICY_OK: {
        VideoState.APPROVED, VideoState.EDITING,
        VideoState.RERUN_QUEUED, VideoState.REJECTED,
    },
    VideoState.APPROVED: {VideoState.PUBLISHED, VideoState.FAILED},
    VideoState.PUBLISHED: {VideoState.ANALYZED, VideoState.FAILED},
    VideoState.ANALYZED: set(),
    # rework loops
    VideoState.REJECTED: {VideoState.DRAFT, VideoState.SCRIPTED},
    VideoState.EDITING: {VideoState.APPROVED, VideoState.PENDING_REVIEW, VideoState.RENDERED},
    VideoState.RERUN_QUEUED: {VideoState.DRAFT, VideoState.SCRIPTED, VideoState.VOICED},
    VideoState.FAILED: {
        VideoState.DRAFT, VideoState.SCRIPTED, VideoState.VOICED, VideoState.RENDERED,
    },
}


def _coerce(s: str | VideoState) -> VideoState:
    return s if isinstance(s, VideoState) else VideoState(s)


def can_transition(current: str | VideoState, target: str | VideoState) -> bool:
    """True if moving current -> target is allowed."""
    return _coerce(target) in _TRANSITIONS[_coerce(current)]


def assert_transition(current: str | VideoState, target: str | VideoState) -> None:
    """Raise InvalidTransition if current -> target is not allowed."""
    if not can_transition(current, target):
        raise InvalidTransition(f"{_coerce(current).value} -> {_coerce(target).value}")
