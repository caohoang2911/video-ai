"""Adversarial LLM verify — Phase 2 of the flag-only fact cross-check.

A second LLM plays hostile fact-checker over research_gate's citations, hunting for claims
the NAMED SOURCE would not actually contain and invented-looking specifics (oddly precise
counts, unverifiable references). It catches what the Wikipedia keyword match (Phase 1)
cannot: unsupported reasoning and source-claim mismatch.

Independence comes from the prompt inversion — this system prompt is rewarded for finding
holes, the opposite of research_gate's "list credible sources" framing — so it stays
independent even on the same model. Flag-only: on any LLM/parse failure every citation
degrades to `doubtful`; it never raises into the pipeline and never blocks.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..logging_setup import get_logger
from .llm_client import complete, parse_json
from .schema import Citation

log = get_logger("content.fact_skeptic")

_VALID = {"supported", "doubtful", "unsupported"}

_SKEPTIC_SYSTEM = (
    "You are a HOSTILE fact-checker auditing a documentary research desk. You are given "
    "numbered citations, each a historical CLAIM plus the SOURCE that supposedly backs it. "
    "For every citation, decide independently and skeptically:\n"
    "- Would that NAMED SOURCE plausibly contain that exact claim? If the source type can't "
    "support the claim (e.g. a ship's manifest cited for someone's private motive), doubt it.\n"
    "- Does the claim contain invented-looking specifics — oddly precise counts, exact quotes, "
    "or references (archive codes, page numbers) that read as fabricated? If so, doubt it.\n"
    "DEFAULT TO DOUBT when uncertain — you are the adversary, not the author. Rate each:\n"
    "supported = source plausibly backs the claim and nothing reads fabricated; "
    "doubtful = plausible but unverifiable or partly shaky; "
    "unsupported = the source could not contain this, or a specific reads invented.\n"
    "Give a concrete one-line reason per verdict (name the doubt; never 'looks fine').\n"
    'Respond with ONLY minified JSON: {"verdicts":[{"index":int,"status":'
    '"supported"|"doubtful"|"unsupported","reason":str}, ...one per citation]}'
)


@dataclass
class SkepticVerdict:
    """One citation's adversarial verdict: supported | doubtful | unsupported."""

    status: str
    reason: str = ""


def _format_citations(citations: list[Citation]) -> str:
    lines = [
        f"[{i}] CLAIM: {c.claim}\n    SOURCE: {c.source}"
        for i, c in enumerate(citations)
    ]
    return "Audit these citations:\n" + "\n".join(lines) + "\n\nReturn one verdict per index now."


def skeptic_verdicts(
    topic: str, angle: str, citations: list[Citation], *, video_id: int | None = None
) -> list[SkepticVerdict]:
    """One batched adversarial pass over all citations. Returns one verdict per citation,
    aligned by index; any missing/garbled/failed entry defaults to `doubtful` (cautious flag,
    never blocks). Never raises."""
    if not citations:
        return []
    default = [SkepticVerdict("doubtful", "not evaluated") for _ in citations]
    try:
        user = f"Topic: {topic}\nAngle: {angle}\n\n" + _format_citations(citations)
        raw = complete(_SKEPTIC_SYSTEM, user, max_tokens=1200, step="fact_skeptic", video_id=video_id, thinking=True)
        data = parse_json(raw)
    except Exception as exc:  # noqa: BLE001 - flag-only: a skeptic failure must not fail the video
        log.warning("fact_skeptic failed (%s) — defaulting all citations to doubtful", exc)
        return default

    out = list(default)
    for item in data.get("verdicts", []):
        idx = item.get("index")
        status = str(item.get("status", "")).lower()
        if isinstance(idx, int) and 0 <= idx < len(out) and status in _VALID:
            out[idx] = SkepticVerdict(status, str(item.get("reason", "")).strip())
    return out
