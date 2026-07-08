"""LLM wrapper: Claude primary, Gemini fallback. Every call is budget-metered.

Heavy SDKs (anthropic, google-genai) are imported lazily inside the call functions —
that keeps `import ai_operator.content.llm_client` cheap and dependency-free for
anything that only needs `parse_json`/typing, and matches the project rule that heavy
deps are not installed until API keys are actually provisioned.
"""

from __future__ import annotations

import json
import re

from ..config import settings
from ..constants import DEFAULT_ANTHROPIC_MODEL
from ..cost.budget_guard import check_and_reserve, record_actual
from ..cost.estimator import estimate_step
from ..logging_setup import get_logger

log = get_logger("content.llm_client")

_CHARS_PER_TOKEN = 4  # rough pre-call estimate so budget_guard can reserve before spending
_GEMINI_FLAT_ESTIMATE_USD = 0.05  # Gemini has no per-token price in constants.py yet


class LLMError(Exception):
    """Raised when no LLM provider is configured or all providers fail."""


def complete(
    system: str,
    user: str,
    *,
    max_tokens: int = 4096,
    step: str = "llm_complete",
    video_id: int | None = None,
) -> str:
    """Call Claude; fall back to Gemini on any Anthropic failure. Returns raw text."""
    if settings.ANTHROPIC_API_KEY:
        try:
            return _complete_anthropic(system, user, max_tokens=max_tokens, step=step, video_id=video_id)
        except Exception as exc:  # noqa: BLE001 - any provider error should trigger fallback, not crash the run
            log.warning("Anthropic call failed (%s) — falling back to Gemini", exc)
    if settings.GEMINI_API_KEY:
        return _complete_gemini(system, user, max_tokens=max_tokens, step=step, video_id=video_id)
    raise LLMError("No LLM provider configured: set ANTHROPIC_API_KEY or GEMINI_API_KEY")


def _complete_anthropic(system: str, user: str, *, max_tokens: int, step: str, video_id: int | None) -> str:
    import anthropic  # lazy: heavy dep, not needed until a real call happens

    est_in_tokens = max(1, (len(system) + len(user)) // _CHARS_PER_TOKEN)
    estimated = estimate_step("anthropic", in_tokens=est_in_tokens, out_tokens=max_tokens, model=DEFAULT_ANTHROPIC_MODEL)
    ledger_id = check_and_reserve(estimated, step=step, provider="anthropic", video_id=video_id, units=est_in_tokens)

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model=DEFAULT_ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        actual = estimate_step(
            "anthropic",
            in_tokens=response.usage.input_tokens,
            out_tokens=response.usage.output_tokens,
            model=DEFAULT_ANTHROPIC_MODEL,
        )
    except Exception:
        # nothing billed on a failed request — release the reservation so a provider
        # outage can't accumulate phantom estimates and eventually trip the budget cap.
        record_actual(ledger_id, 0.0)
        raise
    record_actual(ledger_id, actual)
    return response.content[0].text


def _complete_gemini(system: str, user: str, *, max_tokens: int, step: str, video_id: int | None) -> str:
    from google import genai
    from google.genai import types

    # No per-token Gemini price lives in constants.py (Anthropic-only pricing table),
    # so a flat conservative reservation still stops a fallback loop from draining budget.
    estimated = _GEMINI_FLAT_ESTIMATE_USD
    ledger_id = check_and_reserve(estimated, step=f"{step}_gemini_fallback", provider="gemini", video_id=video_id)

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            # gemini-2.5-flash "thinks" by default, and that reasoning spends the output-token
            # budget -- on a complex prompt it burns the whole allowance and returns
            # `response.text is None`, which then crashes json.loads far downstream. These calls
            # want structured JSON, not chain-of-thought, so spend every token on the answer.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    record_actual(ledger_id, estimated)  # no usage-based pricing available; reservation stands as actual
    text = response.text
    if not text:
        # A safety block or an all-thinking response still yields no text -- fail loudly here
        # rather than handing an empty string to parse_json (a char-0 crash with no context).
        raise LLMError("Gemini returned no text (blocked or empty response)")
    return text


def parse_json(text: str) -> dict:
    """Extract JSON from an LLM response, stripping ```json fences some models add."""
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    return json.loads(cleaned)
