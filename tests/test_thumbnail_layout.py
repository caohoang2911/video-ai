"""Negative-space region detection: a flat frame gets a plain overlay box, a subject that
fills the frame asks for a letterbox bar, and text avoids the busy half of a frame."""

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


def test_region_avoids_the_busy_half():
    rng = np.random.default_rng(1)
    arr = np.full((90, 160), 128, dtype=np.float64)
    arr[:, :80] = rng.integers(0, 255, size=(90, 80))  # left half busy, right half flat
    box, _ = tl.text_region(_from_gray(arr))
    assert box[0] > SIZE[0] * 0.4  # chosen region sits in the calm right half, not over the busy left
