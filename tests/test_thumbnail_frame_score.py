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


def _wide_bars() -> Image.Image:
    """A second usable frame that is NOT a near-duplicate of `_photo_like`: horizontal split
    with a bright subject low-left, so contrast is high but the fingerprint differs."""
    img = Image.new("RGB", SIZE, (20, 24, 30))
    ImageDraw.Draw(img).rectangle([0, 200, SIZE[0], SIZE[1]], fill=(225, 220, 205))
    return img


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


def test_rank_dedupes_same_photo_when_another_usable_frame_exists(tmp_path):
    paths = []
    for i, img in enumerate([_photo_like(), _photo_like(), _wide_bars()]):
        p = tmp_path / f"beat_{i:02d}.jpg"
        img.save(p)
        paths.append(p)
    picked = fs.rank(paths, 2)
    assert len(picked) == 2
    assert paths[2] in picked                                     # the distinct frame is taken
    assert not (paths[0] in picked and paths[1] in picked)        # twin crops burn one slot max


def test_rank_prefers_a_duplicate_photo_over_an_unusable_frame(tmp_path):
    """Slot-filling order: a second crop of a real photograph is still a usable thumbnail,
    a newspaper-scan-like page is not — so the duplicate wins the leftover slot."""
    paths = []
    for i, img in enumerate([_flat_grey(), _photo_like(), _photo_like(), _text_dense()]):
        p = tmp_path / f"beat_{i:02d}.jpg"
        img.save(p)
        paths.append(p)
    picked = fs.rank(paths, 2)
    assert picked == [paths[1], paths[2]] or picked == [paths[2], paths[1]]
    assert paths[0] not in picked and paths[3] not in picked      # unusable frames stay out


def test_rank_relaxes_dedupe_rather_than_come_up_short(tmp_path):
    paths = []
    for i in range(3):  # three copies of the same photo
        p = tmp_path / f"beat_{i:02d}.jpg"
        _photo_like().save(p)
        paths.append(p)
    assert len(fs.rank(paths, 3)) == 3


def test_score_orders_photo_above_flat():
    assert fs.score_image(_photo_like()) > fs.score_image(_flat_grey())


def test_usable_separates_photographs_from_print_and_mush(tmp_path):
    """The admission test callers apply before grouping candidates: photographs in, dense print
    and flat grey out."""
    def _saved(img, name):
        p = tmp_path / name
        img.save(p)
        return p

    assert fs.usable(_saved(_photo_like(), "photo.jpg"))
    assert fs.usable(_saved(_wide_bars(), "bars.jpg"))
    assert not fs.usable(_saved(_text_dense(), "scan.jpg"))
    assert not fs.usable(_saved(_flat_grey(), "grey.jpg"))
    assert not fs.usable(tmp_path / "missing.jpg")  # unreadable scores -inf
