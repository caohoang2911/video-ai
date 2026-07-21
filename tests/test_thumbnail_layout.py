"""Negative-space region detection: a flat frame gets a plain overlay box, a subject that
fills the frame asks for a letterbox bar, and the headline is left-locked (always the left
column) while sliding vertically to dodge the busiest left band."""

from __future__ import annotations

import numpy as np
from PIL import Image

from ai_operator.assembler import thumbnail_layout as tl

SIZE = (1280, 720)


def _from_gray(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(arr.astype(np.uint8), "L").resize(SIZE).convert("RGB")


def test_flat_frame_needs_no_bar():
    box, needs_bar = tl.text_region(Image.new("RGB", SIZE, (90, 90, 90)))
    assert needs_bar is False
    x0, y0, x1, y1 = box
    assert 0 <= x0 < x1 <= SIZE[0] and 0 <= y0 < y1 <= SIZE[1]


def test_busy_frame_needs_bar():
    rng = np.random.default_rng(0)
    noisy = rng.integers(0, 255, size=(90, 160))  # high-frequency detail everywhere
    _, needs_bar = tl.text_region(_from_gray(noisy))
    assert needs_bar is True


def test_region_is_left_locked():
    # Even when the RIGHT half is the calm one, the headline must stay in the LEFT column
    # (synchronized poster placement) rather than jumping to the calmer right side.
    rng = np.random.default_rng(1)
    arr = np.full((90, 160), 128, dtype=np.float64)
    arr[:, :80] = rng.integers(0, 255, size=(90, 80))  # left half busy, right half flat
    box, _ = tl.text_region(_from_gray(arr))
    assert box[0] < SIZE[0] * 0.10          # hugs the left edge
    assert box[2] <= SIZE[0] * 0.55          # a left column, never a right/full-width band


def test_left_column_slides_down_to_dodge_busy_top():
    # Busy UPPER-left, calm lower-left -> the headline stays LEFT but drops to the lower band.
    rng = np.random.default_rng(2)
    arr = np.full((90, 160), 128, dtype=np.float64)
    arr[:40, :83] = rng.integers(0, 255, size=(40, 83))  # top-left busy, everything else flat
    box, _ = tl.text_region(_from_gray(arr))
    assert box[0] < SIZE[0] * 0.10           # still the left column
    assert box[1] > SIZE[1] * 0.30           # slid down, off the busy top band
