"""Numpy-only frame scoring for thumbnail source selection: prefer frames with strong
contrast and a clear subject, reject text-dense pages (newspaper scans) and flat/washed
frames. Pure luminance statistics — no OpenCV dependency, fast enough to score every
candidate asset of a video at render time.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

# Analysis resolution: small enough to be instant, big enough for edge statistics.
_ANALYSIS_SIZE = (320, 180)

# Fraction of strong-edge pixels above which a frame reads as dense print/typography
# (newspaper scans sit far above photographs) and gets penalized hard.
_BUSY_EDGE_FRACTION = 0.10
_STRONG_EDGE = 0.12  # gradient magnitude threshold for a "strong" edge (0..~1 luminance)

# Luminance std below this reads as a flat, washed-out frame at feed size.
_FLAT_CONTRAST = 0.10

# Perceptual dedupe: mean-abs-diff between 32x18 grayscale fingerprints. Crops/copies of the
# same photograph land ~0.02; genuinely different photos of one event land ~0.15.
_DEDUPE_SIZE = (32, 18)
_DUPLICATE_MAE = 0.10

# Below this a frame is unusable AT ANY RANK, not merely worse: measured across every rendered
# video, photographic candidates all score above 0.3 while print scans (newspaper pages, trade
# advertisements) and foliage-busy modern snapshots all score below 0. Ordering alone cannot
# express that — when a candidate group holds only as many images as there are variants, the
# worst one still takes a slot however far it is demoted. So drop them outright.
_UNUSABLE_SCORE = 0.0


def score_image(img: Image.Image) -> float:
    """Higher is better. Combines global contrast + edge detail, penalizing frames that
    are either text-dense (uniform strong edges everywhere) or flat/low-contrast."""
    g = np.asarray(img.convert("L").resize(_ANALYSIS_SIZE), dtype=np.float32) / 255.0
    contrast = float(g.std())
    gy, gx = np.gradient(g)
    mag = np.hypot(gx, gy)
    detail = float(mag.mean())
    busy = float((mag > _STRONG_EDGE).mean())

    s = contrast * 2.0 + min(detail * 8.0, 1.0)
    if busy > _BUSY_EDGE_FRACTION:  # dense typography / print page
        s -= (busy - _BUSY_EDGE_FRACTION) * 8.0
    if contrast < _FLAT_CONTRAST:  # grey mush that vanishes in the feed
        s -= (_FLAT_CONTRAST - contrast) * 6.0
    return s


def score_path(path: Path) -> float:
    """Score an image file; unreadable files score -inf so they are never picked."""
    try:
        with Image.open(path) as img:
            return score_image(img)
    except Exception:
        return float("-inf")


def usable(path: Path) -> bool:
    """Whether a frame is fit to face a video at all. Callers that group candidates before
    ranking (by event relevance, say) must filter with this FIRST: `rank` can only order
    within the group it is given, so a group holding exactly as many candidates as there are
    variants hands every one of them a slot however bad they are."""
    return score_path(path) > _UNUSABLE_SCORE


def rank(paths: list[Path], n: int) -> list[Path]:
    """Top-`n` paths by score, best first, skipping near-duplicates of already-picked frames
    (the same archival photo often backs several beats as different crops — two variants of
    one photo would waste an A/B slot). Unusable frames are passed over while anything else
    remains, but both filters are relaxed rather than coming up short: an all-unusable pool
    still yields its best members, and a literally-repeated Path is returned only once."""
    if n <= 0:
        return []
    scores = {p: score_path(p) for p in paths}
    ordered = sorted(scores, key=lambda p: scores[p], reverse=True)

    picked: list[Path] = []
    fingerprints: list[np.ndarray | None] = []
    for p in ordered:  # first choice: usable AND visually distinct
        if scores[p] <= _UNUSABLE_SCORE:
            break  # `ordered` is descending, so nothing past here is usable either
        fp = _fingerprint(p)
        if fp is not None and any(
            f is not None and float(np.abs(fp - f).mean()) < _DUPLICATE_MAE for f in fingerprints
        ):
            continue
        picked.append(p)
        fingerprints.append(fp)
        if len(picked) == n:
            return picked
    # Short of distinct frames, fill by score. Descending order means a second crop of a real
    # photograph (still a usable thumbnail) is reached for before any print scan, and an
    # unusable frame only to avoid returning fewer than asked.
    for p in ordered:
        if p not in picked:
            picked.append(p)
            if len(picked) == n:
                return picked
    return picked


def _fingerprint(path: Path) -> np.ndarray | None:
    """Tiny grayscale signature for near-duplicate detection; None when unreadable."""
    try:
        with Image.open(path) as img:
            return np.asarray(img.convert("L").resize(_DEDUPE_SIZE), dtype=np.float32) / 255.0
    except Exception:
        return None
