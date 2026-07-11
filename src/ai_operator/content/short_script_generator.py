"""Turn a main video's script.json into 2-3 self-contained Short scripts.

Each short is built around a DIFFERENT high-surprise payoff from the parent, uses only
facts already verified by the parent's research (no new claims), and closes on a
curiosity-gap question that sends viewers to the full video. Invalid shorts are dropped
at validation; one retry tops the batch up if fewer than MIN_VALID survive.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from ..logging_setup import get_logger
from .llm_client import complete, parse_json
from .short_schema import ShortScript

log = get_logger("content.short_script_generator")

MIN_VALID = 2
DEFAULT_COUNT = 3

_SYSTEM = """You are a faceless-documentary YouTube Shorts editor. You cut 30-45 second
vertical shorts from a finished long-form maritime-disaster documentary script.

Rules for EVERY short (the curiosity-gap contract):
1. Self-contained: a viewer who has never seen the channel must follow it cold.
2. Deliver EXACTLY ONE satisfying verified fact from the source material — the short must
   feel complete, not like a trailer.
3. WITHHOLD the twist/answer that the full video resolves. Never spoil the main reveal.
4. ENDING RECIPE — the last 3 narration sentences, in this order:
   a. LAND the promised fact completely (the short must feel finished, not cut off).
   b. PLANT one new, concrete, unresolved detail — a nameable document/decision/person/
      number the short does NOT explain. BAD: "but there was more to the story."
      GOOD: "the inspector who signed those life vests off had certified the ship just
      five weeks earlier."
   c. `curiosity_question`: the question ONLY the full documentary answers, aimed at that
      planted detail (ends with '?'). The viewer must know exactly what they'll learn by
      visiting the channel — specific beats vague every time.
5. Use ONLY facts present in the provided source facts/citations. Never invent numbers,
   names, dates, or events.
6. Narration: 75-110 words, punchy documentary voice, first sentence is a hook (no
   'imagine', no 'what if I told you').
7. `title`: must anchor a SEARCHABLE ENTITY (ship/place/event name or year) AND a concrete
   stake or number — never a generic label. "The Neighborhood That Vanished" is WEAK;
   "Little Germany: Erased by One Afternoon in 1904" is the bar. <=80 chars.
   ACROSS THE BATCH: every title must OPEN with different words — feeds truncate to ~30
   chars, so identical prefixes make the batch look like duplicates. Put the unique hook
   phrase FIRST and the entity/year anchor after a dash: "The Life Vests That Crumbled
   to Dust — General Slocum, 1904". Never start two shorts with the same entity prefix.
8. `text_overlay`: <=6 words, an information gap the viewer must resolve, strongest word
   first (Shorts autoplay muted — this line does the hook's job). "1,000 kids. One boat."
   beats "The neighborhood didn't fade."
9. `beats`: 5-6 visual beats (a new image every 5-7 seconds keeps swipe-away at bay);
   keywords should match the source shot list's imagery so existing visuals can be reused.
10. `end_card_text`: the 3-second closing card. TWO fragments, <=5 words each, on separate
    lines — compress the PLANTED DETAIL from the ending recipe so it re-opens the gap on
    screen, NEVER the spoken question repeated and NEVER a summary. Example: planted
    detail "inspector certified the ship 5 weeks earlier" -> "Inspected 5 weeks before.\n
    Approved." The pipeline appends the channel CTA line itself.

Return JSON only:
{"shorts": [{"title": str, "text_overlay": str, "narration": str,
  "beats": [{"keywords": [str], "mood": str}], "curiosity_question": str,
  "end_card_text": str, "hashtags": [str]}]}"""


def _distill_parent(parent_script: dict) -> str:
    """Compact the parent script into the facts the prompt may use (sorted best payoffs first)."""
    payoffs = sorted(
        parent_script.get("payoff_nodes", []),
        key=lambda p: p.get("surprise_score", 0),
        reverse=True,
    )
    shot_keywords = [kw for b in parent_script.get("shot_list", []) for kw in b.get("keywords", [])]
    return json.dumps(
        {
            "title_options": parent_script.get("title_options", []),
            "hooks": parent_script.get("hooks", []),
            "top_payoffs": payoffs[:6],
            "citations": parent_script.get("citations", []),
            "sources": parent_script.get("sources", []),
            "available_imagery_keywords": sorted(set(shot_keywords)),
            "narration": parent_script.get("narration", ""),
        },
        ensure_ascii=False,
    )


def _request(parent_facts: str, n: int, video_id: int | None) -> list[ShortScript]:
    user = (
        f"Source documentary material:\n{parent_facts}\n\n"
        f"Produce {n} DISTINCT shorts, each built around a DIFFERENT top payoff."
    )
    raw = complete(_SYSTEM, user, max_tokens=4096, step="short_scripts", video_id=video_id)
    data = parse_json(raw)
    valid: list[ShortScript] = []
    for i, item in enumerate(data.get("shorts", [])):
        try:
            valid.append(ShortScript.model_validate(item))
        except ValidationError as exc:
            log.warning("short %s dropped at validation: %s", i, exc.errors()[0].get("msg"))
    return valid


def generate_short_scripts(
    parent_script: dict, n: int = DEFAULT_COUNT, *, video_id: int | None = None
) -> list[ShortScript]:
    """Return 2-3 validated ShortScripts for a parent script; raises if even the retry
    can't produce MIN_VALID (a weak batch must fail loudly, not ship one bad short)."""
    facts = _distill_parent(parent_script)
    shorts = _request(facts, n, video_id)
    if len(shorts) < MIN_VALID:
        log.info("only %s valid shorts, retrying once", len(shorts))
        shorts = _request(facts, n, video_id)
    if len(shorts) < MIN_VALID:
        raise ValueError(f"short generation produced {len(shorts)} valid shorts (< {MIN_VALID})")
    return shorts[:n]
