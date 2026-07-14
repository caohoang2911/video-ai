"""shorts_runner: child creation, idempotency, force re-roll, no-recurse, partial failure.

LLM, TTS, and the vertical render are patched at module boundaries; the DB is temp_db.
"""

import json
from unittest.mock import patch

import pytest

from ai_operator.content.short_schema import ShortScript
from ai_operator.db.engine import SessionLocal
from ai_operator.db.models import Video
from ai_operator.db.state_machine import VideoState
from ai_operator.ops import shorts_runner


def _short(i: int) -> ShortScript:
    return ShortScript.model_validate({
        "title": f"Short number {i} title here",
        "text_overlay": f"Hook {i}",
        "narration": " ".join(["word"] * 90),
        "beats": [{"keywords": ["steamboat"], "mood": "tense"}] * 3,
        "curiosity_question": f"Question {i}?",
        "hashtags": [],
    })


@pytest.fixture
def published_main(temp_db, tmp_path, monkeypatch):
    """A published main video with a script.json + one beat image on disk."""
    monkeypatch.setattr(shorts_runner, "OUTPUT_DIR", tmp_path)
    with SessionLocal() as s:
        v = Video(state=VideoState.PUBLISHED.value, idempotency_key="main:test", kind="main")
        s.add(v)
        s.commit()
        vid = v.id
    vdir = tmp_path / str(vid)
    (vdir / "img").mkdir(parents=True)
    (vdir / "img" / "beat_01.jpg").write_bytes(b"jpg")
    (vdir / "script.json").write_text(json.dumps({
        "shot_list": [{"beat_id": 1, "keywords": ["steamboat"], "mood": "tense"}],
        "payoff_nodes": [], "citations": [], "sources": [],
    }))
    return vid


def _run(parent_id: int, shorts=None, *, force: bool = False, render_boom: set[int] | None = None):
    """Run generate_shorts with LLM/TTS/render/notify patched out."""
    shorts = shorts if shorts is not None else [_short(1), _short(2), _short(3)]
    calls = {"rendered": []}

    def fake_build(video_id):
        if render_boom and video_id in render_boom:
            raise RuntimeError("render boom")
        calls["rendered"].append(video_id)
        return {"video_path": "x", "duration_sec": 40}

    def fake_synth(video_id, _text):
        p = shorts_runner.OUTPUT_DIR / str(video_id) / "narration.mp3"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"mp3")
        return p

    with patch.object(shorts_runner, "generate_short_scripts", return_value=shorts), \
         patch.object(shorts_runner.tts_narrator, "synthesize", side_effect=fake_synth), \
         patch.object(shorts_runner, "_source_short_images", side_effect=lambda *a, **k: None), \
         patch.object(shorts_runner, "build_short", side_effect=fake_build), \
         patch.object(shorts_runner, "notify", side_effect=AssertionError("no notify in tests")):
        ids = shorts_runner.generate_shorts(parent_id, force=force)
    return ids, calls


def _children(parent_id):
    with SessionLocal() as s:
        return s.query(Video).filter_by(parent_id=parent_id).order_by(Video.id).all()


def test_creates_children_with_kind_and_parent(published_main):
    ids, _ = _run(published_main)
    kids = _children(published_main)
    assert len(ids) == len(kids) == 3
    assert all(k.kind == "short" and k.parent_id == published_main for k in kids)
    # Telegram unconfigured in tests -> stops at voiced-state advance done by build stub;
    # states were driven scripted -> voiced by the runner
    assert all(k.idempotency_key == f"short:{published_main}:{i}" for i, k in enumerate(kids))
    # publish reads the upload body via script_path — it must point at the child's script.json
    for k in kids:
        assert k.script_path and k.script_path.endswith(f"{k.id}/script.json")
        assert json.loads(open(k.script_path).read())["curiosity_question"].endswith("?")


def test_rerun_without_force_is_noop(published_main):
    _run(published_main)
    ids2, _ = _run(published_main)
    assert ids2 == []
    assert len(_children(published_main)) == 3


def test_force_discards_unpublished_and_rerolls(published_main):
    _run(published_main)
    first_ids = [k.id for k in _children(published_main)]
    # publish one child; it must survive the re-roll
    with SessionLocal() as s:
        kept = s.get(Video, first_ids[0])
        kept.state = VideoState.PUBLISHED.value
        s.commit()
    ids2, _ = _run(published_main, force=True)
    kids = _children(published_main)
    assert len(ids2) == 3
    assert first_ids[0] in [k.id for k in kids]  # published short kept
    assert len(kids) == 4                         # 1 kept + 3 fresh (old unpublished discarded)
    # NOTE: no id-disjointness assert — SQLite reuses rowids after DELETE. The kept short is
    # the only published one; every other child must be from the fresh batch (ids2).
    others = [k for k in kids if k.id != first_ids[0]]
    assert all(k.id in ids2 for k in others)
    assert sum(k.state == VideoState.PUBLISHED.value for k in kids) == 1


def test_short_never_spawns_shorts(published_main):
    ids, _ = _run(published_main)
    child = ids[0]
    ids2, calls = _run(child)
    assert ids2 == [] and calls["rendered"] == []


def test_force_discard_survives_fk_enforcement_and_dependent_rows(temp_db_fk, tmp_path, monkeypatch):
    """The real engine runs PRAGMA foreign_keys=ON and real shorts carry CostLedger/Decision
    rows — the discard must detach/remove them, delete DB rows FIRST, and only then touch
    files (a failed delete must never orphan artifacts)."""
    from ai_operator.db.models import Decision
    from ai_operator.db.models_ops import CostLedger

    monkeypatch.setattr(shorts_runner, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(shorts_runner, "CHECKPOINT_DIR", tmp_path / "checkpoints")
    with SessionLocal() as s:
        parent = Video(state=VideoState.PUBLISHED.value, idempotency_key="m:fk", kind="main")
        s.add(parent)
        s.commit()
        child = Video(state=VideoState.REJECTED.value, kind="short", parent_id=parent.id,
                      idempotency_key=f"short:{parent.id}:0")
        s.add(child)
        s.commit()
        s.add(Decision(video_id=child.id, tier="policy", decision_code="REJECT_POLICY_AUDIO"))
        s.add(CostLedger(video_id=child.id, ym="2026-07", provider="elevenlabs",
                         step="tts", units=1, estimated_cost=0.01))
        s.commit()
        child_id, parent_id = child.id, parent.id
    (tmp_path / str(child_id)).mkdir(parents=True)
    (tmp_path / str(child_id) / "final.mp4").write_bytes(b"mp4")

    with SessionLocal() as s:
        children = s.query(Video).filter_by(parent_id=parent_id).all()
    shorts_runner._discard_unpublished(children)

    with SessionLocal() as s:
        assert s.get(Video, child_id) is None
        assert s.query(Decision).filter_by(video_id=child_id).count() == 0
        ledger = s.query(CostLedger).filter_by(provider="elevenlabs").one()
        assert ledger.video_id is None  # spend history kept, detached
    assert not (tmp_path / str(child_id)).exists()


def test_one_failing_short_does_not_abort_batch(published_main):
    # child ids are allocated sequentially after the parent; boom the SECOND child's render
    with SessionLocal() as s:
        next_id = s.query(Video).order_by(Video.id.desc()).first().id + 2
    ids, _ = _run(published_main, render_boom={next_id})
    kids = _children(published_main)
    assert len(kids) == 3
    failed = [k for k in kids if k.state == VideoState.FAILED.value]
    assert len(failed) == 1 and len(ids) == 2


def test_source_images_reuses_when_parent_has_enough_distinct_stills(tmp_path, monkeypatch):
    """Enough distinct parent stills -> reuse path (no API refetch)."""
    from ai_operator.ops import shorts_runner as sr

    monkeypatch.setattr(sr, "OUTPUT_DIR", tmp_path)
    img = tmp_path / "6" / "img"
    img.mkdir(parents=True)
    for i in range(1, 6):
        (img / f"beat_{i:02d}.jpg").write_bytes(f"distinct-{i}".encode())

    class _Beat:
        keywords, mood = ["k"], "m"
    short = type("S", (), {"beats": [_Beat()] * 3})()

    calls = {"reuse": 0, "refetch": 0}
    monkeypatch.setattr(sr, "_reuse_parent_images", lambda *a, **k: calls.__setitem__("reuse", 1))
    monkeypatch.setattr(sr, "_refetch_short_stills", lambda *a, **k: calls.__setitem__("refetch", 1))
    sr._source_short_images(6, {}, 99, short)
    assert calls == {"reuse": 1, "refetch": 0}


def test_source_images_refetches_when_parent_stills_are_duplicates(tmp_path, monkeypatch):
    """Parent rendered from b-roll: files exist but collapse to 1 distinct md5 -> refetch."""
    from ai_operator.ops import shorts_runner as sr

    monkeypatch.setattr(sr, "OUTPUT_DIR", tmp_path)
    img = tmp_path / "6" / "img"
    img.mkdir(parents=True)
    for i in (2, 3):  # same bytes -> 1 distinct, mirrors the real video-6 bug
        (img / f"beat_{i:02d}.jpg").write_bytes(b"same-archival-leftover")

    class _Beat:
        keywords, mood = ["k"], "m"
    short = type("S", (), {"beats": [_Beat()] * 5})()

    calls = {"reuse": 0, "refetch": 0}
    monkeypatch.setattr(sr, "_reuse_parent_images", lambda *a, **k: calls.__setitem__("reuse", 1))
    monkeypatch.setattr(sr, "_refetch_short_stills", lambda *a, **k: calls.__setitem__("refetch", 1))
    sr._source_short_images(6, {}, 99, short)
    assert calls == {"reuse": 0, "refetch": 1}
