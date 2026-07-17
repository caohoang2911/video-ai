"""Key-free unit tests for thumbnail hero selection, the CLIP relevance gate, and the fal
image layer wiring — all mocked, so no model download, no network, no fal call. Guards the
promises: gate drops wrong-subject archives, Kontext toggle off never touches fal, a failed
Kontext degrades to a PIL grade, and no archival falls back to a synthetic hero."""

from __future__ import annotations

from pathlib import Path

from ai_operator.assembler import thumbnail_generator as tg


class _Video:
    def __init__(self, title):
        self.title = title


# --------------------------------------------------------------------------------------
# relevance gate
# --------------------------------------------------------------------------------------


def test_gate_noop_when_clip_unavailable(monkeypatch):
    monkeypatch.setattr(tg.clip_reranker, "available", lambda: False)
    paths = [Path("a.jpg"), Path("b.jpg")]
    assert tg._relevance_gate(paths, "estonia", 1) == paths  # untouched


def test_gate_noop_when_subject_empty(monkeypatch):
    monkeypatch.setattr(tg.clip_reranker, "available", lambda: True)
    paths = [Path("a.jpg")]
    assert tg._relevance_gate(paths, "", 1) == paths


def test_gate_filters_below_threshold(monkeypatch):
    monkeypatch.setattr(tg.clip_reranker, "available", lambda: True)
    monkeypatch.setattr(tg.settings, "THUMB_RELEVANCE_MIN", 0.22)
    scores = {"good.jpg": 0.31, "wrong.jpg": 0.10}
    monkeypatch.setattr(tg.clip_reranker, "score", lambda subj, p: scores[p.name])
    kept = tg._relevance_gate([Path("good.jpg"), Path("wrong.jpg")], "estonia ferry", 1)
    assert kept == [Path("good.jpg")]  # wrong-subject archive dropped


def test_gate_keeps_on_none_score(monkeypatch):
    monkeypatch.setattr(tg.clip_reranker, "available", lambda: True)
    monkeypatch.setattr(tg.clip_reranker, "score", lambda subj, p: None)  # measure failed
    paths = [Path("a.jpg"), Path("b.jpg")]
    assert tg._relevance_gate(paths, "estonia", 1) == paths  # never punish on a failed measure


# --------------------------------------------------------------------------------------
# hero pick
# --------------------------------------------------------------------------------------


def test_pick_hero_archival_first_no_fal(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("fal must not be called when archival is available")

    monkeypatch.setattr(tg.cloud_flux, "generate", _boom)
    src, mode, synth = tg._pick_hero(_Video("x"), [Path("beat_01.jpg")], 1)
    assert (src, mode, synth) == (Path("beat_01.jpg"), "archival", None)


def test_pick_hero_synthetic_when_no_archival(monkeypatch):
    monkeypatch.setattr(tg.settings, "FAL_KEY", "k")
    monkeypatch.setattr(tg.cloud_flux, "generate", lambda *a, **k: Path("/tmp/synth.jpg"))
    src, mode, synth = tg._pick_hero(_Video("Estonia: sealed"), [], 1)
    assert mode == "synthetic" and src == Path("/tmp/synth.jpg") and synth == Path("/tmp/synth.jpg")


def test_pick_hero_none_without_key(monkeypatch):
    monkeypatch.setattr(tg.settings, "FAL_KEY", None)
    assert tg._pick_hero(_Video("x"), [], 1) == (None, None, None)


def test_pick_hero_synthetic_failure_falls_back(monkeypatch):
    monkeypatch.setattr(tg.settings, "FAL_KEY", "k")

    def _boom(*a, **k):
        raise RuntimeError("fal down")

    monkeypatch.setattr(tg.cloud_flux, "generate", _boom)
    assert tg._pick_hero(_Video("x"), [], 1) == (None, None, None)  # never blocks the thumbnail


# --------------------------------------------------------------------------------------
# hero preparation (Kontext toggle + fallback)
# --------------------------------------------------------------------------------------


def test_prepare_hero_kontext_off_never_calls_fal(monkeypatch):
    monkeypatch.setattr(tg.settings, "THUMBNAIL_KONTEXT_ENHANCE", False)

    def _boom(*a, **k):
        raise AssertionError("Kontext must not be called when the toggle is off")

    monkeypatch.setattr(tg.cloud_flux, "kontext_edit", _boom)
    assert tg._prepare_hero(Path("f.jpg"), "archival", 1) is False  # -> PIL grade, no fal


def test_prepare_hero_synthetic_skips_grade_no_fal(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("no fal for an already-cinematic synthetic hero")

    monkeypatch.setattr(tg.cloud_flux, "kontext_edit", _boom)
    assert tg._prepare_hero(Path("f.jpg"), "synthetic", 1) is True  # already graded


def test_prepare_hero_archival_kontext_success(monkeypatch, tmp_path):
    monkeypatch.setattr(tg.settings, "THUMBNAIL_KONTEXT_ENHANCE", True)
    enhanced = tmp_path / "enh.jpg"
    enhanced.write_bytes(b"x")
    monkeypatch.setattr(tg.cloud_flux, "kontext_edit", lambda p, instr, video_id=None: enhanced)
    monkeypatch.setattr(tg, "_extract_frame", lambda src, out: None)  # no ffmpeg in unit
    assert tg._prepare_hero(tmp_path / "f.jpg", "archival", 1) is True  # graded by Kontext
    assert not enhanced.exists()  # temp cleaned up


def test_prepare_hero_kontext_failure_falls_back_to_pil(monkeypatch):
    monkeypatch.setattr(tg.settings, "THUMBNAIL_KONTEXT_ENHANCE", True)

    def _boom(*a, **k):
        raise RuntimeError("kontext 500")

    monkeypatch.setattr(tg.cloud_flux, "kontext_edit", _boom)
    assert tg._prepare_hero(Path("f.jpg"), "archival", 1) is False  # degrade to PIL grade


# --------------------------------------------------------------------------------------
# synthetic-hero prompt
# --------------------------------------------------------------------------------------


def test_hero_prompt_anchors_on_subject():
    prompt = tg._hero_prompt(_Video("MS Estonia: Why the Wreck Was Sealed"))
    assert "MS Estonia" in prompt and "no text" in prompt


# --------------------------------------------------------------------------------------
# photo credit (CC BY only) + event_year
# --------------------------------------------------------------------------------------


def test_thumb_credit_only_for_cc_by_licenses():
    assert tg._thumb_credit("CC BY-SA 4.0 | Mark Markefelt | http://p") == \
        "Photo: Mark Markefelt · Wikimedia Commons · CC BY-SA 4.0"
    assert tg._thumb_credit("CC BY 2.0 | Bob | http://p").startswith("Photo: Bob")
    assert tg._thumb_credit("CC BY-SA 4.0 | unknown author | http://p").startswith("Photo: Unknown author")
    assert tg._thumb_credit("Public domain | someone | http://p") is None   # PD -> no burn
    assert tg._thumb_credit(None) is None
    assert tg._thumb_credit("only one part") is None


def test_event_year_reads_script_json(tmp_path):
    import json

    p = tmp_path / "script.json"
    p.write_text(json.dumps({"event_year": 1994}))
    assert tg._event_year(p) == 1994
    p.write_text(json.dumps({"event_year": None}))
    assert tg._event_year(p) is None
    assert tg._event_year(tmp_path / "missing.json") is None


# --------------------------------------------------------------------------------------
# generate() wiring: an already-graded hero must NOT be PIL-graded again
# --------------------------------------------------------------------------------------


def test_overlay_texts_coalesces_null_thumbnail_text(tmp_path):
    import json

    p = tmp_path / "script.json"
    p.write_text(json.dumps({"title_options": [{"title": "A", "thumbnail_text": None}, {"title": "B"}]}))
    assert tg._overlay_texts(p) == ["", ""]  # explicit null and missing key both coalesce to ""


def test_generate_kontext_hero_is_not_double_graded(monkeypatch, tmp_path):
    """`_prepare_hero` returning True (Kontext/synthetic = already graded) must make the hero
    variant skip the PIL grade — the b/c real frames still get it."""
    grades: dict[str, bool] = {}

    class _V:
        video_path = str(tmp_path / "v.mp4")
        title = "MS Estonia: Why the Wreck Was Sealed"
        thumb_path = None

    class _S:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, model, vid):
            return _V()

        def commit(self):
            pass

    (tmp_path / "v.mp4").write_bytes(b"x")
    (tmp_path / "9").mkdir()
    monkeypatch.setattr(tg, "SessionLocal", lambda: _S())
    monkeypatch.setattr(tg, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(tg, "_overlay_texts", lambda p: ["NEVER EXPLAINED", "55 MINUTES", "ONE BOLT"])
    monkeypatch.setattr(tg, "_gated_pools", lambda vid: ([tmp_path / "a.jpg"], [], "MS Estonia"))
    monkeypatch.setattr(tg, "_pick_hero", lambda v, a, vid: (tmp_path / "a.jpg", "archival", None))
    monkeypatch.setattr(tg, "_archival_credits", lambda vid: {})  # skip the DB credit lookup
    monkeypatch.setattr(tg, "_prepare_hero", lambda fp, mode, vid: True)  # hero already graded
    monkeypatch.setattr(tg, "_extract_frame", lambda src, out: Path(out).write_bytes(b"f"))

    def _spy(frame_path, text, out_path, kicker, grade=True, credit=None):
        grades[Path(out_path).name] = grade
        Path(out_path).write_bytes(b"o")

    monkeypatch.setattr(tg, "_overlay_text", _spy)

    tg.generate(9)
    assert grades["thumb_a.jpg"] is False  # already-graded hero -> PIL grade SKIPPED
    assert grades["thumb_b.jpg"] is True   # real frames -> PIL grade applied
    assert grades["thumb_c.jpg"] is True
