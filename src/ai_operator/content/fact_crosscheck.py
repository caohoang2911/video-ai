"""Independent cross-check of research_gate citations against outside evidence.

research_gate is self-attestation: the LLM names its own sources and sets `verified`. This
module adds a SECOND, INDEPENDENT signal — it does NOT block the pipeline (flag-only); it
annotates each citation with a machine-checked verdict a human reads before approving.

Phase 1 (here): Wikipedia cross-check — confirm the claim's entity exists and a MAJORITY of
its dates/numbers appear in a real Wikipedia article. Deliberately simple string/regex
matching, not NLP: the goal is catching gross fabrication (wrong year, invented casualty
count), and biasing toward `unconfirmed` when unsure is fine — the LLM skeptic (Phase 2)
and the human gate are the safety net.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

from requests import Session
from requests_cache import CacheMixin
from requests_ratelimiter import LimiterMixin

from ..config import DATA_DIR
from ..logging_setup import get_logger
from ..media.stock_clients import _retry_after_seconds  # DRY: shared 429/503 backoff helper
from .schema import Citation

log = get_logger("content.fact_crosscheck")

_WIKI_API = "https://en.wikipedia.org/w/api.php"
_WIKI_UA = "ai-operator/0.1 (self-hosted documentary pipeline)"  # Wikimedia UA policy
_WIKI_PER_SECOND = 1.0
_CACHE_NAME = "fact_crosscheck_cache"

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")
_FULLDATE_RE = re.compile(rf"\b\d{{1,2}}\s+(?:{_MONTHS})\s+\d{{4}}\b")
# 3+ digit counts (casualties, tonnage…); commas optional. Years are handled separately.
_NUMBER_RE = re.compile(r"\b\d[\d,]{2,}\b")
# First capitalized multi-word phrase, or a 'Quoted Title' — the search entity.
_ENTITY_RE = re.compile(r"\b([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*)+)")


class _CachedLimiterSession(CacheMixin, LimiterMixin, Session):
    """24h-cached, rate-limited session — same pattern as media.stock_clients."""


_session: _CachedLimiterSession | None = None


def _wiki_client() -> _CachedLimiterSession:
    global _session
    if _session is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _session = _CachedLimiterSession(
            cache_name=str(DATA_DIR / _CACHE_NAME),
            backend="sqlite",
            expire_after=timedelta(hours=24),
            per_second=_WIKI_PER_SECOND,
        )
    return _session


@dataclass
class CrossCheckVerdict:
    """One citation's Wikipedia verdict: confirmed | conflict | unconfirmed."""

    status: str
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    article_title: str | None = None


def _claim_entity(claim: str) -> str:
    """The proper-noun phrase to search Wikipedia for — a quoted title if present, else the
    first capitalized multi-word phrase ('RMS Lusitania', 'Halifax Explosion')."""
    quoted = re.search(r"['\"]([^'\"]{3,})['\"]", claim)
    if quoted:
        return quoted.group(1).strip()
    m = _ENTITY_RE.search(claim)
    return m.group(1).strip() if m else ""


def _extract_facts(claim: str) -> tuple[list[str], list[str]]:
    """Return (years, other_facts) found in the claim. Years drive conflict detection;
    other_facts (full dates + 3-digit-plus counts) drive majority matching. Numbers are
    comma-normalized so '1,198' and '1198' compare equal."""
    years = _YEAR_RE.findall(claim)
    full_dates = _FULLDATE_RE.findall(claim)
    numbers = [n.replace(",", "") for n in _NUMBER_RE.findall(claim) if not _YEAR_RE.fullmatch(n)]
    others = [d for d in full_dates] + [n for n in numbers if len(n) >= 3]
    return years, others


def _present(fact: str, article_norm: str) -> bool:
    return fact.replace(",", "").lower() in article_norm


def _wiki_extract(entity: str) -> tuple[str, str] | None:
    """(title, plain-text extract) of the best-matching Wikipedia article for `entity`, or
    None when nothing usable comes back. Never raises — a network/parse failure is a MISS,
    not a pipeline error. Retries 429/503 with backoff (shared helper)."""
    if not entity:
        return None
    params = {
        "action": "query", "format": "json",
        "generator": "search", "gsrsearch": entity, "gsrlimit": 1,
        "prop": "extracts", "explaintext": 1, "exintro": 0,
    }
    r = None
    for attempt in (1, 2, 3):
        try:
            r = _wiki_client().get(_WIKI_API, params=params, headers={"User-Agent": _WIKI_UA}, timeout=8)
            r.raise_for_status()
            break
        except Exception as exc:  # noqa: BLE001 - any failure is a MISS, never a pipeline error
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if attempt < 3 and status in (429, 503):
                import time
                time.sleep(_retry_after_seconds(exc, default=2 ** attempt))
                continue
            log.info("wikipedia lookup failed for %r: %s", entity, exc)
            return None
    pages = (r.json().get("query") or {}).get("pages", {})
    for page in pages.values():
        extract = (page.get("extract") or "").strip()
        if extract:
            return page.get("title", entity), extract
    return None


def verdict_for(citation: Citation) -> CrossCheckVerdict:
    """Cross-check one citation against Wikipedia. Conflict (a claimed year disagreeing with
    the article) wins over majority; else majority of facts present -> confirmed, too few ->
    unconfirmed. Entity-not-found / no facts / any failure -> unconfirmed (never raises)."""
    entity = _claim_entity(citation.claim)
    hit = _wiki_extract(entity)
    if hit is None:
        return CrossCheckVerdict("unconfirmed")
    title, extract = hit
    article_norm = extract.replace(",", "").lower()

    years, others = _extract_facts(citation.claim)
    # Conflict: the claim names year(s), the article names year(s), but NONE of the claim's
    # years appear -> the event's date disagrees. Conservative: one matching year clears it.
    article_years = set(_YEAR_RE.findall(extract))
    if years and article_years and not any(y in article_years for y in years):
        return CrossCheckVerdict("conflict", missing=years, article_title=title)

    facts = years + others
    if not facts:
        # Entity is real and nothing contradicts it, but there is nothing checkable.
        return CrossCheckVerdict("confirmed", article_title=title)
    matched = [f for f in facts if _present(f, article_norm)]
    missing = [f for f in facts if not _present(f, article_norm)]
    status = "confirmed" if len(matched) * 2 >= len(facts) else "unconfirmed"  # majority
    return CrossCheckVerdict(status, matched=matched, missing=missing, article_title=title)


def crosscheck_citations(citations: list[Citation]) -> list[CrossCheckVerdict]:
    """Wikipedia verdict per citation. Dedups identical entities so repeated events cost one
    lookup (the session cache also covers this, but the dedup avoids re-parsing)."""
    cache: dict[str, CrossCheckVerdict] = {}
    out: list[CrossCheckVerdict] = []
    for c in citations:
        key = _claim_entity(c.claim).lower() + "|" + c.claim
        if key not in cache:
            cache[key] = verdict_for(c)
        out.append(cache[key])
    return out


def _merge(wiki_status: str, skeptic_status: str) -> str:
    """Combine the two independent verdicts into one human-facing confidence flag. A hard
    negative from EITHER check (Wikipedia contradiction, or the skeptic calling it unsupported)
    demands review; only agreement of both positives is `ok`; everything else is `weak`."""
    if wiki_status == "conflict" or skeptic_status == "unsupported":
        return "review"
    if wiki_status == "confirmed" and skeptic_status == "supported":
        return "ok"
    return "weak"


def verify(
    topic: str, angle: str, citations: list[Citation], *, video_id: int | None = None
) -> list[Citation]:
    """Flag-only entry point: run Wikipedia cross-check + the adversarial skeptic over every
    citation and return NEW citations carrying `fact_status` + `crosscheck` detail. Never
    blocks — any failure logs and returns the citations UNCHANGED so the pipeline is unaffected."""
    if not citations:
        return citations
    from . import fact_skeptic  # local import keeps the LLM path out of the Wikipedia-only import

    try:
        wiki = crosscheck_citations(citations)
        skeptic = fact_skeptic.skeptic_verdicts(topic, angle, citations, video_id=video_id)
        enriched: list[Citation] = []
        for c, w, s in zip(citations, wiki, skeptic):
            data = c.model_dump()
            data["fact_status"] = _merge(w.status, s.status)
            data["crosscheck"] = {
                "wikipedia": w.status,
                "wikipedia_article": w.article_title,
                "skeptic": s.status,
                "skeptic_reason": s.reason,
            }
            enriched.append(Citation(**data))
        log.info(
            "fact_crosscheck: %s",
            " ".join(f"{c.fact_status}" for c in enriched),
        )
        return enriched
    except Exception as exc:  # noqa: BLE001 - flag-only: verification must never fail the video
        log.warning("fact_crosscheck.verify failed (%s) — citations left unannotated", exc)
        return citations


def summarize(citations: list[Citation]) -> str:
    """`N ok / N weak / N review` line for the human review gate. `unflagged` counts citations
    the gate didn't annotate (disabled or a verify failure)."""
    counts = {"ok": 0, "weak": 0, "review": 0, "unflagged": 0}
    for c in citations:
        counts[c.fact_status or "unflagged"] = counts.get(c.fact_status or "unflagged", 0) + 1
    parts = [f"{counts[k]} {k}" for k in ("ok", "weak", "review", "unflagged") if counts[k]]
    return " / ".join(parts) if parts else "no citations"
