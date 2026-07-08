"""Structured (non-binary) review decision codes.

A plain approve/reject button lets a reviewer rubber-stamp without really looking — the
whole point of this gate is to force a *specific* code + reason, which becomes an audit
trail (`decisions` table) the content-engine can later learn "what gets rejected" from.
This module is the single source of truth mapping each terminal code to the video state
it moves to, so the callback handler and the CLI report never disagree on what a code means.
"""

from __future__ import annotations

from ..db import VideoState

TIER_POLICY = "policy"
TIER_QUALITY = "quality"

# Sub-reasons offered by the picker after the reviewer taps the top-level Reject/Edit button.
POLICY_REJECT_REASONS: tuple[str, ...] = ("AUDIO", "CAPTION", "ORIGINALITY", "OTHER")
QUALITY_EDIT_REASONS: tuple[str, ...] = ("PACING", "SYNC", "KENBURNS", "MUSIC", "ORIGINALITY", "OTHER")

REJECT_POLICY_PREFIX = "REJECT_POLICY_"
EDIT_PREFIX = "EDIT_"

PASS_POLICY = "PASS_POLICY"
PASS_QUALITY = "PASS_QUALITY"
HOLD_RERUN = "HOLD_RERUN"

# decision_code -> target VideoState. Every *terminal* tap (not a menu-open tap) must be here.
CODE_TARGET_STATE: dict[str, VideoState] = {
    PASS_POLICY: VideoState.POLICY_OK,
    **{f"{REJECT_POLICY_PREFIX}{r}": VideoState.REJECTED for r in POLICY_REJECT_REASONS},
    PASS_QUALITY: VideoState.APPROVED,
    **{f"{EDIT_PREFIX}{r}": VideoState.EDITING for r in QUALITY_EDIT_REASONS},
    HOLD_RERUN: VideoState.RERUN_QUEUED,
}


def tier_of(code: str) -> str:
    """Policy codes gate publish (TIER-1); quality codes feed the content-engine post-gate."""
    if code == PASS_POLICY or code.startswith(REJECT_POLICY_PREFIX):
        return TIER_POLICY
    return TIER_QUALITY


def is_final(code: str) -> bool:
    """True once `code` is a terminal decision (vs. a menu-opening tap like `REJECT_POLICY`/`EDIT`)."""
    return code in CODE_TARGET_STATE


def requires_free_text(code: str) -> bool:
    """`_OTHER` codes need a human-written reason — never store an empty "other"."""
    return code.endswith("_OTHER")
