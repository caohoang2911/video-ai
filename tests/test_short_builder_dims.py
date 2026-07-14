"""short_builder drives the shared helpers at 1080x1920 — asserted at the module
boundaries (no real ffmpeg render)."""

import json
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

    def fake_segment(image_path, duration, out_path, zoom_in, size=(1920, 1080)):
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
