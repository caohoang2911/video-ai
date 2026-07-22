"""ShortScript validators: the curiosity-gap contract + narration length + beat count."""

import pytest
from pydantic import ValidationError

from ai_operator.content.short_schema import ShortScript

_BASE = {
    "title": "The Captain Who Sailed Past Safety",
    "text_overlay": "He steered PAST safety",
    "narration": " ".join(["word"] * 90),
    "beats": [{"keywords": ["steamboat fire"], "mood": "tense"}] * 3,
    "curiosity_question": "What did that extra mile cost?",
    "hashtags": ["Shorts", "History"],
}


def _make(**overrides) -> dict:
    return {**_BASE, **overrides}


def test_valid_short_parses():
    s = ShortScript.model_validate(_make())
    assert s.curiosity_question.endswith("?")


@pytest.mark.parametrize("question", ["", "This is a statement.", "No question mark"])
def test_curiosity_question_must_be_open_question(question):
    with pytest.raises(ValidationError):
        ShortScript.model_validate(_make(curiosity_question=question))


@pytest.mark.parametrize("words", [30, 59, 131, 400])
def test_narration_word_count_bounds(words):
    with pytest.raises(ValidationError):
        ShortScript.model_validate(_make(narration=" ".join(["word"] * words)))


@pytest.mark.parametrize("n", [0, 2, 8])
def test_beat_count_bounds(n):
    beats = [{"keywords": ["k"], "mood": "m"}] * n
    with pytest.raises(ValidationError):
        ShortScript.model_validate(_make(beats=beats))


def test_overlay_headline_7_to_14_words_ok():
    s = ShortScript.model_validate(
        _make(overlay_headline="How the General Slocum Caught Fire\n1,021 Never Came Home")
    )
    assert "\n" in s.overlay_headline


@pytest.mark.parametrize("headline", ["Too short here now", " ".join(["word"] * 15)])
def test_overlay_headline_word_bounds(headline):
    with pytest.raises(ValidationError):
        ShortScript.model_validate(_make(overlay_headline=headline))


def test_legacy_text_overlay_only_still_valid():
    # pre-headline scripts carry only text_overlay -> must still parse (render falls back)
    s = ShortScript.model_validate(_make(overlay_headline=""))
    assert s.text_overlay and not s.overlay_headline


def test_short_needs_at_least_one_hook():
    with pytest.raises(ValidationError):
        ShortScript.model_validate(_make(text_overlay="", overlay_headline=""))


_SPAN_NARRATION = (
    "The dam broke at midnight. The valley flooded fast. Nobody heard the warning. "
    + " ".join(["word"] * 54)
)


def _beats(spans):
    return [{"keywords": ["k"], "mood": "m", "narration_span": s} for s in spans]


def test_paraphrased_spans_are_rejected():
    # None of these appear verbatim -> the renderer could not time any image -> fail loud so the
    # generator retries.
    with pytest.raises(ValidationError):
        ShortScript.model_validate(_make(
            narration=_SPAN_NARRATION,
            beats=_beats(["a totally invented line", "another fabrication", "a third made-up one"]),
        ))


def test_verbatim_spans_pass_and_a_minority_miss_is_tolerated():
    # 2 of 3 anchor -> above the half floor -> valid (the miss interpolates at render time).
    s = ShortScript.model_validate(_make(
        narration=_SPAN_NARRATION,
        beats=_beats(["The dam broke at midnight.", "The valley flooded fast.", "a line that misses"]),
    ))
    assert len(s.beats) == 3


def test_curly_typography_span_is_accepted():
    # Curly apostrophe/quotes in the span still anchor against the straight-quoted narration.
    narration = (
        "The ship's bell rang once. Then a long silence fell over the deck. "
        "The captain said nothing. " + " ".join(["word"] * 54)
    )
    s = ShortScript.model_validate(_make(
        narration=narration,
        beats=_beats([
            "The ship’s bell rang once.",
            "Then a long silence fell over the deck.",
            "The captain said nothing.",
        ]),
    ))
    assert len(s.beats) == 3


def test_spanless_prefield_short_still_validates():
    # The field is optional: pre-field scripts (and regen re-validating them) must keep parsing.
    s = ShortScript.model_validate(_make(beats=[{"keywords": ["k"], "mood": "m"}] * 3))
    assert all(b.narration_span == "" for b in s.beats)


def test_a_sentence_reused_across_beats_is_not_mistaken_for_paraphrase():
    # A dramatic multi-still closer repeats one verbatim sentence; membership (not a forward
    # cursor) must count every reuse as copied so the short is not falsely rejected.
    s = ShortScript.model_validate(_make(
        narration=_SPAN_NARRATION,
        beats=_beats([
            "The dam broke at midnight.",
            "The valley flooded fast.",
            "The valley flooded fast.",
        ]),
    ))
    assert len(s.beats) == 3
