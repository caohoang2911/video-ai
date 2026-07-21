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


def test_stand_in_provider_is_recorded_as_a_fallback_in_the_ledger(cfg, monkeypatch):
    """A degradation nobody can see later is a degradation that costs days to diagnose: every
    Claude call once fell to Gemini for two days and only the ledger step name gave it away."""
    cfg(anthropic="sk-a", gateway="http://localhost/v1", gemini="g")
    steps: list[str] = []

    def _fail(system, user, **kwargs):
        steps.append(kwargs["step"])
        raise RuntimeError("down")

    def _ok(system, user, **kwargs):
        steps.append(kwargs["step"])
        return "text"

    monkeypatch.setitem(llm_client._PROVIDERS, "anthropic", _fail)
    monkeypatch.setitem(llm_client._PROVIDERS, "gateway", _ok)

    complete("sys", "user", step="script_generate", thinking=True)

    # first choice bills the plain step; the stand-in names itself
    assert steps == ["script_generate", "script_generate_gateway_fallback"]


def test_first_choice_provider_bills_the_plain_step(cfg, monkeypatch):
    cfg(anthropic="sk-a", gemini="g")
    steps: list[str] = []
    monkeypatch.setitem(llm_client._PROVIDERS, "anthropic",
                        lambda s, u, **kw: steps.append(kw["step"]) or "text")

    complete("sys", "user", step="research_gate", thinking=True)

    assert steps == ["research_gate"]  # not "..._anthropic_fallback"


def test_a_degraded_thinking_step_reaches_the_operator(cfg, monkeypatch):
    """A whole day of scripts was once written by the last-resort model because the paid key was
    out of credit and the gateway refused connections. The ledger recorded every bit of it and
    nobody looked, so the degradation now pushes an alert as well."""
    cfg(anthropic="sk-a", gateway="http://localhost/v1", gemini="g")
    llm_client._DEGRADED_ALERTED.clear()
    import ai_operator.ops.alerting as alerting

    alerts: list[str] = []
    monkeypatch.setattr(alerting, "alert", lambda msg: alerts.append(msg))
    monkeypatch.setitem(llm_client._PROVIDERS, "anthropic",
                        lambda s, u, **kw: (_ for _ in ()).throw(RuntimeError("credit balance is too low")))
    monkeypatch.setitem(llm_client._PROVIDERS, "gateway", lambda s, u, **kw: "text")

    complete("sys", "user", step="script_generate", thinking=True)

    assert len(alerts) == 1
    assert "gateway" in alerts[0] and "credit balance is too low" in alerts[0]


def test_the_degradation_alert_does_not_repeat_all_run(cfg, monkeypatch):
    """One wedged provider would otherwise fire per beat until someone restarts, and a channel
    that cries every minute is one nobody reads."""
    cfg(anthropic="sk-a", gateway="http://localhost/v1", gemini="g")
    llm_client._DEGRADED_ALERTED.clear()
    import ai_operator.ops.alerting as alerting

    alerts: list[str] = []
    monkeypatch.setattr(alerting, "alert", lambda msg: alerts.append(msg))
    monkeypatch.setitem(llm_client._PROVIDERS, "anthropic",
                        lambda s, u, **kw: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setitem(llm_client._PROVIDERS, "gateway", lambda s, u, **kw: "text")

    for _ in range(5):
        complete("sys", "user", step="script_generate", thinking=True)

    assert len(alerts) == 1


def test_a_cheap_step_falling_back_stays_quiet(cfg, monkeypatch):
    """Only reasoning-dependent output is worth waking someone for; the ledger already records
    the rest."""
    cfg(gateway="http://localhost/v1", gemini="g")
    llm_client._DEGRADED_ALERTED.clear()
    import ai_operator.ops.alerting as alerting

    alerts: list[str] = []
    monkeypatch.setattr(alerting, "alert", lambda msg: alerts.append(msg))
    monkeypatch.setitem(llm_client._PROVIDERS, "gateway",
                        lambda s, u, **kw: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setitem(llm_client._PROVIDERS, "gemini", lambda s, u, **kw: "text")

    complete("sys", "user", step="srt_translate", thinking=False)

    assert alerts == []
