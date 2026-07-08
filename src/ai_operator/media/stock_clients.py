"""Pexels + Pixabay stock photo search -- cached 24h and rate-limited.

Pixabay's ToS *requires* a 24h response cache for repeated queries; without it (and without
a rate limit) retries/resumes across the pipeline would blow through both APIs' request caps
fast. `requests_cache` and `requests_ratelimiter` compose via mixins directly on `Session`
(the documented pattern) rather than inheriting `CachedSession`+`LimiterSession`, which would
create a diamond-inheritance MRO neither library's docs test.
"""

from __future__ import annotations

from datetime import timedelta

from requests import Session
from requests_cache import CacheMixin
from requests_ratelimiter import LimiterMixin

from ..config import DATA_DIR, settings
from ..logging_setup import get_logger

log = get_logger("stock_clients")

_CACHE_NAME = "stock_http_cache"
PEXELS_PER_SECOND = 3.0
PIXABAY_PER_SECOND = 1.5


class _CachedLimiterSession(CacheMixin, LimiterMixin, Session):
    """24h-cached, rate-limited requests.Session (per-provider instance, see below)."""


_pexels_session: _CachedLimiterSession | None = None
_pixabay_session: _CachedLimiterSession | None = None


def _make_session(per_second: float) -> _CachedLimiterSession:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return _CachedLimiterSession(
        cache_name=str(DATA_DIR / _CACHE_NAME),
        backend="sqlite",
        expire_after=timedelta(hours=24),
        per_second=per_second,
    )


def _pexels_client() -> _CachedLimiterSession:
    global _pexels_session
    if _pexels_session is None:
        _pexels_session = _make_session(PEXELS_PER_SECOND)
    return _pexels_session


def _pixabay_client() -> _CachedLimiterSession:
    global _pixabay_session
    if _pixabay_session is None:
        _pixabay_session = _make_session(PIXABAY_PER_SECOND)
    return _pixabay_session


def search_pexels(keyword: str, per_page: int = 5) -> list[str]:
    """Landscape photo URLs (>=1920w) for `keyword`; [] if unconfigured or the call fails."""
    if not settings.PEXELS_API_KEY:
        return []
    try:
        r = _pexels_client().get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": settings.PEXELS_API_KEY},
            params={"query": keyword, "per_page": per_page, "orientation": "landscape"},
            timeout=5,
        )
        r.raise_for_status()
        remaining = r.headers.get("X-Ratelimit-Remaining")
        if remaining is not None:
            log.debug("pexels quota remaining=%s", remaining)
        photos = r.json().get("photos", [])
        return [p["src"]["large2x"] for p in photos if p.get("src", {}).get("large2x")]
    except Exception as exc:
        log.warning("pexels search failed for %r: %s", keyword, exc)
        return []


def search_pixabay(keyword: str, per_page: int = 5) -> list[str]:
    """Landscape photo URLs (>=1920w) for `keyword`; [] if unconfigured or the call fails."""
    if not settings.PIXABAY_API_KEY:
        return []
    try:
        r = _pixabay_client().get(
            "https://pixabay.com/api/",
            params={
                "key": settings.PIXABAY_API_KEY,
                "q": keyword,
                "image_type": "photo",
                "orientation": "horizontal",
                "min_width": 1920,
                "per_page": per_page,
            },
            timeout=5,
        )
        r.raise_for_status()
        hits = r.json().get("hits", [])
        return [h["largeImageURL"] for h in hits if h.get("largeImageURL")]
    except Exception as exc:
        log.warning("pixabay search failed for %r: %s", keyword, exc)
        return []
