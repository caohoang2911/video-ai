"""A Short's images have to land on the sentence they illustrate.

Beats used to be timed by cutting the narration into equal slices, which holds only while the
sentences are the same length. In a real render the beat drawn for "the world imagined alien
abductions" -- a flying saucer -- covered the sentence about blizzards over the Andes instead,
because the earlier sentences ran long. The fix asks each beat which narration it illustrates
and times the image from that; these lock it, including the fallbacks that keep older scripts
rendering.
"""

from __future__ import annotations

from ai_operator.assembler.short_builder import _beat_durations, beat_targets

# Sentences of deliberately uneven length -- the case an even split gets wrong.
NARRATION = (
    "A plane vanished. "                                                  # 0.0-14.3% of chars
    "For over half a century no wreckage or remains were ever found anywhere. "
    "The world imagined alien abductions and spy plots. "
    "The ice gave back one word."
)
SPANS = [
    "A plane vanished.",
    "For over half a century no wreckage or remains were ever found anywhere.",
    "The world imagined alien abductions and spy plots.",
    "The ice gave back one word.",
]
BEATS = [{"keywords": ["x"], "mood": "m", "narration_span": s} for s in SPANS]


def test_targets_follow_sentence_length_not_the_clock():
    targets = beat_targets(NARRATION, BEATS, 60.0)

    assert len(targets) == 3  # interior boundaries only; beat 0 always starts at 0.0
    # Each boundary sits where its sentence actually starts, proportionally through the text.
    for target, span in zip(targets, SPANS[1:]):
        assert abs(target - NARRATION.index(span) / len(NARRATION) * 60.0) < 0.01
    # ...and that is NOT the even split, which is the whole point.
    assert [round(t, 1) for t in targets] != [15.0, 30.0, 45.0]


def test_ufo_beat_lands_on_its_own_sentence():
    """The regression that started this: the alien-speculation image covering the blizzard line."""
    targets = beat_targets(NARRATION, BEATS, 60.0)
    alien_start = targets[1]  # boundary opening beat 3 ("The world imagined alien abductions")

    even_split_start = 2 * 60.0 / 4
    assert alien_start > even_split_start  # the long second sentence pushes it later
    # and it opens no earlier than where that sentence begins in the text
    assert alien_start >= NARRATION.index(SPANS[2]) / len(NARRATION) * 60.0 - 0.01


def test_script_without_spans_falls_back_to_the_even_split():
    plain = [{"keywords": ["x"], "mood": "m"} for _ in SPANS]  # pre-field script
    assert beat_targets(NARRATION, plain, 60.0) is None


def test_a_paraphrased_span_only_loses_its_own_boundary():
    beats = [dict(b) for b in BEATS]
    beats[2]["narration_span"] = "the world thought aliens took it"  # not verbatim
    targets = beat_targets(NARRATION, beats, 60.0)

    assert targets is not None                       # the other spans still carry the timing
    assert abs(targets[1] - 2 * 60.0 / 4) < 0.01     # this one boundary uses the even split
    assert abs(targets[2] - NARRATION.index(SPANS[3]) / len(NARRATION) * 60.0) < 0.01


def test_repeated_sentence_matches_forward_not_back():
    narration = "It vanished. Years passed. It vanished. The ice gave it back."
    spans = ["It vanished.", "Years passed.", "It vanished.", "The ice gave it back."]
    beats = [{"keywords": ["x"], "mood": "m", "narration_span": s} for s in spans]

    targets = beat_targets(narration, beats, 40.0)

    assert targets[1] > targets[0]  # the second "It vanished." resolves to the LATER occurrence
    assert targets[2] > targets[1]


def test_durations_still_sum_and_stay_monotonic_with_targets():
    caps = [{"end": e} for e in (5.0, 12.0, 25.0, 40.0, 60.0)]
    durations = _beat_durations(60.0, 4, caps, beat_targets(NARRATION, BEATS, 60.0))

    assert len(durations) == 4
    assert abs(sum(durations) - 60.0) < 1e-6
    assert all(d > 0 for d in durations)


def test_boundaries_only_ever_move_forward():
    """A beat whose span was paraphrased takes its even-split slot; if the NEXT beat's real span
    sits further back in the text, the raw boundary would go backwards and the renderer would be
    handed an inverted grid."""
    narration = "A. " + "x" * 400 + " The ice gave back one word. Later still, silence."
    beats = [
        {"keywords": ["a"], "mood": "m", "narration_span": "A."},
        {"keywords": ["b"], "mood": "m", "narration_span": "not in the narration at all"},
        {"keywords": ["c"], "mood": "m", "narration_span": "The ice gave back one word."},
        {"keywords": ["d"], "mood": "m", "narration_span": "Later still, silence."},
    ]

    targets = beat_targets(narration, beats, 60.0)

    assert targets == sorted(targets)


def test_a_degenerate_grid_still_gives_each_beat_a_real_shot():
    """Two frames of an image is a flicker, not a shot: the no-caption-nearby fallback advances
    by a whole minimum beat rather than 0.1s."""
    from ai_operator.assembler.short_builder import _MIN_BEAT_S

    durations = _beat_durations(10.0, 4, caps=[], targets=[0.0, 0.0, 0.0])

    assert all(d >= _MIN_BEAT_S - 1e-6 for d in durations[:-1]), durations
