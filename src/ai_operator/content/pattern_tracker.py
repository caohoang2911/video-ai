"""Narrative-pattern diversity guard — the anti-"cookie cutter" defense.

Video has no `pattern` column (phase 02 owns no DB migrations), so history is read
back from the on-disk script.json files already written by prior runs — the shared
file-based artifact layout the whole pipeline uses for cross-phase handoff.

Selection picks the LEAST-used pattern in the recent window rather than random: that
is a strictly stronger guarantee than "flag if >50%" (it can never let one pattern's
share climb past 50% in the first place), while still satisfying the spec's flag/log
requirement when a skewed history is found.
"""

from __future__ import annotations

import json
from collections import Counter

from ..config import OUTPUT_DIR
from ..logging_setup import get_logger

log = get_logger("content.pattern_tracker")

PATTERNS = ("chronological", "causal-chain", "perspective-flip", "mystery-first", "impact-backward")
RECENT_WINDOW = 6          # look-back size for the repeat-share check
REPEAT_THRESHOLD = 0.5


def recent_patterns(window: int = RECENT_WINDOW) -> list[str]:
    """Most-recent-first patterns pulled from existing output/<video_id>/script.json files."""
    if not OUTPUT_DIR.exists():
        return []
    dated: list[tuple[float, str]] = []
    for script_path in OUTPUT_DIR.glob("*/script.json"):
        try:
            data = json.loads(script_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue  # partial/corrupt write from a crashed run — skip, don't crash the guard
        pattern = data.get("pattern")
        if pattern:
            dated.append((script_path.stat().st_mtime, pattern))
    dated.sort(key=lambda e: e[0], reverse=True)
    return [p for _, p in dated[:window]]


def choose_pattern() -> str:
    """Pick the narrative pattern used least often across the recent window."""
    history = recent_patterns()
    if not history:
        return PATTERNS[0]

    counts = Counter(history)
    top_pattern, top_count = counts.most_common(1)[0]
    share = top_count / len(history)
    if share > REPEAT_THRESHOLD:
        log.warning(
            "pattern-diversity guard: '%s' is %.0f%% of last %d scripts — forcing a different pattern",
            top_pattern, share * 100, len(history),
        )

    ranked = sorted(PATTERNS, key=lambda p: counts.get(p, 0))
    return ranked[0]
