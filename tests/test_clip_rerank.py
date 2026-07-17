"""Key-free unit tests for CLIP relevance re-ranking: the scorer degrades to identity order on
any failure (no model download in tests -- the model is monkeypatched to raise), and the
visual_fetcher integration reorders candidates by score, no-ops when CLIP is unavailable, and
keeps candidates whose thumbnail failed to download (appended after the ranked ones)."""

from __future__ import annotations

from pathlib import Path

from ai_operator.media import clip_reranker
from ai_operator.media import visual_fetcher as vf


# --------------------------------------------------------------------------------------
# clip_reranker.rank -- always safe
# --------------------------------------------------------------------------------------


def test_rank_identity_for_zero_or_one_image():
    assert clip_reranker.rank("x", []) == []
    assert clip_reranker.rank("x", [Path("a.jpg")]) == [0]


def test_rank_falls_back_to_identity_when_model_unavailable(monkeypatch):
    # never downloads the model: _model raises, rank must swallow it and keep the given order
    def _boom():
        raise RuntimeError("no model")

    monkeypatch.setattr(clip_reranker, "_model", _boom)
    assert clip_reranker.rank("naval battle", [Path("a.jpg"), Path("b.jpg"), Path("c.jpg")]) == [0, 1, 2]


# --------------------------------------------------------------------------------------
# visual_fetcher._rank_candidates integration
# --------------------------------------------------------------------------------------


def _cands():
    return [{"url": "a", "thumb": "ta"}, {"url": "b", "thumb": "tb"}, {"url": "c", "thumb": "tc"}]


def test_rank_candidates_noop_when_clip_unavailable(monkeypatch):
    monkeypatch.setattr(vf.clip_reranker, "available", lambda: False)
    cands = _cands()
    assert vf._rank_candidates("naval", cands) == cands  # untouched provider order


def test_rank_candidates_reorders_by_clip_score(monkeypatch):
    monkeypatch.setattr(vf.clip_reranker, "available", lambda: True)
    monkeypatch.setattr(vf, "_download_thumb", lambda url, dest: dest)          # all thumbs "download"
    monkeypatch.setattr(vf.clip_reranker, "rank", lambda text, imgs: [2, 0, 1])  # scored order

    ranked = vf._rank_candidates("naval battle", _cands())
    assert [c["url"] for c in ranked] == ["c", "a", "b"]


def test_rank_candidates_keeps_failed_thumb_candidates_last(monkeypatch):
    monkeypatch.setattr(vf.clip_reranker, "available", lambda: True)
    # candidate "b" has no downloadable thumbnail -> excluded from ranking, appended at the end
    monkeypatch.setattr(vf, "_download_thumb", lambda url, dest: None if url == "tb" else dest)
    monkeypatch.setattr(vf.clip_reranker, "rank", lambda text, imgs: [1, 0])   # reverse the 2 ranked

    ranked = vf._rank_candidates("naval battle", _cands())
    assert [c["url"] for c in ranked] == ["c", "a", "b"]  # c,a ranked (reversed); b (no thumb) last


# --------------------------------------------------------------------------------------
# clip_reranker.score -- absolute relevance for the thumbnail gate, best-effort None
# --------------------------------------------------------------------------------------


def test_score_none_for_empty_text():
    assert clip_reranker.score("", Path("a.jpg")) is None


def test_score_none_when_model_unavailable(monkeypatch):
    def _boom():
        raise RuntimeError("no model")

    monkeypatch.setattr(clip_reranker, "_model", _boom)
    assert clip_reranker.score("estonia ferry", Path("a.jpg")) is None
