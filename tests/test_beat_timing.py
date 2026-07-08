"""Key-free unit tests for per-beat Ken Burns durations.

Guards the reconciliation invariant that broke a real render: durations must sum EXACTLY to
the narration length, and no single beat may swallow the timeline when few beats cover a long
narration (the old "dump all drift on the last beat" behavior made one 7-minute shot).
"""

from __future__ import annotations

from ai_operator.assembler.beat_timing import MIN_BEAT_SECONDS, compute_beat_durations


def _beats(n: int) -> list[dict]:
    # uniform-length narration spans so the proportional split is even before clamping
    return [{"beat_id": i + 1, "narration_span": "x" * 50, "mood": "m"} for i in range(n)]


def test_durations_sum_exactly_to_narration_length():
    for total in (60.0, 452.0, 900.0):
        ds = compute_beat_durations(_beats(10), total)
        assert abs(sum(ds) - total) < 0.05


def test_few_long_beats_no_single_beat_swallows_timeline():
    # 10 beats over a 7.5-minute narration: previously beat 10 took ~420s. Now every beat is a
    # sane share -- no beat should exceed ~3x the even split.
    total = 452.0
    ds = compute_beat_durations(_beats(10), total)
    even = total / 10
    assert max(ds) < even * 3, f"a beat swallowed the timeline: {max(ds):.0f}s of {total:.0f}s"
    assert min(ds) >= MIN_BEAT_SECONDS


def test_many_short_beats_respect_floor_and_sum():
    # 40 beats over a 30s narration forces heavy down-scaling into the MIN floor
    total = 30.0
    ds = compute_beat_durations(_beats(40), total)
    assert all(d >= MIN_BEAT_SECONDS for d in ds)
    assert abs(sum(ds) - total) < 0.05


def test_establishing_beat_is_not_shorter_than_montage():
    # position-based pacing: the opening (establishing) beat should get >= a closing montage beat
    ds = compute_beat_durations(_beats(10), 452.0)
    assert ds[0] >= ds[-1]


def test_empty_shot_list_returns_empty():
    assert compute_beat_durations([], 100.0) == []
