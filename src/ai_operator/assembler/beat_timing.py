"""Per-beat Ken Burns segment durations.

Raw duration = a beat's share of total narration length (proportional to narration_span
text length) so a visual cut roughly tracks how long that beat is spoken. That raw value
is clamped into a shot-type pacing band (establishing shots linger, montage beats cut
fast), then any rounding drift from clamping is absorbed so segment durations always sum
EXACTLY to the narration's own duration -- otherwise picture and sound slowly drift apart
over a 10+ minute render.
"""

from __future__ import annotations

# (min, max) seconds per shot type -- keeps retention pacing steady regardless of how the
# narration-proportional estimate lands.
SHOT_DURATION_CLAMP: dict[str, tuple[float, float]] = {
    "establishing": (4.0, 6.0),
    "detail": (2.0, 3.0),
    "reaction": (2.0, 3.0),
    "montage": (1.0, 2.0),
}
DEFAULT_CLAMP = (2.0, 6.0)
MIN_BEAT_SECONDS = 0.5


def infer_shot_type(index: int, total: int, beat: dict) -> str:
    """script.json's shot_list carries no shot_type (only mood/keywords) -- approximate
    pacing intent from position: the opening beat establishes, the closing stretch is a
    faster montage, everything else is a normal detail/reaction cut. An explicit
    `shot_type` key (if a beat ever carries one) always wins."""
    explicit = beat.get("shot_type")
    if explicit:
        return str(explicit).lower()
    if index == 0:
        return "establishing"
    if total >= 5 and index >= total - max(1, total // 5):
        return "montage"
    return "detail"


def clamp_duration(raw_seconds: float, shot_type: str) -> float:
    lo, hi = SHOT_DURATION_CLAMP.get(shot_type, DEFAULT_CLAMP)
    return max(lo, min(hi, raw_seconds))


def compute_beat_durations(shot_list: list[dict], total_duration: float) -> list[float]:
    """One duration (seconds) per beat in `shot_list`; the list always sums to exactly
    `total_duration` (the narration's real length) so base video and narration audio
    never drift apart."""
    if not shot_list:
        return []
    lengths = [max(1, len(b.get("narration_span", ""))) for b in shot_list]
    total_len = sum(lengths)
    total = len(shot_list)
    raw = [total_duration * (n / total_len) for n in lengths]
    clamped = [
        clamp_duration(d, infer_shot_type(i, total, b))
        for i, (d, b) in enumerate(zip(raw, shot_list))
    ]
    return _reconcile(clamped, total_duration)


def _reconcile(durations: list[float], target_total: float) -> list[float]:
    """Force exact sum by absorbing drift in the last beat; if that would push it below a
    watchable floor (many beats + short narration), spread the shortfall evenly instead."""
    diff = target_total - sum(durations)
    if abs(diff) < 0.01:
        return durations
    out = list(durations)
    adjusted_last = out[-1] + diff
    if adjusted_last < MIN_BEAT_SECONDS:
        per_beat = diff / len(out)
        out = [max(MIN_BEAT_SECONDS, d + per_beat) for d in out]
    else:
        out[-1] = adjusted_last
    return out
