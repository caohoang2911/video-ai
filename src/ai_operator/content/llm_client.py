"""LLM wrapper: Claude primary, Gemini fallback. Every call is budget-metered.

Heavy SDKs (anthropic, google-genai) are imported lazily inside the call functions —
that keeps `import ai_operator.content.llm_client` cheap and dependency-free for
anything that only needs `parse_json`/typing, and matches the project rule that heavy
deps are not installed until API keys are actually provisioned.
"""

from __future__ import annotations

import json
import re
import time

from ..config import settings
from ..constants import DEFAULT_ANTHROPIC_MODEL
from ..cost.budget_guard import check_and_reserve, record_actual
from ..cost.estimator import estimate_step
from ..logging_setup import get_logger

log = get_logger("content.llm_client")

_CHARS_PER_TOKEN = 4  # rough pre-call estimate so budget_guard can reserve before spending
_GEMINI_FLAT_ESTIMATE_USD = 0.05  # Gemini has no per-token price in constants.py yet
# A relevance judgment is one small downscaled image + a one-number answer — far cheaper than
# a script call, and free on the Gemini free tier. Reserve a tiny flat amount so a burst of
# per-image scores can't drain the cap, then record it as the actual (no usage price exists).
_GEMINI_VISION_FLAT_ESTIMATE_USD = 0.002
# The gate scores one image per call back-to-back, which is exactly the shape a per-minute
# request quota punishes. A quota rejection returns None and the image is KEPT UNJUDGED, so
# a burst that outruns the quota silently disables the gate — retry those once after a pause
# instead. Only quota errors are retried; a bad key or an unreadable image fails immediately.
_VISION_QUOTA_RETRY_SLEEP_S = 20
_QUOTA_ERROR_MARKERS = ("429", "RESOURCE_EXHAUSTED", "quota")
# "Depicts the subject" is not the same question as "is a real depiction of the subject": a
# museum scale model in its display case, a modern memorial plaque, and a photo of the site
# as it looks today all depict their event faithfully and all make a terrible video face.
# Naming those exclusions is what separates a 1.0 archive photo from a 1.0 souvenir.
_RELEVANCE_PROMPT = (
    'Does this image show "{subject}" ITSELF — the event, the vessel, or the site as it was? '
    "Answer with a single number from 0.0 to 1.0 (1.0 = a real depiction of it, 0.0 = "
    "unrelated). Score 0.0 for anything that only REFERS to it rather than showing it: a "
    "modern memorial, plaque, sign, museum display or scale model, map, or a modern photo of "
    "the location today. Number only, no words."
)
# Adaptive thinking tokens count against max_tokens (it is the ceiling on thinking + text
# combined). A tight ceiling lets a long thinking pass consume the whole budget and return
# a response with NO text block at all, which silently drops the call to the Gemini
# fallback. Floor the request ceiling high enough that thinking + a full script both fit;
# billing corrects to real usage afterwards.
_ANTHROPIC_MIN_MAX_TOKENS = 16_000


def _effective_max_tokens(requested: int) -> int:
    return max(requested, _ANTHROPIC_MIN_MAX_TOKENS)


class LLMError(Exception):
    """Raised when no LLM provider is configured or all providers fail."""


def complete(
    system: str,
    user: str,
    *,
    max_tokens: int = 4096,
    step: str = "llm_complete",
    video_id: int | None = None,
    thinking: bool = False,
) -> str:
    """Call the best available LLM for this step, falling back down the chain. Returns raw text.

    `thinking=True` marks a step whose output quality depends on the model's reasoning pass
    (script and hook writing, research judgement). Only the direct Anthropic API delivers it:
    an OpenAI-compatible gateway fronting a Claude Code plan accepts the request but strips
    the thinking parameter, and it prepends its own multi-thousand-token coding-agent system
    prompt that frames the model wrong for documentary prose. So those steps prefer the direct
    key and treat the gateway as a fallback; every other step goes to the gateway first."""
    for provider in _provider_chain(thinking):
        try:
            return _PROVIDERS[provider](system, user, max_tokens=max_tokens, step=step, video_id=video_id)
        except Exception as exc:  # noqa: BLE001 - any provider error should trigger fallback, not crash the run
            log.warning("%s call failed (%s) — trying next provider", provider, exc)
    raise LLMError("No LLM provider succeeded: set ANTHROPIC_API_KEY, LLM_GATEWAY_URL or GEMINI_API_KEY")


def _provider_chain(thinking: bool) -> list[str]:
    """Providers to try in order for this step, best-quality first, given what is configured."""
    chain: list[str] = []
    if thinking and settings.ANTHROPIC_API_KEY:
        chain.append("anthropic")
    if settings.LLM_GATEWAY_URL:
        chain.append("gateway")
    elif settings.ANTHROPIC_API_KEY and "anthropic" not in chain:
        chain.append("anthropic")
    if settings.GEMINI_API_KEY:
        chain.append("gemini")
    return chain


def _complete_gateway(system: str, user: str, *, max_tokens: int, step: str, video_id: int | None) -> str:
    """Call an OpenAI-compatible gateway (e.g. self-hosted 9router). The gateway's own
    pricing is unknown here, so budget metering reserves at the official Anthropic list
    rate — conservative (over-reserves on a free tier), never under-charges the cap."""
    from openai import OpenAI  # lazy: heavy dep, only needed when the gateway is enabled

    est_in_tokens = max(1, (len(system) + len(user)) // _CHARS_PER_TOKEN)
    estimated = estimate_step("anthropic", in_tokens=est_in_tokens, out_tokens=max_tokens)
    ledger_id = check_and_reserve(estimated, step=step, provider="gateway", video_id=video_id, units=est_in_tokens)

    client = OpenAI(
        api_key=settings.LLM_GATEWAY_KEY or settings.ANTHROPIC_API_KEY,
        base_url=settings.LLM_GATEWAY_URL,
    )
    try:
        response = client.chat.completions.create(
            model=settings.LLM_GATEWAY_MODEL,
            max_tokens=_effective_max_tokens(max_tokens),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        usage = response.usage
        actual = estimate_step(
            "anthropic",
            in_tokens=usage.prompt_tokens if usage else est_in_tokens,
            out_tokens=usage.completion_tokens if usage else max_tokens,
        )
    except Exception:
        record_actual(ledger_id, 0.0)  # nothing billed on failure — release the reservation
        raise
    record_actual(ledger_id, actual)
    text = response.choices[0].message.content if response.choices else None
    if not text:
        raise LLMError("LLM gateway returned no text")
    return text


def _complete_anthropic(system: str, user: str, *, max_tokens: int, step: str, video_id: int | None) -> str:
    import anthropic  # lazy: heavy dep, not needed until a real call happens

    est_in_tokens = max(1, (len(system) + len(user)) // _CHARS_PER_TOKEN)
    estimated = estimate_step("anthropic", in_tokens=est_in_tokens, out_tokens=max_tokens, model=DEFAULT_ANTHROPIC_MODEL)
    ledger_id = check_and_reserve(estimated, step=step, provider="anthropic", video_id=video_id, units=est_in_tokens)

    # base_url=None falls through to the official API; set ANTHROPIC_BASE_URL in .env to
    # route through an Anthropic-compatible gateway (must speak /v1/messages format).
    client = anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY, base_url=settings.ANTHROPIC_BASE_URL
    )
    try:
        response = client.messages.create(
            model=DEFAULT_ANTHROPIC_MODEL,
            max_tokens=_effective_max_tokens(max_tokens),
            # Opus 4.8 runs WITHOUT thinking when the param is omitted (unlike Sonnet 5,
            # where adaptive is the default) — opt in so script/hook generation gets the
            # reasoning pass the model tier is being paid for.
            thinking={"type": "adaptive"},
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
    return _extract_text(response)


def _extract_text(response) -> str:
    """Join the text blocks of a Messages response. Newer Claude models can emit a leading
    `ThinkingBlock` (extended thinking), so `content[0]` is not guaranteed to be the text --
    blindly reading `content[0].text` then AttributeErrors and the caller falls back to Gemini."""
    text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
    if not text:
        raise LLMError("Anthropic response had no text block")
    return text


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


# Built after the call functions exist so `complete` can dispatch by provider name.
_PROVIDERS = {
    "anthropic": _complete_anthropic,
    "gateway": _complete_gateway,
    "gemini": _complete_gemini,
}


def score_image_relevance(
    subject: str, image_bytes: bytes, *, mime_type: str = "image/jpeg", video_id: int | None = None
) -> float | None:
    """0..1 relevance of an image to `subject` via Gemini vision (1.0 = depicts exactly this
    event/subject, 0.0 = unrelated), or None when Gemini is unusable or returns no parseable
    number. Best-effort: never raises. Requires GEMINI_API_KEY.

    Backs the thumbnail relevance gate: a real archival photo of the WRONG ship/livery scores
    low and gets dropped, so only an image that actually depicts the event faces the video."""
    if not subject or not image_bytes or not settings.GEMINI_API_KEY:
        return None
    try:
        from google import genai
        from google.genai import types
    except Exception:  # noqa: BLE001 - SDK not installed -> treat as no backend, keep image
        return None

    try:
        ledger_id = check_and_reserve(
            _GEMINI_VISION_FLAT_ESTIMATE_USD, step="thumb_relevance", provider="gemini", video_id=video_id
        )
    except Exception as exc:  # noqa: BLE001 - budget cap / ledger error -> can't judge, never crash render
        log.warning("Gemini relevance reserve failed (%s) -> image not judged", exc)
        return None

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=settings.GEMINI_VISION_MODEL,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    _RELEVANCE_PROMPT.format(subject=subject),
                ],
                config=types.GenerateContentConfig(
                    max_output_tokens=16,
                    # No chain-of-thought needed for a one-number answer; thinking would spend the
                    # tiny output budget and return no text (same trap as the script calls above).
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
        except Exception as exc:  # noqa: BLE001 - outage / bad key / quota -> release the reservation
            if attempt == 0 and _is_quota_error(exc):
                log.warning("Gemini relevance score hit a quota wall (%s) -> retrying once", exc)
                time.sleep(_VISION_QUOTA_RETRY_SLEEP_S)
                continue
            record_actual(ledger_id, 0.0)  # nothing billed on failure (mirrors the other providers)
            log.warning("Gemini relevance score failed (%s) -> image not judged", exc)
            return None
        record_actual(ledger_id, _GEMINI_VISION_FLAT_ESTIMATE_USD)
        return _parse_unit_score(response.text)
    return None  # unreachable: the loop either returns or falls into the terminal-failure branch


def _is_quota_error(exc: Exception) -> bool:
    """Whether the failure is a rate/quota rejection worth waiting out (vs a permanent error)."""
    text = str(exc)
    return any(marker in text for marker in _QUOTA_ERROR_MARKERS)


def _parse_unit_score(text: str | None) -> float | None:
    """First number found in `text`, clamped to [0, 1]; None when there is no number."""
    if not text:
        return None
    match = re.search(r"\d*\.?\d+", text)
    if not match:
        return None
    try:
        return max(0.0, min(1.0, float(match.group())))
    except ValueError:
        return None


def parse_json(text: str) -> dict:
    """Extract JSON from an LLM response, stripping ```json fences some models add."""
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    return json.loads(cleaned)
