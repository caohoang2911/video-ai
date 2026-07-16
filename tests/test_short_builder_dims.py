"""short_builder drives the shared helpers at 1080x1920 — asserted at the module
boundaries (no real ffmpeg render)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_operator.assembler import short_builder
from ai_operator.db.engine import SessionLocal
from ai_operator.db.models import Video
from ai_operator.db.state_machine import VideoState


@pytest.fixture
def voiced_short(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(short_builder, "OUTPUT_DIR", tmp_path)
    with SessionLocal() as s:
        v = Video(state=VideoState.VOICED.value, idempotency_key="short:test:0", kind="short")
        s.add(v)
        s.commit()
        vid = v.id
    vdir = tmp_path / str(vid)
    (vdir / "img").mkdir(parents=True)
    for i in (1, 2, 3):
        (vdir / "img" / f"beat_{i:02d}.jpg").write_bytes(b"jpg")
    (vdir / "narration.mp3").write_bytes(b"mp3")
    (vdir / "script.json").write_text(json.dumps({
        "text_overlay": "Hook line",
        "curiosity_question": "Why?",
        "beats": [{"keywords": ["k"], "mood": "m"}] * 3,
    }))
    return vid


def test_build_short_targets_portrait_dims(voiced_short, tmp_path):
    seen = {"kenburns_sizes": [], "card_sizes": []}

    def fake_still(src, out, overlay_text=None):
        out.write_bytes(b"png")
        return out

    def fake_segment(image_path, duration, out_path, motion="zoom_in", size=(1920, 1080), **kw):
        seen["kenburns_sizes"].append(size)
        out_path.write_bytes(b"mp4")
        return out_path

    def fake_card(last_still, card_copy, out, work):
        seen["card_sizes"].append(short_builder.SHORT_SIZE)
        return out

    with patch.object(short_builder, "_portrait_still", side_effect=fake_still), \
         patch.object(short_builder.kenburns_ffmpeg, "render_segment", side_effect=fake_segment), \
         patch.object(short_builder, "_end_card", side_effect=fake_card), \
         patch.object(short_builder, "transcribe", return_value=[{"start": 0, "end": 1, "text": "x"}]), \
         patch.object(short_builder.ffmpeg_encode, "probe_duration", return_value=40.0), \
         patch.object(short_builder.ffmpeg_encode, "concat_copy", side_effect=lambda segs, out, **kw: out), \
         patch.object(short_builder.ffmpeg_encode, "burn_and_mux",
                      side_effect=lambda base, srt, narr, music, out, **kw: out), \
         patch.object(short_builder.srt_writer, "write_srt", side_effect=lambda segs, p: p), \
         patch.object(short_builder, "is_done", return_value=False), \
         patch.object(short_builder, "write_checkpoint"), \
         patch.object(short_builder, "_resolve_music_path", return_value=None):
        # checkpoint state is global (output/checkpoints/), so is_done is patched out — a real
        # checkpoint for the same low video id would otherwise short-circuit the build.
        result = short_builder.build_short(voiced_short)

    assert seen["kenburns_sizes"] == [short_builder.SHORT_SIZE] * 3
    assert seen["card_sizes"] == [short_builder.SHORT_SIZE]
    assert result["duration_sec"] == 40
    with SessionLocal() as s:
        assert s.get(Video, voiced_short).state == VideoState.RENDERED.value


def test_build_short_burns_karaoke_ass_when_words_present(voiced_short, tmp_path):
    """With word timestamps available, the shorts path burns a self-styled ASS (sub_style
    None) instead of the SRT + force_style pair."""
    seen = {}

    def fake_burn(base, cap, narr, music, out, **kw):
        seen["cap"], seen["style"] = Path(cap), kw.get("sub_style", "MISSING")
        return out

    caps = [{"start": 0.0, "end": 1.0, "text": "x",
             "words": [{"start": 0.0, "end": 1.0, "text": "x"}]}]
    with patch.object(short_builder, "_portrait_still", side_effect=lambda s, o: (o.write_bytes(b"p"), o)[1]), \
         patch.object(short_builder.kenburns_ffmpeg, "render_segment",
                      side_effect=lambda i, d, o, **kw: (o.write_bytes(b"m"), o)[1]), \
         patch.object(short_builder, "_end_card", side_effect=lambda s, c, o, w: o), \
         patch.object(short_builder, "transcribe", return_value=caps), \
         patch.object(short_builder.ffmpeg_encode, "probe_duration", return_value=40.0), \
         patch.object(short_builder.ffmpeg_encode, "concat_copy", side_effect=lambda segs, out, **kw: out), \
         patch.object(short_builder.ffmpeg_encode, "burn_and_mux", side_effect=fake_burn), \
         patch.object(short_builder, "is_done", return_value=False), \
         patch.object(short_builder, "write_checkpoint"), \
         patch.object(short_builder, "_resolve_music_path", return_value=None):
        short_builder.build_short(voiced_short)

    assert seen["cap"].suffix == ".ass" and seen["cap"].exists()
    assert seen["style"] is None
    assert "\\k" in seen["cap"].read_text()


def test_beat_durations_snap_to_nearby_phrase_ends():
    caps = [{"start": 0, "end": 10.5, "text": "a"},
            {"start": 10.5, "end": 19.7, "text": "b"},
            {"start": 19.7, "end": 30.0, "text": "c"}]
    durs = short_builder._beat_durations(30.0, 3, caps)
    # even boundaries 10.0/20.0 pull to phrase ends 10.5/19.7
    assert durs == pytest.approx([10.5, 9.2, 10.3])
    assert sum(durs) == pytest.approx(30.0)


def test_beat_durations_keep_even_grid_when_no_phrase_end_is_near():
    caps = [{"start": 0, "end": 5.0, "text": "a"}, {"start": 5.0, "end": 30.0, "text": "b"}]
    durs = short_builder._beat_durations(30.0, 3, caps)
    assert durs == pytest.approx([10.0, 10.0, 10.0])


def test_beat_durations_with_no_captions_split_evenly_and_sum_exactly():
    durs = short_builder._beat_durations(41.7, 6, [])
    assert len(durs) == 6
    assert sum(durs) == pytest.approx(41.7, abs=1e-9)


def test_build_short_rejects_over_60s_narration(voiced_short, tmp_path):
    with patch.object(short_builder.ffmpeg_encode, "probe_duration", return_value=59.0):
        with pytest.raises(ValueError, match="60s"):
            short_builder.build_short(voiced_short)


def test_portrait_caption_style_keeps_phone_safe_side_margins():
    """Phones taller than 16:9 (19.5:9, 20:9) cover-fill the 9:16 frame and crop up to
    ~10% off each side, so caption lines must wrap well inside the frame. libass margins
    are script units on PlayResX=384: 40 units ≈ 112px per side at 1080w — the crop zone."""
    style = dict(kv.split("=", 1) for kv in short_builder._PORTRAIT_SUB_STYLE.split(","))
    assert int(style["MarginL"]) >= 40
    assert int(style["MarginR"]) >= 40
