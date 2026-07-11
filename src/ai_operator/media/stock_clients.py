"""Pexels + Pixabay stock photo search + Wikimedia Commons archival search -- cached 24h
and rate-limited.

Pixabay's ToS *requires* a 24h response cache for repeated queries; without it (and without
a rate limit) retries/resumes across the pipeline would blow through both APIs' request caps
fast. `requests_cache` and `requests_ratelimiter` compose via mixins directly on `Session`
(the documented pattern) rather than inheriting `CachedSession`+`LimiterSession`, which would
create a diamond-inheritance MRO neither library's docs test.

Wikimedia Commons is keyless but its API etiquette requires an identifying User-Agent and a
modest request rate; licensing there is PER-FILE (PD / CC0 / CC BY / CC BY-SA / all-rights-
reserved mixed together), so every candidate carries its own license + attribution fields --
the caller must persist them for the publish-phase credit line.
"""

from __future__ import annotations

import re
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
COMMONS_PER_SECOND = 1.0
# Archival photos predate HD -- 1000px wide is enough for a gentle Ken Burns at 1080p, while
# the 1920px stock bar would reject nearly every pre-1930 photograph.
COMMONS_MIN_WIDTH = 1000
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_COMMONS_UA = "ai-operator/0.1 (self-hosted documentary pipeline)"  # Wikimedia UA policy
# Motion b-roll: prefer the smallest file that still clears 1080p -- it costs the least
# bandwidth and the ffmpeg normalize pass rescales everything to 1920x1080 anyway.
VIDEO_MIN_HEIGHT = 1080
# A wider candidate pool gives the CLIP re-ranker a real choice (it scores each hit's preview
# thumbnail against the beat's content and picks the most relevant, not just the first hit).
CANDIDATE_POOL = 10

# Search functions return a list of {"url", "thumb"} candidates: `url` is the full-res
# photo/video file to download, `thumb` a small preview used only for relevance ranking.


class _CachedLimiterSession(CacheMixin, LimiterMixin, Session):
    """24h-cached, rate-limited requests.Session (per-provider instance, see below)."""


_pexels_session: _CachedLimiterSession | None = None
_pixabay_session: _CachedLimiterSession | None = None
_commons_session: _CachedLimiterSession | None = None


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


def _commons_client() -> _CachedLimiterSession:
    global _commons_session
    if _commons_session is None:
        _commons_session = _make_session(COMMONS_PER_SECOND)
    return _commons_session


def _source_disabled(name: str) -> bool:
    """True when the operator turned this source off via DISABLED_VISUAL_SOURCES in .env
    (comma-separated names). Lets a provider that keeps returning content-mismatched hits
    be locked out without deleting its API key."""
    disabled = {s.strip().lower() for s in settings.DISABLED_VISUAL_SOURCES.split(",") if s.strip()}
    return name in disabled


def _commons_license_ok(short_name: str) -> bool:
    """Only free-to-reuse grants pass: Public Domain family, CC0, CC BY, CC BY-SA.
    Everything else on Commons (GFDL-only, fair use, unknown) is rejected."""
    s = short_name.strip().lower()
    return s.startswith(("pd", "public domain", "no restrictions", "cc0", "cc by", "cc-by"))


def _strip_html(text: str) -> str:
    """Commons `Artist` metadata is HTML (often a wikilink) -> plain text for a credit line."""
    return re.sub(r"<[^>]+>", "", text).replace("\n", " ").strip()


def search_pexels(keyword: str, per_page: int = CANDIDATE_POOL) -> list[dict]:
    """Landscape photo candidates (>=1920w) for `keyword`; [] if unconfigured or the call fails."""
    if _source_disabled("pexels") or not settings.PEXELS_API_KEY:
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
        return [
            {"url": src["large2x"], "thumb": src.get("medium") or src["large2x"]}
            for p in photos if (src := p.get("src", {})).get("large2x")
        ]
    except Exception as exc:
        log.warning("pexels search failed for %r: %s", keyword, exc)
        return []


def search_pixabay(keyword: str, per_page: int = CANDIDATE_POOL) -> list[dict]:
    """Landscape photo candidates (>=1920w) for `keyword`; [] if unconfigured or the call fails."""
    if _source_disabled("pixabay") or not settings.PIXABAY_API_KEY:
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
        return [
            {"url": h["largeImageURL"], "thumb": h.get("previewURL") or h["largeImageURL"]}
            for h in hits if h.get("largeImageURL")
        ]
    except Exception as exc:
        log.warning("pixabay search failed for %r: %s", keyword, exc)
        return []


def search_wikimedia_commons(keyword: str, per_page: int = CANDIDATE_POOL) -> list[dict]:
    """Archival photo candidates from Wikimedia Commons for `keyword`; [] on failure.

    Each candidate carries per-file licensing (unlike the per-provider stock licenses):
    {"url", "thumb", "source": "wikimedia", "license", "artist", "file_page"}.
    Only PD/CC0/CC BY/CC BY-SA bitmap files >= COMMONS_MIN_WIDTH px wide are returned;
    `url` is the 1920px scaled render (originals can be 100MP museum scans)."""
    if _source_disabled("wikimedia"):
        return []
    try:
        r = _commons_client().get(
            _COMMONS_API,
            params={
                "action": "query", "format": "json",
                "generator": "search",
                "gsrsearch": f"filetype:bitmap {keyword}",
                "gsrnamespace": 6,  # File: namespace
                "gsrlimit": per_page,
                "prop": "imageinfo",
                "iiprop": "url|size|extmetadata",
                "iiurlwidth": 1920,  # scaled render + thumb template in one request
            },
            headers={"User-Agent": _COMMONS_UA},
            timeout=8,
        )
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages", {})
    except Exception as exc:
        log.warning("wikimedia commons search failed for %r: %s", keyword, exc)
        return []

    out: list[dict] = []
    # generator=search returns an unordered page map; `index` restores relevance order
    for p in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        license_short = ((meta.get("LicenseShortName") or {}).get("value") or "").strip()
        if not license_short or not _commons_license_ok(license_short):
            continue
        if (info.get("width") or 0) < COMMONS_MIN_WIDTH:
            continue
        original = info.get("url") or ""
        if not original.lower().endswith((".jpg", ".jpeg", ".png")):
            continue  # svg/tiff/pdf renders behave badly downstream
        full = info.get("thumburl") or original
        # Commons thumb URLs embed the width -- swap for a small CLIP-ranking preview
        thumb = full.replace("/1920px-", "/480px-") if "/1920px-" in full else full
        out.append({
            "url": full,
            "thumb": thumb,
            "source": "wikimedia",
            "license": license_short,
            "artist": _strip_html((meta.get("Artist") or {}).get("value") or ""),
            "file_page": info.get("descriptionurl") or "",
        })
    return out


def _best_pexels_file(video: dict) -> str | None:
    """Best landscape mp4 file link for one Pexels video hit -- the smallest that still clears
    1080p (least bandwidth), or the largest landscape file when nothing reaches 1080p."""
    files = [
        f for f in video.get("video_files", [])
        if f.get("link") and f.get("file_type") == "video/mp4"
        and f.get("width") and f.get("height") and f["width"] >= f["height"]
    ]
    if not files:
        return None
    fhd = [f for f in files if f["height"] >= VIDEO_MIN_HEIGHT]
    if fhd:
        return min(fhd, key=lambda f: f["width"])["link"]
    return max(files, key=lambda f: f["width"])["link"]


def _best_pixabay_tier(hit: dict) -> dict | None:
    """Best landscape video tier dict for one Pixabay video hit -- smallest tier >=1080p, else
    the tallest. Portrait tiers are dropped (pillarboxing them reads as low-quality/AI-slop)."""
    tiers = [
        t for t in hit.get("videos", {}).values()
        if isinstance(t, dict) and t.get("url") and t.get("width") and t.get("height")
        and t["width"] >= t["height"]
    ]
    if not tiers:
        return None
    fhd = [t for t in tiers if t["height"] >= VIDEO_MIN_HEIGHT]
    return min(fhd, key=lambda t: t["height"]) if fhd else max(tiers, key=lambda t: t["height"])


def _best_pixabay_file(hit: dict) -> str | None:
    """Best landscape video tier URL for one Pixabay video hit (see _best_pixabay_tier)."""
    tier = _best_pixabay_tier(hit)
    return tier["url"] if tier else None


def search_pexels_video(keyword: str, per_page: int = CANDIDATE_POOL) -> list[dict]:
    """Landscape stock-VIDEO candidates (>=1080p mp4 preferred) for `keyword`; [] if
    unconfigured or the call fails. Clips are normalized to 1920x1080@24fps downstream."""
    if _source_disabled("pexels") or not settings.PEXELS_API_KEY:
        return []
    try:
        r = _pexels_client().get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": settings.PEXELS_API_KEY},
            params={"query": keyword, "per_page": per_page, "orientation": "landscape", "size": "medium"},
            timeout=8,
        )
        r.raise_for_status()
        return [
            {"url": url, "thumb": v.get("image", "")}
            for v in r.json().get("videos", []) if (url := _best_pexels_file(v))
        ]
    except Exception as exc:
        log.warning("pexels video search failed for %r: %s", keyword, exc)
        return []


def search_pixabay_video(keyword: str, per_page: int = CANDIDATE_POOL) -> list[dict]:
    """Stock-VIDEO candidates (>=1080p tier preferred) for `keyword`; [] if unconfigured or the
    call fails. Pixabay video is CC0; clips are normalized to 1920x1080@24fps downstream."""
    if _source_disabled("pixabay") or not settings.PIXABAY_API_KEY:
        return []
    try:
        r = _pixabay_client().get(
            "https://pixabay.com/api/videos/",
            params={"key": settings.PIXABAY_API_KEY, "q": keyword, "per_page": per_page},
            timeout=8,
        )
        r.raise_for_status()
        out = []
        for h in r.json().get("hits", []):
            tier = _best_pixabay_tier(h)
            if tier:
                out.append({"url": tier["url"], "thumb": tier.get("thumbnail", "")})
        return out
    except Exception as exc:
        log.warning("pixabay video search failed for %r: %s", keyword, exc)
        return []
