"""Best-effort topic DEMAND signal from the YouTube Data API.

There is no official "search volume" endpoint, and paid keyword tools are web-search-oriented,
not YouTube. The honest, free, YouTube-native proxy: for a topic's entity, look at how much the
EXISTING videos get watched (demand) versus how crowded the field already is (competition), and
fold them into an Opportunity score 0-100 — high watch demand that is not yet saturated.

Reuses the channel's OAuth (same `build_service` as channel_stats). NEVER raises: no key,
quota exhaustion, or any API error -> None, so gen-topics never blocks on it. One `search.list`
costs 100 quota units; the default 10k/day budget covers ~100 topic checks.
"""

from __future__ import annotations

import json
import math
from statistics import median

from ..config import settings
from ..logging_setup import get_logger

log = get_logger("content.topic_demand")

_YT_KEYS = ["YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"]
_MAX_RESULTS = 8
_STRONG_VIEWS = 200_000  # a video at/above this is a "strong incumbent" (competition)


def score(query: str) -> dict | None:
    """Opportunity score 0-100 for `query`, or None when YouTube is unconfigured / errors.

    Returns `{"score", "median_views", "competition", "top": [{"title","views"} ...]}`.
    """
    query = (query or "").strip()
    if not query or settings.missing(_YT_KEYS):
        return None
    try:
        from ..publisher.oauth_headless import build_service  # deferred: OAuth libs + creds

        service = build_service()
        search = service.search().list(
            part="snippet", q=query, type="video", maxResults=_MAX_RESULTS, order="relevance"
        ).execute()
        ids = [it["id"]["videoId"] for it in search.get("items", []) if it.get("id", {}).get("videoId")]
        if not ids:
            return {"score": 0, "median_views": 0, "competition": 0, "top": []}
        stats = service.videos().list(part="snippet,statistics", id=",".join(ids)).execute()
    except Exception as exc:  # noqa: BLE001 - demand is a nice-to-have; never break gen-topics
        log.warning("topic_demand: YouTube lookup failed for %r: %s", query, exc)
        return None

    videos = []
    for it in stats.get("items", []):
        views = int(it.get("statistics", {}).get("viewCount", 0) or 0)
        videos.append({"title": it.get("snippet", {}).get("title", ""), "views": views})
    if not videos:
        return {"score": 0, "median_views": 0, "competition": 0, "top": []}

    views_list = sorted((v["views"] for v in videos), reverse=True)
    med = int(median(views_list))
    competition = sum(1 for v in views_list if v >= _STRONG_VIEWS)
    top = sorted(videos, key=lambda v: v["views"], reverse=True)[:3]
    return {
        "score": _opportunity(med, competition),
        "median_views": med,
        "competition": competition,
        "top": top,
    }


def _opportunity(median_views: int, competition: int) -> int:
    """Demand (log of median views, 1k->0 .. 1M->100) dampened by saturation (strong incumbents)."""
    demand = (math.log10(median_views + 1) - 3.0) / 3.0 * 100.0  # 10^3 -> 0, 10^6 -> 100
    demand = max(0.0, min(100.0, demand))
    penalty = min(35.0, competition * 6.0)
    return int(round(max(0.0, demand - penalty)))


def score_json(query: str) -> tuple[int | None, str | None]:
    """Convenience for persistence: `(score, meta_json)` — both None when unavailable."""
    result = score(query)
    if result is None:
        return None, None
    return result["score"], json.dumps(result)
