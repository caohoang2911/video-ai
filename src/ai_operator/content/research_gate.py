"""Pre-script fact-check gate — the anti-hallucination layer.

Runs BEFORE narration is written: asks the LLM to name >=3 credible sources and
cross-verify dates/places/names, then fails closed on Low research_depth or an
insufficient citation count. Citations produced here are merged into script.json by
script_generator; they never appear in narration/video (audit-only, per spec).
"""

from __future__ import annotations

from ..logging_setup import get_logger
from .llm_client import complete, parse_json
from .schema import Citation

log = get_logger("content.research_gate")

_DEPTH_RANK = {"Low": 0, "Med": 1, "High": 2}
_MIN_CITATIONS = 3
_MIN_DEPTH = "Med"

_SYSTEM_PROMPT = (
    "You are a maritime-history fact-checker for a documentary research desk. Given a "
    "topic and angle, list at least 3 credible, real, checkable sources (named "
    "archives, official inquiry reports, museum/library records, established news "
    "archives — never invent a URL or a source that would not plausibly exist). "
    "Cross-verify dates, place names, and person names across the sources before "
    "citing a claim as verified. Rate overall research_depth: "
    "Low = facts unverifiable or fewer than 3 independent sources; "
    "Med = 3+ sources, cross-verified, minor gaps remain; "
    "High = 3+ sources, fully cross-verified, high confidence. "
    'Respond with ONLY minified JSON: {"citations":[{"claim":str,"source":str,'
    '"verified":bool}, ...at least 3 items], "research_depth":"Low"|"Med"|"High"}'
)


class ResearchRejected(Exception):
    """Raised when research_depth is Low or fewer than 3 citations come back."""


def research(topic_title: str, angle: str, video_id: int | None = None) -> dict:
    """Return {"citations": [Citation], "sources": [str], "research_depth": "Med"|"High"}.

    Raises ResearchRejected (fail-closed) so no script is ever generated on weak/absent
    sourcing — this is the single control point against LLM-fabricated "history".
    """
    user = f"Topic: {topic_title}\nAngle: {angle}\nList sources and verify facts now."
    raw = complete(_SYSTEM_PROMPT, user, max_tokens=1500, step="research_gate", video_id=video_id, thinking=True)
    data = parse_json(raw)

    citations = [Citation(**c) for c in data.get("citations", [])]
    depth = data.get("research_depth", "Low")
    if depth not in _DEPTH_RANK:
        depth = "Low"  # unknown/malformed rating fails closed rather than defaulting to pass

    if len(citations) < _MIN_CITATIONS or _DEPTH_RANK[depth] < _DEPTH_RANK[_MIN_DEPTH]:
        raise ResearchRejected(
            f"research_depth={depth} citations={len(citations)} for '{topic_title}' "
            f"— need >={_MIN_CITATIONS} sources and >={_MIN_DEPTH} depth before scripting"
        )

    sources = list(dict.fromkeys(c.source for c in citations))  # de-dup, keep first-seen order
    log.info("research_gate PASS depth=%s citations=%d topic=%r", depth, len(citations), topic_title)
    return {"citations": citations, "sources": sources, "research_depth": depth}
