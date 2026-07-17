"""Topic sub-niche categories. Maritime is the proven anchor; the rest are disciplined
expansions of the SAME 'forgotten disaster' storytelling formula. Keep a NEW channel mostly on
the anchor (algorithm traction needs a tight niche) and expand deliberately — the selector
exists for control, not to sprawl early.
"""

from __future__ import annotations

# key -> {label (Vietnamese UI), domain (English phrasing injected into the LLM prompt)}
CATEGORIES: dict[str, dict[str, str]] = {
    "maritime": {"label": "Thảm hoạ biển",
                 "domain": "maritime disasters (shipwrecks, sinkings, ferry and ocean-liner losses)"},
    "aviation": {"label": "Hàng không",
                 "domain": "aviation disasters (airliner crashes, mid-air collisions, airship losses)"},
    "industrial": {"label": "Công nghiệp / Mỏ",
                   "domain": "industrial and mining disasters (mine explosions, factory blasts, gas releases)"},
    "rail": {"label": "Đường sắt",
             "domain": "railway disasters (train collisions, derailments, tunnel and bridge failures)"},
    "structural": {"label": "Sập / Đập",
                   "domain": "structural and dam disasters (bridge and building collapses, dam failures, floods)"},
    "fire": {"label": "Hoả hoạn",
             "domain": "fire disasters (city conflagrations, theatre, factory and nightclub fires)"},
}

DEFAULT_CATEGORY = "maritime"


def valid(category: str | None) -> str:
    """Normalize an incoming category to a known key, falling back to the anchor niche."""
    return category if category in CATEGORIES else DEFAULT_CATEGORY


def label(category: str | None) -> str:
    """Vietnamese display label for a category key."""
    return CATEGORIES.get(valid(category), CATEGORIES[DEFAULT_CATEGORY])["label"]


def domain(category: str | None) -> str:
    """English domain phrasing for the LLM suggestion prompt."""
    return CATEGORIES[valid(category)]["domain"]
