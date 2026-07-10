"""Tiny inline-SVG chart builders — no JS library, no npm, no external requests.

Each function returns a self-contained `<svg>` string dropped into a template with `| safe`.
Safe on empty / single-point / all-equal inputs (no divide-by-zero, no NaN coords).
"""

from __future__ import annotations

_ACCENT = "#4f8cff"
_ACCENT_FILL = "#4f8cff22"
_MUTED = "#8b93a3"


def _empty(width: int, height: int) -> str:
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="no data">'
        f'<text x="{width // 2}" y="{height // 2}" dy=".35em" fill="{_MUTED}" font-size="14" '
        f'text-anchor="middle">chưa có dữ liệu</text></svg>'
    )


def sparkline(points, *, width: int = 680, height: int = 140, stroke: str = _ACCENT,
              fill: str = _ACCENT_FILL) -> str:
    """Line chart with a soft area fill for a numeric series."""
    pts = [float(p) for p in (points or [])]
    n = len(pts)
    if n == 0:
        return _empty(width, height)
    pad = 14
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0  # all-equal -> flat line at mid, no zero-division

    def x(i: int) -> float:
        return width / 2 if n == 1 else pad + (width - 2 * pad) * (i / (n - 1))

    def y(v: float) -> float:
        return height - pad - (height - 2 * pad) * ((v - lo) / span)

    coords = [(round(x(i), 1), round(y(v), 1)) for i, v in enumerate(pts)]
    if n == 1:  # single point: a centered dot on a baseline
        cx, cy = coords[0]
        return (
            f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="trend">'
            f'<circle cx="{cx}" cy="{cy}" r="4" fill="{stroke}"/></svg>'
        )
    line = " ".join(f"{cx},{cy}" for cx, cy in coords)
    area = (
        f"M {pad},{height - pad} "
        + " ".join(f"L {cx},{cy}" for cx, cy in coords)
        + f" L {round(x(n - 1), 1)},{height - pad} Z"
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="trend">'
        f'<path d="{area}" fill="{fill}" stroke="none"/>'
        f'<polyline points="{line}" fill="none" stroke="{stroke}" stroke-width="2.5" '
        f'stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def bar_chart(points, *, width: int = 680, height: int = 140, fill: str = _ACCENT) -> str:
    """Vertical bars for a small numeric series."""
    vals = [float(p) for p in (points or [])]
    n = len(vals)
    if n == 0:
        return _empty(width, height)
    pad = 14
    hi = max(vals) or 1.0
    slot = (width - 2 * pad) / n
    bw = max(2.0, slot * 0.6)
    bars = []
    for i, v in enumerate(vals):
        bh = (height - 2 * pad) * (v / hi)
        bx = pad + slot * i + (slot - bw) / 2
        by = height - pad - bh
        bars.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{fill}" rx="2"/>')
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="bars">'
        + "".join(bars)
        + "</svg>"
    )


def views_sparkline(views) -> str:
    """Convenience wrapper: the cumulative-views trend line."""
    return sparkline(views)
