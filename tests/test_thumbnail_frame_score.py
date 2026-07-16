"""Key-free unit tests for thumbnail frame scoring: contrasty photo-like frames outrank
text-dense (newspaper-scan-like) and flat grey frames, ranking prefers non-adjacent beats,
and unreadable files sink to the bottom. Pure PIL+numpy; no ffmpeg, no network."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from ai_operator.assembler import thumbnail_frame_score as fs

SIZE = (640, 360)


def _photo_like() -> Image.Image:
    """Smooth vertical gradient with one big dark subject blob: high contrast, sparse edges."""
    grad = np.tile(np.linspace(40, 230, SIZE[1], dtype=np.uint8)[:, None], (1, SIZE[0]))
    img = Image.fromarray(grad, "L").convert("RGB")
    ImageDraw.Draw(img).ellipse([200, 90, 440, 280], fill=(15, 15, 15))
    return img


def _text_dense() -> Image.Image:
    """Dense print-like texture: strong edges everywhere, like a newspaper page scan."""
    rng = np.random.default_rng(7)
    noise = (rng.random((SIZE[1], SIZE[0])) > 0.5).astype(np.uint8) * 255
    return Image.fromarray(noise, "L").convert("RGB")


def _flat_grey() -> Image.Image:
    return Image.new("RGB", SIZE, (128, 128, 128))


def test_photo_outranks_text_dense_and_flat():
    photo = fs.score_image(_photo_like())
    assert photo > fs.score_image(_text_dense())
    assert photo > fs.score_image(_flat_grey())


def test_unreadable_file_scores_neg_inf(tmp_path):
    bad = tmp_path / "not_an_image.jpg"
    bad.write_bytes(b"garbage")
    assert fs.score_path(bad) == float("-inf")


def test_rank_puts_best_first_and_dedupes_same_photo(tmp_path):
    paths = []
    for i, img in enumerate([_flat_grey(), _photo_like(), _photo_like(), _text_dense()]):
        p = tmp_path / f"beat_{i:02d}.jpg"
        img.save(p)
        paths.append(p)
    picked = fs.rank(paths, 2)
    assert len(picked) == 2
    assert picked[0] in (paths[1], paths[2])                      # a photo-like frame wins
    assert not (paths[1] in picked and paths[2] in picked)        # twin crops burn one slot max


def test_rank_relaxes_dedupe_rather_than_come_up_short(tmp_path):
    paths = []
    for i in range(3):  # three copies of the same photo
        p = tmp_path / f"beat_{i:02d}.jpg"
        _photo_like().save(p)
        paths.append(p)
    assert len(fs.rank(paths, 3)) == 3


def test_score_orders_photo_above_flat():
    assert fs.score_image(_photo_like()) > fs.score_image(_flat_grey())
