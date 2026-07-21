"""Key-free tests for the vision call behind the thumbnail relevance gate.

The gate scores one image per call back-to-back, so a per-minute request quota is the
failure that actually bites: a rejected call returns None and the image is KEPT UNJUDGED,
silently disabling the gate. These pin the quota retry, the fail-fast on real errors, and
the prompt wording that separates a real depiction from a souvenir of the event.
"""

from __future__ import annotations

import pytest

from ai_operator.content import llm_client


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    """Replays a scripted sequence of outcomes, recording the kwargs of every call."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(outcome)


@pytest.fixture
def vision(monkeypatch):
    """Wire a fake Gemini client + a no-op budget ledger; return the recorder."""

    def _install(*outcomes):
        from google import genai

        models = _FakeModels(outcomes)
        monkeypatch.setattr(genai, "Client", lambda **kw: type("C", (), {"models": models})())
        monkeypatch.setattr(llm_client.settings, "GEMINI_API_KEY", "g", raising=False)
        monkeypatch.setattr(llm_client, "check_and_reserve", lambda *a, **k: 1)
        monkeypatch.setattr(llm_client, "record_actual", lambda *a, **k: None)
        monkeypatch.setattr(llm_client.time, "sleep", lambda s: slept.append(s))
        return models

    slept: list[float] = []
    _install.slept = slept
    return _install


def test_quota_rejection_is_retried_once(vision):
    models = vision(RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded"), "1.0")

    assert llm_client.score_image_relevance("RMS Lusitania", b"jpegbytes") == 1.0
    assert len(models.calls) == 2
    assert vision.slept  # waited out the quota window rather than giving up on the image


def test_second_quota_rejection_gives_up(vision):
    err = RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded")
    models = vision(err, err)

    assert llm_client.score_image_relevance("RMS Lusitania", b"jpegbytes") is None
    assert len(models.calls) == 2  # exactly one retry, never an unbounded wait


def test_non_quota_failure_is_not_retried(vision):
    models = vision(RuntimeError("400 INVALID_ARGUMENT bad image"))

    assert llm_client.score_image_relevance("RMS Lusitania", b"jpegbytes") is None
    assert len(models.calls) == 1  # a permanent error must not cost the render a 20s sleep


def test_call_uses_the_configured_vision_model(vision, monkeypatch):
    monkeypatch.setattr(llm_client.settings, "GEMINI_VISION_MODEL", "gemini-test-model", raising=False)
    models = vision("0.0")

    llm_client.score_image_relevance("MS Estonia", b"jpegbytes")

    assert models.calls[0]["model"] == "gemini-test-model"


def test_prompt_excludes_memorials_and_museum_pieces(vision):
    # A museum scale model in its case and a modern memorial plaque both depict their event
    # faithfully and both make a terrible video face — the prompt must rule them out by name.
    models = vision("1.0")

    llm_client.score_image_relevance("MS Estonia", b"jpegbytes")

    prompt = models.calls[0]["contents"][-1]
    assert "MS Estonia" in prompt
    assert "memorial" in prompt and "model" in prompt


def test_prompt_asks_when_the_photograph_was_taken(vision):
    """The wording this replaced asked whether the image showed the subject "or the site as it
    was" while also rejecting "a modern photo of the location today" — a present-day picture of
    a disaster site answers yes to both, and the contradiction shipped an empty hillside as a
    thumbnail. The question must be anchored on the photograph's era, not only its content."""
    models = vision("1.0")

    llm_client.score_image_relevance("The St. Francis Dam Failure", b"jpegbytes")

    prompt = models.calls[0]["contents"][-1]
    assert "FROM THE TIME" in prompt          # era is the question, not an afterthought
    assert "present-day photograph" in prompt  # ...and the opposite case is named as a reject
    assert "site as it was" not in prompt      # the clause that contradicted it is gone
