"""Provider routing: which backend serves a step, and how it degrades when one fails.

The split exists because the OpenAI-compatible gateway cannot serve extended thinking --
it accepts the parameter and silently drops it, and it prepends its own coding-agent system
prompt. Steps whose quality rides on the reasoning pass must therefore prefer the direct
Anthropic key, while cheap steps still take the gateway first.
"""

import pytest

from ai_operator.content import llm_client
from ai_operator.content.llm_client import LLMError, complete


@pytest.fixture
def cfg(monkeypatch):
    """Set the three provider knobs at once; each test states the config it cares about."""

    def _set(*, anthropic=None, gateway=None, gemini=None):
        monkeypatch.setattr(llm_client.settings, "ANTHROPIC_API_KEY", anthropic, raising=False)
        monkeypatch.setattr(llm_client.settings, "LLM_GATEWAY_URL", gateway, raising=False)
        monkeypatch.setattr(llm_client.settings, "GEMINI_API_KEY", gemini, raising=False)

    return _set


def test_thinking_step_prefers_direct_anthropic_over_gateway(cfg):
    cfg(anthropic="sk-a", gateway="http://localhost/v1", gemini="g")
    assert llm_client._provider_chain(thinking=True) == ["anthropic", "gateway", "gemini"]


def test_plain_step_takes_gateway_first(cfg):
    cfg(anthropic="sk-a", gateway="http://localhost/v1", gemini="g")
    assert llm_client._provider_chain(thinking=False) == ["gateway", "gemini"]


def test_without_gateway_anthropic_serves_every_step(cfg):
    cfg(anthropic="sk-a", gemini="g")
    assert llm_client._provider_chain(thinking=False) == ["anthropic", "gemini"]
    assert llm_client._provider_chain(thinking=True) == ["anthropic", "gemini"]


def test_thinking_step_without_anthropic_key_still_runs_on_gateway(cfg):
    cfg(gateway="http://localhost/v1", gemini="g")
    assert llm_client._provider_chain(thinking=True) == ["gateway", "gemini"]


def test_failing_provider_falls_through_to_the_next(cfg, monkeypatch):
    cfg(anthropic="sk-a", gateway="http://localhost/v1", gemini="g")
    called = []

    def _fail(name):
        def _call(system, user, **kwargs):
            called.append(name)
            raise RuntimeError(f"{name} down")

        return _call

    def _ok(system, user, **kwargs):
        called.append("gemini")
        return "text from gemini"

    monkeypatch.setitem(llm_client._PROVIDERS, "anthropic", _fail("anthropic"))
    monkeypatch.setitem(llm_client._PROVIDERS, "gateway", _fail("gateway"))
    monkeypatch.setitem(llm_client._PROVIDERS, "gemini", _ok)

    assert complete("sys", "user", thinking=True) == "text from gemini"
    assert called == ["anthropic", "gateway", "gemini"]


def test_no_provider_configured_raises(cfg):
    cfg()
    with pytest.raises(LLMError):
        complete("sys", "user")
