"""Key-free unit tests for the ffmpeg-native render path (5a): SRT writing, encoder-arg
selection, stream-copy concat, body-first burn+mux, and branding-card spec. Real ffmpeg/ffprobe
(already pipeline deps); `AI_OPERATOR_ENCODER=libx264` forces the portable software path so
these pass off Apple Silicon too. No MoviePy, no network, no API key.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ai_operator.assembler import branding, ffmpeg_encode, srt_writer


@pytest.fixture(autouse=True)
def _force_libx264(monkeypatch):
    monkeypatch.setenv("AI_OPERATOR_ENCODER", "libx264")


def _probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def _silent_clip(path: Path, *, seconds=2.0, size="320x240") -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s={size}:r=24:d={seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-r", "24", str(path)],
        check=True, capture_output=True,
    )


def _tone(path: Path, *, seconds=2.0) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300", "-t", str(seconds), str(path)],
        check=True, capture_output=True,
    )


# --------------------------------------------------------------------------------------
# srt_writer
# --------------------------------------------------------------------------------------


def test_srt_timestamp_format_and_indexing(tmp_path):
    p = srt_writer.write_srt(
        [{"start": 0.0, "end": 2.5, "text": "one"}, {"start": 61.2, "end": 63.75, "text": "two"}],
        tmp_path / "c.srt",
    )
    body = p.read_text()
    assert "1\n00:00:00,000 --> 00:00:02,500\none" in body
    assert "2\n00:01:01,200 --> 00:01:03,750\ntwo" in body


def test_srt_skips_empty_and_nudges_nonincreasing_end(tmp_path):
    p = srt_writer.write_srt(
        [{"start": 0.0, "end": 1.0, "text": "  "}, {"start": 5.0, "end": 5.0, "text": "kept"}],
        tmp_path / "c.srt",
    )
    body = p.read_text()
    assert "kept" in body
    assert body.count("-->") == 1                       # empty-text cue dropped
    assert "00:00:05,000 --> 00:00:05,500" in body       # end==start nudged +0.5s


# --------------------------------------------------------------------------------------
# encoder selection
# --------------------------------------------------------------------------------------


def test_video_encode_args_toggles_on_env(monkeypatch):
    monkeypatch.setenv("AI_OPERATOR_ENCODER", "libx264")
    assert ffmpeg_encode.video_encode_args()[:2] == ["-c:v", "libx264"]
    monkeypatch.setenv("AI_OPERATOR_ENCODER", "")
    assert ffmpeg_encode.video_encode_args()[:2] == ["-c:v", "h264_videotoolbox"]


# --------------------------------------------------------------------------------------
# concat_copy + probe_duration
# --------------------------------------------------------------------------------------


def test_concat_copy_sums_durations_and_stays_24fps(tmp_path):
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _silent_clip(a, seconds=2.0)
    _silent_clip(b, seconds=1.0)
    out = ffmpeg_encode.concat_copy([a, b], tmp_path / "cat.mp4")

    assert abs(ffmpeg_encode.probe_duration(out) - 3.0) < 0.2
    v = next(s for s in _probe(out)["streams"] if s["codec_type"] == "video")
    assert v["avg_frame_rate"] == "24/1"
    assert not (tmp_path / "cat_concat.txt").exists()   # list file cleaned up


# --------------------------------------------------------------------------------------
# burn_and_mux (body-first: caption burn + narration mux, body length preserved)
# --------------------------------------------------------------------------------------


def test_burn_and_mux_muxes_narration_and_keeps_body_length(tmp_path):
    base = tmp_path / "base.mp4"
    _silent_clip(base, seconds=2.0)
    nar = tmp_path / "narration.mp3"
    _tone(nar, seconds=2.0)
    srt = srt_writer.write_srt([{"start": 0.0, "end": 1.5, "text": "hello"}], tmp_path / "captions.srt")

    body = ffmpeg_encode.burn_and_mux(base, srt, nar, None, tmp_path / "body.mp4")

    streams = _probe(body)["streams"]
    assert any(s["codec_type"] == "audio" for s in streams)      # narration muxed in
    assert any(s["codec_type"] == "video" for s in streams)
    assert abs(ffmpeg_encode.probe_duration(body) - 2.0) < 0.3    # body length == narration, no intro shift


# --------------------------------------------------------------------------------------
# branding card spec (must match the concat boundary exactly)
# --------------------------------------------------------------------------------------


def test_branding_card_matches_concat_spec(tmp_path):
    out = branding.make_outro(tmp_path / "outro.mp4")
    streams = _probe(out)["streams"]
    v = next(s for s in streams if s["codec_type"] == "video")
    a = next(s for s in streams if s["codec_type"] == "audio")
    assert (v["width"], v["height"]) == (1920, 1080)
    assert v["avg_frame_rate"] == "24/1"
    assert v["pix_fmt"] == "yuv420p"
    assert a["codec_name"] == "aac" and int(a["channels"]) == 2
