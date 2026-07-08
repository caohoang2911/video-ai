"""YouTube publishing package.

Covers headless OAuth, resumable upload, metadata/AI-disclosure body, quota +
cadence throttling, thumbnail upload, and the human-in-the-loop Studio A/B
workflow (YouTube's "Test & Compare" is Studio-only — there is no public API to
drive it, so we submit a checklist and record the human-observed winner instead).
"""

from __future__ import annotations

from .publish import publish

__all__ = ["publish"]
