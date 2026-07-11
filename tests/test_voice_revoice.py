"""Key-free unit tests for the single-brand-voice + revoice gate: checkpoint
invalidate/resume, the ElevenLabs monthly character ledger, per-video provider
selection/resumability, the publish() needs_revoice gate, and the `revoice` CLI command's
full teardown+rebuild. No network/API calls are made -- provider boundaries (ElevenLabs,
edge-tts) are monkeypatched; only local ffmpeg (already required by the pipeline) is used
to produce real short audio files for the tts_narrator integration tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import typer
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_operator import checkpoint
from ai_operator.cost import elevenlabs_char_guard as char_guard
from ai_operator.db.base import Base
from ai_operator.db.models import Video
from ai_operator.db.models_ops import CostLedger
from ai_operator.db.state_machine import VideoState
from ai_operator.media import commands as media_commands
from ai_operator.media import tts_narrator as tn
from ai_operator.media import tts_providers as tp
from ai_operator.media.tts_chunker import TextChunk

# `ai_operator.publisher`'s __init__ does `from .publish import publish`, which rebinds its
# `publish` attribute to the FUNCTION -- any `import ...publisher.publish as x` resolves via
# that same (now-shadowed) attribute chain. Pull the real submodule straight from sys.modules
# so monkeypatch targets the module's own globals (SessionLocal, quota_throttle, ...).
import ai_operator.publisher.publish  # noqa: F401 -- ensures it's registered in sys.modules

pub_mod = sys.modules["ai_operator.publisher.publish"]

# --------------------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------------------


def _make_session_factory(tmp_path: Path):
    """Isolated sqlite db per test -- never touches the real dev data/operator.db."""
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _quota_status(*, exhausted: bool = False, alert: bool = False, used: int = 0) -> char_guard.CharQuotaStatus:
    quota = char_guard.CREATOR_TIER_MONTHLY_CHAR_QUOTA
    return char_guard.CharQuotaStatus(
        ym="2026-07", chars_used=used, quota=quota, pct_used=used / quota, alert=alert, exhausted=exhausted
    )


def _write_silent_audio(path: Path, seconds: float = 0.2) -> None:
    """Real short audio via ffmpeg (already a pipeline dependency) -- forces the mp3 muxer
    regardless of the caller's chosen extension, matching how the real providers write raw
    provider bytes to a `.raw`-suffixed path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(seconds), "-f", "mp3", str(path)],
        check=True, capture_output=True,
    )


# --------------------------------------------------------------------------------------
# Video.needs_revoice column
# --------------------------------------------------------------------------------------


def test_video_needs_revoice_defaults_false(tmp_path):
    Session = _make_session_factory(tmp_path)
    with Session() as s:
        v = Video(idempotency_key="k-default")
        s.add(v)
        s.commit()
        s.refresh(v)
        assert v.needs_revoice is False


# --------------------------------------------------------------------------------------
# checkpoint.invalidate
# --------------------------------------------------------------------------------------


def test_checkpoint_invalidate_removes_only_the_target_step(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", tmp_path)
    checkpoint.write(1, "tts_narration", {"a": 1})
    checkpoint.write(1, "assemble", {"b": 2})

    checkpoint.invalidate(1, "tts_narration")

    assert not checkpoint.is_done(1, "tts_narration")
    assert checkpoint.is_done(1, "assemble")
    assert checkpoint.last_step(1) == "assemble"


def test_checkpoint_invalidate_updates_last_step_when_it_was_the_invalidated_step(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", tmp_path)
    checkpoint.write(2, "a", {})
    checkpoint.write(2, "b", {})
    assert checkpoint.last_step(2) == "b"

    checkpoint.invalidate(2, "b")
    assert checkpoint.last_step(2) == "a"

    checkpoint.invalidate(2, "a")
    assert checkpoint.last_step(2) is None


def test_checkpoint_invalidate_is_noop_when_nothing_to_drop(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", tmp_path)
    checkpoint.invalidate(999, "never-written")  # no checkpoint file at all -- must not raise

    checkpoint.write(3, "a", {})
    checkpoint.invalidate(3, "also-never-written")  # step never existed on an existing file
    assert checkpoint.is_done(3, "a")


# --------------------------------------------------------------------------------------
# elevenlabs_char_guard
# --------------------------------------------------------------------------------------


def test_month_chars_used_sums_only_elevenlabs_current_month(tmp_path, monkeypatch):
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(char_guard, "SessionLocal", Session)
    monkeypatch.setattr(char_guard, "_live_subscription", lambda: None)  # test ledger path, không HTTP
    with Session() as s:
        s.add_all([
            CostLedger(step="tts_elevenlabs", provider="elevenlabs", units=1000, estimated_cost=0.3, ym="2026-07"),
            CostLedger(step="tts_elevenlabs", provider="elevenlabs", units=2000, estimated_cost=0.6, ym="2026-07"),
            CostLedger(step="tts_openai", provider="openai", units=5000, estimated_cost=0.1, ym="2026-07"),
            CostLedger(step="tts_elevenlabs", provider="elevenlabs", units=9999, estimated_cost=3.0, ym="2026-06"),
        ])
        s.commit()

    assert char_guard.month_chars_used("2026-07") == 3000


def test_check_char_quota_alert_fires_at_70_pct_boundary(tmp_path, monkeypatch):
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(char_guard, "SessionLocal", Session)
    monkeypatch.setattr(char_guard, "_live_subscription", lambda: None)  # test ledger path, không HTTP
    # neo quota về hằng mặc định — máy operator có thể override qua .env
    monkeypatch.setattr(char_guard.settings, "ELEVENLABS_MONTHLY_CHAR_QUOTA",
                        char_guard.CREATOR_TIER_MONTHLY_CHAR_QUOTA)
    with Session() as s:
        s.add(CostLedger(
            step="x", provider="elevenlabs",
            units=char_guard.CREATOR_TIER_MONTHLY_CHAR_QUOTA * char_guard.ALERT_THRESHOLD_PCT,
            estimated_cost=0.0, ym="2026-07",
        ))
        s.commit()

    status = char_guard.check_char_quota("2026-07")
    assert status.alert is True
    assert status.exhausted is False


def test_check_char_quota_no_alert_just_under_70_pct(tmp_path, monkeypatch):
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(char_guard, "SessionLocal", Session)
    monkeypatch.setattr(char_guard, "_live_subscription", lambda: None)  # test ledger path, không HTTP
    # neo quota về hằng mặc định — máy operator có thể override qua .env
    monkeypatch.setattr(char_guard.settings, "ELEVENLABS_MONTHLY_CHAR_QUOTA",
                        char_guard.CREATOR_TIER_MONTHLY_CHAR_QUOTA)
    with Session() as s:
        s.add(CostLedger(
            step="x", provider="elevenlabs",
            units=char_guard.CREATOR_TIER_MONTHLY_CHAR_QUOTA * char_guard.ALERT_THRESHOLD_PCT - 1,
            estimated_cost=0.0, ym="2026-07",
        ))
        s.commit()

    assert char_guard.check_char_quota("2026-07").alert is False


def test_check_char_quota_exhausted_at_100_pct(tmp_path, monkeypatch):
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(char_guard, "SessionLocal", Session)
    monkeypatch.setattr(char_guard, "_live_subscription", lambda: None)  # test ledger path, không HTTP
    with Session() as s:
        s.add(CostLedger(
            step="x", provider="elevenlabs",
            units=char_guard.CREATOR_TIER_MONTHLY_CHAR_QUOTA,
            estimated_cost=0.0, ym="2026-07",
        ))
        s.commit()

    assert char_guard.check_char_quota("2026-07").exhausted is True


# --------------------------------------------------------------------------------------
# tts_providers.synthesize_video -- per-video provider selection + resumability
# --------------------------------------------------------------------------------------


def test_synthesize_video_first_chunk_failure_falls_back_to_edge_for_all_chunks(tmp_path, monkeypatch):
    el_calls, edge_calls = [], []

    def fake_el(text, out_path, *, video_id, prev_text, next_text, prev_request_ids):
        el_calls.append(text)
        raise tp.ProviderFailed("simulated 429")

    def fake_edge(text, out_path, voice=tp.EDGE_TTS_VOICE):
        edge_calls.append(text)
        Path(out_path).write_bytes(b"fake-edge-audio")

    monkeypatch.setattr(tp, "synthesize_elevenlabs", fake_el)
    monkeypatch.setattr(tp, "synthesize_edge_tts", fake_edge)
    monkeypatch.setattr(tp.char_guard, "check_char_quota", lambda ym=None: _quota_status())

    chunks = [TextChunk(text=f"chunk {i}", prev_text=None, next_text=None, has_overlap_head=False) for i in range(3)]
    chunk_paths = [tmp_path / f"c{i}.raw" for i in range(3)]
    done: list[tuple[int, str, str | None]] = []

    provider = tp.synthesize_video(
        chunks, chunk_paths, video_id=1, done_indices=set(), prev_request_ids=[],
        on_chunk_done=lambda i, p, r: done.append((i, p, r)),
    )

    assert provider == "edge_tts"
    assert el_calls == ["chunk 0"]           # only the first chunk was ever tried on ElevenLabs
    assert edge_calls == ["chunk 0", "chunk 1", "chunk 2"]  # then EVERY chunk, never a mix
    assert [d[1] for d in done] == ["edge_tts", "edge_tts", "edge_tts"]


def test_synthesize_video_late_chunk_failure_raises_without_edge_fallback(tmp_path, monkeypatch):
    el_calls, edge_calls = [], []

    def fake_el(text, out_path, *, video_id, prev_text, next_text, prev_request_ids):
        el_calls.append(text)
        if text == "chunk 2":
            raise tp.ProviderFailed("simulated network blip")
        Path(out_path).write_bytes(b"audio")
        return f"rid-{text}"

    def fake_edge(text, out_path, voice=tp.EDGE_TTS_VOICE):
        edge_calls.append(text)

    monkeypatch.setattr(tp, "synthesize_elevenlabs", fake_el)
    monkeypatch.setattr(tp, "synthesize_edge_tts", fake_edge)
    monkeypatch.setattr(tp.char_guard, "check_char_quota", lambda ym=None: _quota_status())

    chunks = [TextChunk(text=f"chunk {i}", prev_text=None, next_text=None, has_overlap_head=False) for i in range(3)]
    chunk_paths = [tmp_path / f"c{i}.raw" for i in range(3)]
    done: list[tuple[int, str, str | None]] = []

    with pytest.raises(tp.ProviderFailed):
        tp.synthesize_video(
            chunks, chunk_paths, video_id=1, done_indices=set(), prev_request_ids=[],
            on_chunk_done=lambda i, p, r: done.append((i, p, r)),
        )

    assert edge_calls == []  # a later failure never falls back to edge mid-video
    assert done == [(0, "elevenlabs", "rid-chunk 0"), (1, "elevenlabs", "rid-chunk 1")]


def test_synthesize_video_resumes_missing_tail_only(tmp_path, monkeypatch):
    el_calls = []

    def fake_el(text, out_path, *, video_id, prev_text, next_text, prev_request_ids):
        el_calls.append(text)
        Path(out_path).write_bytes(b"audio")
        return f"rid-{text}"

    def fake_edge(text, out_path, voice=tp.EDGE_TTS_VOICE):
        raise AssertionError("edge-tts must never be reached on a resumed elevenlabs run")

    monkeypatch.setattr(tp, "synthesize_elevenlabs", fake_el)
    monkeypatch.setattr(tp, "synthesize_edge_tts", fake_edge)
    monkeypatch.setattr(tp.char_guard, "check_char_quota", lambda ym=None: _quota_status())

    chunks = [TextChunk(text=f"chunk {i}", prev_text=None, next_text=None, has_overlap_head=False) for i in range(3)]
    chunk_paths = [tmp_path / f"c{i}.raw" for i in range(3)]
    done: list[tuple[int, str, str | None]] = []

    provider = tp.synthesize_video(
        chunks, chunk_paths, video_id=1, done_indices={0, 1},
        prev_request_ids=["rid-chunk 0", "rid-chunk 1"],
        on_chunk_done=lambda i, p, r: done.append((i, p, r)),
    )

    assert provider == "elevenlabs"
    assert el_calls == ["chunk 2"]  # chunks 0/1 never re-billed/re-synthesized
    assert done == [(2, "elevenlabs", "rid-chunk 2")]


def test_synthesize_video_quota_exhausted_from_start_falls_back_to_edge(tmp_path, monkeypatch):
    edge_calls = []

    def fake_el(*a, **k):
        raise AssertionError("elevenlabs must not even be attempted once the char quota is exhausted")

    def fake_edge(text, out_path, voice=tp.EDGE_TTS_VOICE):
        edge_calls.append(text)
        Path(out_path).write_bytes(b"audio")

    monkeypatch.setattr(tp, "synthesize_elevenlabs", fake_el)
    monkeypatch.setattr(tp, "synthesize_edge_tts", fake_edge)
    monkeypatch.setattr(tp.char_guard, "check_char_quota", lambda ym=None: _quota_status(exhausted=True, used=100_000))

    chunks = [TextChunk(text="only chunk", prev_text=None, next_text=None, has_overlap_head=False)]
    chunk_paths = [tmp_path / "c0.raw"]

    provider = tp.synthesize_video(
        chunks, chunk_paths, video_id=1, done_indices=set(), prev_request_ids=[], on_chunk_done=lambda i, p, r: None
    )

    assert provider == "edge_tts"
    assert edge_calls == ["only chunk"]


# --------------------------------------------------------------------------------------
# tts_narrator.synthesize -- integration (real ffmpeg, mocked provider boundary)
# --------------------------------------------------------------------------------------


def test_tts_narrator_synthesize_fallback_sets_needs_revoice(tmp_path, monkeypatch):
    monkeypatch.setattr(tn, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", tmp_path / "checkpoints")

    def fake_synthesize_video(chunks, chunk_paths, *, video_id, done_indices, prev_request_ids, on_chunk_done):
        assert done_indices == set()
        for i, p in enumerate(chunk_paths):
            _write_silent_audio(p)
            on_chunk_done(i, "edge_tts", None)
        return "edge_tts"

    monkeypatch.setattr(tn, "synthesize_video", fake_synthesize_video)

    video_id = 501
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(tn, "SessionLocal", Session)
    with Session() as s:
        s.add(Video(id=video_id, idempotency_key="k-501"))
        s.commit()

    out = tn.synthesize(video_id, "This is the first sentence. This is the second sentence.")

    assert out.exists()
    with Session() as s:
        assert s.get(Video, video_id).needs_revoice is True
    assert checkpoint.artifacts_of(video_id, tn.STEP)["provider"] == "edge_tts"


def test_tts_narrator_synthesize_resumes_after_partial_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(tn, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", tmp_path / "checkpoints")
    fixed_chunks = [
        TextChunk(text="part one", prev_text=None, next_text="part two", has_overlap_head=False),
        TextChunk(text="part two", prev_text="part one", next_text=None, has_overlap_head=False),
    ]
    monkeypatch.setattr(tn, "chunk_narration", lambda text: fixed_chunks)

    video_id = 777
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(tn, "SessionLocal", Session)
    with Session() as s:
        s.add(Video(id=video_id, idempotency_key="k-777"))
        s.commit()

    def crashing_synth(chunks, chunk_paths, *, video_id, done_indices, prev_request_ids, on_chunk_done):
        assert done_indices == set()
        _write_silent_audio(chunk_paths[0])
        on_chunk_done(0, "elevenlabs", "rid-0")
        raise RuntimeError("simulated crash mid-narration")

    monkeypatch.setattr(tn, "synthesize_video", crashing_synth)
    with pytest.raises(RuntimeError, match="simulated crash"):
        tn.synthesize(video_id, "irrelevant -- chunk_narration is mocked")

    saved = checkpoint.artifacts_of(video_id, tn.CHUNKS_STEP)
    assert [c["index"] for c in saved["chunks"]] == [0]  # only the completed chunk survived

    seen: dict[str, set[int]] = {}

    def resuming_synth(chunks, chunk_paths, *, video_id, done_indices, prev_request_ids, on_chunk_done):
        seen["done_indices"] = set(done_indices)
        assert prev_request_ids == ["rid-0"]
        _write_silent_audio(chunk_paths[1])
        on_chunk_done(1, "elevenlabs", "rid-1")
        return "elevenlabs"

    monkeypatch.setattr(tn, "synthesize_video", resuming_synth)
    out = tn.synthesize(video_id, "irrelevant -- chunk_narration is mocked")

    assert seen["done_indices"] == {0}  # chunk 0 was NOT re-synthesized/re-billed
    assert out.exists()
    with Session() as s:
        assert s.get(Video, video_id).needs_revoice is False  # elevenlabs end-to-end


def test_tts_narrator_raises_on_mixed_providers(tmp_path, monkeypatch):
    """Defense-in-depth: even if synthesize_video's own invariant were ever violated, the
    narrator must never silently ship/checkpoint a mixed-provider narration."""
    monkeypatch.setattr(tn, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", tmp_path / "checkpoints")
    fixed_chunks = [
        TextChunk(text="a", prev_text=None, next_text="b", has_overlap_head=False),
        TextChunk(text="b", prev_text="a", next_text=None, has_overlap_head=False),
    ]
    monkeypatch.setattr(tn, "chunk_narration", lambda text: fixed_chunks)

    def mixed_synth(chunks, chunk_paths, *, video_id, done_indices, prev_request_ids, on_chunk_done):
        _write_silent_audio(chunk_paths[0])
        on_chunk_done(0, "elevenlabs", "rid-0")
        _write_silent_audio(chunk_paths[1])
        on_chunk_done(1, "edge_tts", None)
        return "elevenlabs"

    monkeypatch.setattr(tn, "synthesize_video", mixed_synth)

    video_id = 888
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(tn, "SessionLocal", Session)
    with Session() as s:
        s.add(Video(id=video_id, idempotency_key="k-888"))
        s.commit()

    with pytest.raises(RuntimeError, match="mixed TTS providers"):
        tn.synthesize(video_id, "irrelevant -- chunk_narration is mocked")


# --------------------------------------------------------------------------------------
# publish() needs_revoice gate
# --------------------------------------------------------------------------------------


def test_publish_refuses_needs_revoice_video_before_spending_quota(tmp_path, monkeypatch):
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(pub_mod, "SessionLocal", Session)
    with Session() as s:
        s.add(Video(
            id=42, idempotency_key="k-42", needs_revoice=True,
            video_path="output/42/final.mp4", state=VideoState.APPROVED.value,
        ))
        s.commit()

    def _must_not_be_called(*a, **k):
        raise AssertionError("quota must never be touched for a needs_revoice video")

    monkeypatch.setattr(pub_mod.quota_throttle, "ensure_can_publish", _must_not_be_called)

    with pytest.raises(ValueError, match="needs re-voice"):
        pub_mod.publish(42)


# --------------------------------------------------------------------------------------
# revoice command -- full teardown+rebuild
# --------------------------------------------------------------------------------------


def test_revoice_full_teardown_rebuild_on_rendered_video(tmp_path, monkeypatch):
    monkeypatch.setattr(media_commands, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", tmp_path / "checkpoints")

    video_id = 900
    video_dir = tmp_path / str(video_id)
    video_dir.mkdir(parents=True)
    script_path = video_dir / "script.json"
    script_path.write_text(json.dumps({"narration": "Some narration text."}), encoding="utf-8")
    final_path = video_dir / "final.mp4"
    final_path.write_bytes(b"stale-render")

    # Prior full run landed on edge-tts -- exactly why needs_revoice is already True.
    checkpoint.write(video_id, tn.STEP, {"narration_path": str(video_dir / "old.mp3"), "provider": "edge_tts"})
    checkpoint.write(video_id, tn.CHUNKS_STEP, {"total_chunks": 1, "chunks": [
        {"index": 0, "path": str(video_dir / "old.mp3"), "provider": "edge_tts", "request_id": None}
    ]})
    checkpoint.write(video_id, "assemble", {"video_path": str(final_path)})

    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(media_commands, "SessionLocal", Session)
    with Session() as s:
        s.add(Video(
            id=video_id, idempotency_key="k-900", state=VideoState.RENDERED.value,
            script_path=str(script_path), video_path=str(final_path), needs_revoice=True,
        ))
        s.commit()

    new_audio = video_dir / "narration.mp3"

    def fake_synthesize(vid, narration_text):
        assert vid == video_id
        new_audio.write_bytes(b"fresh-elevenlabs-audio")
        checkpoint.write(vid, tn.STEP, {"narration_path": str(new_audio), "provider": "elevenlabs"})
        return new_audio

    monkeypatch.setattr(tn, "synthesize", fake_synthesize)

    media_commands.revoice(video_id=video_id)

    assert not final_path.exists()                              # stale render torn down
    assert checkpoint.artifacts_of(video_id, "assemble") is None  # assemble checkpoint invalidated
    with Session() as s:
        v = s.get(Video, video_id)
        assert v.state == VideoState.VOICED.value  # re-enters assemble's render branch
        assert v.needs_revoice is False            # cleared LAST, only now that it landed
        assert v.audio_path == str(new_audio)


def test_revoice_leaves_render_and_state_untouched_when_elevenlabs_still_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(media_commands, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(checkpoint, "CHECKPOINT_DIR", tmp_path / "checkpoints")

    video_id = 901
    video_dir = tmp_path / str(video_id)
    video_dir.mkdir(parents=True)
    script_path = video_dir / "script.json"
    script_path.write_text(json.dumps({"narration": "Some narration text."}), encoding="utf-8")
    final_path = video_dir / "final.mp4"
    final_path.write_bytes(b"stale-render")

    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(media_commands, "SessionLocal", Session)
    with Session() as s:
        s.add(Video(
            id=video_id, idempotency_key="k-901", state=VideoState.RENDERED.value,
            script_path=str(script_path), video_path=str(final_path), needs_revoice=True,
        ))
        s.commit()

    still_edge_audio = video_dir / "narration.mp3"

    def fake_synthesize_still_edge(vid, narration_text):
        still_edge_audio.write_bytes(b"edge-again")
        checkpoint.write(vid, tn.STEP, {"narration_path": str(still_edge_audio), "provider": "edge_tts"})
        return still_edge_audio

    monkeypatch.setattr(tn, "synthesize", fake_synthesize_still_edge)

    with pytest.raises(typer.Exit):
        media_commands.revoice(video_id=video_id)

    assert final_path.exists()  # left untouched -- nothing better to rebuild from yet
    with Session() as s:
        v = s.get(Video, video_id)
        assert v.state == VideoState.RENDERED.value  # unchanged
        assert v.needs_revoice is True                # still flagged


# --------------------------------------------------------------------------------------
# synthesize_elevenlabs SDK contract (regression: with_raw_response is a context manager)
# --------------------------------------------------------------------------------------


def test_synthesize_elevenlabs_enters_raw_response_context_manager(tmp_path, monkeypatch):
    """On elevenlabs>=2.x `with_raw_response.convert()` returns a CONTEXT MANAGER; the synth must
    enter it with `with` to reach `.data`/`._response`. The prior code touched the wrapper
    directly, so every real synth raised and the video silently fell back to edge-tts. This fakes
    that SDK shape (unmocked synth path) so a regression to non-`with` access fails loudly."""
    import types

    import elevenlabs.client as el_client

    class _RawResp:
        def __init__(self):
            self.data = iter([b"AUDIO", b"BYTES"])
            self._response = types.SimpleNamespace(headers={"request-id": "rid-xyz"})

    class _CM:  # only reachable via `with`; direct attribute access has no .data/._response
        def __enter__(self):
            return _RawResp()

        def __exit__(self, *a):
            return False

    class _FakeClient:
        def __init__(self, api_key=None):
            self.text_to_speech = types.SimpleNamespace(
                with_raw_response=types.SimpleNamespace(convert=lambda **kw: _CM())
            )

    monkeypatch.setattr(el_client, "ElevenLabs", _FakeClient)
    monkeypatch.setattr(tp.settings, "ELEVENLABS_API_KEY", "k")
    monkeypatch.setattr(tp.settings, "ELEVENLABS_VOICE_ID", "v")
    monkeypatch.setattr(tp, "estimate_step", lambda *a, **k: 0.0)
    monkeypatch.setattr(tp, "check_and_reserve", lambda *a, **k: 1)
    monkeypatch.setattr(tp, "record_actual", lambda *a, **k: None)

    out = tmp_path / "narration_chunk.mp3"
    rid = tp.synthesize_elevenlabs(
        "hello", out, video_id=None, prev_text=None, next_text=None, prev_request_ids=[]
    )
    assert out.read_bytes() == b"AUDIOBYTES"  # streamed from r.data inside the context manager
    assert rid == "rid-xyz"                    # request-id read from r._response.headers


def test_check_char_quota_prefers_live_subscription_over_ledger(tmp_path, monkeypatch):
    """Số thật từ ElevenLabs (đúng dashboard) thắng sổ nội bộ — ledger đếm theo lần thử
    (kể cả lần rơi xuống edge-tts) nên overstate; chỉ còn là fallback khi offline."""
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(char_guard, "SessionLocal", Session)
    with Session() as s:  # ledger nói 99k (sắp cháy) — nhưng số thật chỉ 32k/40k
        s.add(CostLedger(step="x", provider="elevenlabs", units=99_000,
                         estimated_cost=0.0, ym="2026-07"))
        s.commit()
    monkeypatch.setattr(char_guard, "_live_subscription", lambda: (32_272, 40_000))

    status = char_guard.check_char_quota("2026-07")
    assert (status.chars_used, status.quota) == (32_272, 40_000)
    assert status.exhausted is False
    assert status.alert is True  # 80.7% >= ngưỡng 70%
