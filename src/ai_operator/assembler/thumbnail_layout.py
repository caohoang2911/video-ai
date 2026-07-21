"""Negative-space detection for thumbnail text placement.

The headline must land in the emptiest region of the frame (sky, water, blurred
background) so the subject is never covered. This scores a handful of edge-anchored
candidate boxes by how "busy" (high-gradient) they are and returns the calmest one.
When even the calmest box is still busy — the subject fills the whole frame — the
caller is told (`needs_bar`) to lay a cinematic letterbox bar there instead, which
still keeps the subject fully visible rather than zooming or covering the center.

Pure numpy luminance-gradient analysis, same cheap primitive as thumbnail_frame_score
— no ML, deterministic, instant.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

_ANALYSIS_SIZE = (160, 90)  # small luminance grid; gradient stats are stable at this size

# Candidate text regions as (x0, y0, x1, y1) fractions plus a small preference bonus
# (subtracted from busyness). The headline is LEFT-LOCKED — every candidate shares the same
# left edge and ~52% right edge, so the title always reads as a movie-poster column down the
# LEFT with the subject breathing on the right, synchronized across all variants (never
# jumping to the right or a corner). Only the VERTICAL band flexes: the tall column is the
# strong default, and top-/bottom-left let the headline slide up or down to dodge the busiest
# left band (a face or detail sitting mid-left) while staying on the left. Biases just break
# near-ties; a clearly busier band still yields to a calmer one.
_CANDIDATES = (
    ("left", (0.045, 0.10, 0.52, 0.88), 0.022),
    ("bottom-left", (0.045, 0.44, 0.52, 0.92), 0.008),
    ("top-left", (0.045, 0.07, 0.52, 0.56), 0.006),
)

# Mean gradient magnitude (0..1 luminance) above which a region reads as "busy". Empty
# sky/water sits ~0.02-0.06; a detailed subject ~0.10+. Kept lenient so a poster headline may
# lightly overlap a subject edge (acceptable) — only a frame busy everywhere flips needs_bar.
_EMPTY_MAX = 0.10


def text_region(img: Image.Image) -> tuple[tuple[int, int, int, int], bool]:
    """Return `(box_px, needs_bar)`: the calmest edge-anchored box in pixel coords, and
    whether the frame is too busy for a plain overlay (caller darkens the box more heavily)."""
    w, h = img.size
    g = np.asarray(img.convert("L").resize(_ANALYSIS_SIZE), dtype=np.float32) / 255.0
    gy, gx = np.gradient(g)
    mag = np.hypot(gx, gy)
    aw, ah = _ANALYSIS_SIZE

    best_frac, best_adj, min_busy = _CANDIDATES[0][1], float("inf"), float("inf")
    for _name, frac, bonus in _CANDIDATES:
        x0, y0, x1, y1 = frac
        cell = mag[int(y0 * ah):int(y1 * ah), int(x0 * aw):int(x1 * aw)]
        busy = float(cell.mean()) if cell.size else float("inf")
        min_busy = min(min_busy, busy)  # RAW busyness of the calmest region, unbiased
        adjusted = busy - bonus
        if adjusted < best_adj:
            best_frac, best_adj = frac, adjusted

    x0, y0, x1, y1 = best_frac
    box = (int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))
    # needs_bar from the calmest region's RAW busyness (not the biased pick), so the small
    # placement bias never forces a heavier scrim than the frame actually warrants.
    return box, min_busy > _EMPTY_MAX
