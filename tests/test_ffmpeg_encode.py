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

from ai_operator.assembler import branding, endscreen_outro, ffmpeg_encode, srt_writer


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


def _jpg(path: Path, *, color="white", size="1920x1080") -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={size}", "-frames:v", "1", str(path)],
        check=True, capture_output=True,
    )


def _mean_luma(path: Path) -> float:
    """Average frame luminance (YAVG); distinguishes a bright image backdrop from the flat dark card."""
    out = subprocess.run(
        ["ffmpeg", "-i", str(path), "-vf",
         "signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    vals = [float(ln.split("=")[-1]) for ln in out.stderr.splitlines() if "YAVG" in ln]
    return sum(vals) / len(vals) if vals else 0.0


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
    audio = next(s for s in streams if s["codec_type"] == "audio")
    assert any(s["codec_type"] == "video" for s in streams)
    # forced stereo 44100 so the body matches the stereo intro/outro cards at the concat boundary
    assert int(audio["channels"]) == 2 and int(audio["sample_rate"]) == 44100
    assert abs(ffmpeg_encode.probe_duration(body) - 2.0) < 0.3    # body length == narration, no intro shift


def test_burn_and_mux_skips_subtitles_on_empty_srt(tmp_path):
    """A speechless narration -> empty SRT: must not crash; the base video passes straight through."""
    base = tmp_path / "base.mp4"
    _silent_clip(base, seconds=1.5)
    nar = tmp_path / "narration.mp3"
    _tone(nar, seconds=1.5)
    empty = srt_writer.write_srt([], tmp_path / "captions.srt")   # 0-byte file
    assert empty.stat().st_size == 0

    body = ffmpeg_encode.burn_and_mux(base, empty, nar, None, tmp_path / "body.mp4")
    streams = _probe(body)["streams"]
    assert any(s["codec_type"] == "video" for s in streams)
    assert any(s["codec_type"] == "audio" for s in streams)


def test_concat_copy_audio_reencode_produces_uniform_stereo(tmp_path):
    """Final-join path: video stream-copied, audio re-encoded to one stereo track."""
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _silent_clip(a, seconds=1.0)
    _silent_clip(b, seconds=1.0)
    # give the clips a (mono) audio track so re-encode has something to normalize to stereo
    for clip in (a, b):
        tmp = clip.with_suffix(".wav.mp4")
        subprocess.run(["ffmpeg", "-y", "-i", str(clip), "-f", "lavfi", "-i", "sine=frequency=200",
                        "-shortest", "-c:v", "copy", "-c:a", "aac", "-ac", "1", str(tmp)],
                       check=True, capture_output=True)
        tmp.replace(clip)
    out = ffmpeg_encode.concat_copy([a, b], tmp_path / "joined.mp4", audio_reencode=True)
    audio = next(s for s in _probe(out)["streams"] if s["codec_type"] == "audio")
    assert int(audio["channels"]) == 2


# --------------------------------------------------------------------------------------
# branding card spec (must match the concat boundary exactly)
# --------------------------------------------------------------------------------------


def _mean_volume_db(path: Path) -> float:
    """volumedetect mean_volume in dB; -91.0 stands in for digital silence (-inf)."""
    out = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    for line in out.stderr.splitlines():
        if "mean_volume" in line:
            val = line.split("mean_volume:")[1].strip().split(" ")[0]
            return -91.0 if val == "-inf" else float(val)
    return -91.0


@pytest.fixture()
def _synth_outro_path(monkeypatch, tmp_path):
    """Force the synthesized-card path even when the repo carries a hand-made
    assets/branding/outro.mp4 (which would otherwise be normalized and returned)."""
    monkeypatch.setattr(branding, "BRANDING_DIR", tmp_path / "no-branding")


def test_outro_card_matches_concat_spec_at_endscreen_length(tmp_path, _synth_outro_path):
    out = branding.make_outro(tmp_path / "outro.mp4")
    streams = _probe(out)["streams"]
    v = next(s for s in streams if s["codec_type"] == "video")
    a = next(s for s in streams if s["codec_type"] == "audio")
    assert (v["width"], v["height"]) == (1920, 1080)
    assert v["avg_frame_rate"] == "24/1"
    assert v["pix_fmt"] == "yuv420p"
    assert a["codec_name"] == "aac" and int(a["channels"]) == 2
    # end-screen elements need 5-20s of runway; the card must provide it
    assert abs(ffmpeg_encode.probe_duration(out) - endscreen_outro.OUTRO_SECONDS) < 0.3
    assert not list(tmp_path.glob("outro_teaser*.txt"))   # teaser textfiles cleaned up


def test_outro_card_fades_music_bed_back_in(tmp_path, _synth_outro_path):
    bed = tmp_path / "bed.mp3"
    _tone(bed, seconds=30.0)
    out = branding.make_outro(tmp_path / "outro.mp4", teaser="One more story", music=bed)
    a = next(s for s in _probe(out)["streams"] if s["codec_type"] == "audio")
    assert a["codec_name"] == "aac" and int(a["channels"]) == 2
    assert _mean_volume_db(out) > -50.0                   # bed is audible, not anullsrc


def test_outro_card_is_silent_without_music(tmp_path, _synth_outro_path):
    out = branding.make_outro(tmp_path / "outro.mp4", music=None)
    assert _mean_volume_db(out) < -80.0


def test_outro_card_stretches_to_cover_spoken_voice(tmp_path, _synth_outro_path):
    voice = tmp_path / "voice.mp3"
    _tone(voice, seconds=14.0)
    out = branding.make_outro(tmp_path / "outro.mp4", teaser="One more story", voice=voice)
    a = next(s for s in _probe(out)["streams"] if s["codec_type"] == "audio")
    assert a["codec_name"] == "aac" and int(a["channels"]) == 2
    # voice(14s) + tail(2s) = 16s, inside the 12..20s end-screen window
    assert abs(ffmpeg_encode.probe_duration(out) - 16.0) < 0.5
    assert _mean_volume_db(out) > -50.0                  # the voice is actually on the card


def test_outro_card_ducks_music_under_voice(tmp_path, _synth_outro_path):
    bed = tmp_path / "bed.mp3"; _tone(bed, seconds=30.0)
    voice = tmp_path / "voice.mp3"; _tone(voice, seconds=13.0)
    out = branding.make_outro(tmp_path / "outro.mp4", teaser="One more story", music=bed, voice=voice)
    a = next(s for s in _probe(out)["streams"] if s["codec_type"] == "audio")
    assert a["codec_name"] == "aac" and int(a["channels"]) == 2
    assert ffmpeg_encode.probe_duration(out) > endscreen_outro.OUTRO_SECONDS  # stretched past 12s
    assert _mean_volume_db(out) > -50.0                  # voice + ducked bed are audible


def test_outro_card_voice_only_is_audible(tmp_path, _synth_outro_path):
    voice = tmp_path / "voice.mp3"; _tone(voice, seconds=13.0)
    out = branding.make_outro(tmp_path / "outro.mp4", voice=voice, music=None)
    assert _mean_volume_db(out) > -50.0                  # voice carries the card with no bed
    assert ffmpeg_encode.probe_duration(out) > endscreen_outro.OUTRO_SECONDS


def test_outro_card_caps_spoken_length_at_max(tmp_path, _synth_outro_path):
    voice = tmp_path / "voice.mp3"; _tone(voice, seconds=25.0)
    out = branding.make_outro(tmp_path / "outro.mp4", voice=voice)
    # a long voice can't push the card past YouTube's 20s end-screen element ceiling
    assert abs(ffmpeg_encode.probe_duration(out) - endscreen_outro.OUTRO_MAX_SECONDS) < 0.5


def test_outro_card_degrades_on_unreadable_audio(tmp_path, _synth_outro_path):
    # A 0-byte/corrupt voice or music file must NOT abort the render (best-effort contract):
    # the bad input is dropped and the card falls back rather than crashing ffmpeg.
    bad_voice = tmp_path / "voice.mp3"; bad_voice.write_bytes(b"")          # 0-byte voice
    out = branding.make_outro(tmp_path / "outro.mp4", teaser="One more story", voice=bad_voice)
    # voice dropped -> fixed 12s card, silent (no music either), no exception raised
    assert abs(ffmpeg_encode.probe_duration(out) - endscreen_outro.OUTRO_SECONDS) < 0.3
    assert _mean_volume_db(out) < -80.0

    bad_music = tmp_path / "bed.mp3"; bad_music.write_bytes(b"not audio")   # corrupt bed
    out2 = branding.make_outro(tmp_path / "outro2.mp4", music=bad_music)
    assert _mean_volume_db(out2) < -80.0                                    # music dropped -> silent


def test_outro_card_uses_documentary_backdrop(tmp_path, _synth_outro_path):
    img = tmp_path / "beat_09.jpg"; _jpg(img, color="white")
    out = branding.make_outro(tmp_path / "outro.mp4", teaser="One more story", backdrop_image=img)
    streams = _probe(out)["streams"]
    v = next(s for s in streams if s["codec_type"] == "video")
    a = next(s for s in streams if s["codec_type"] == "audio")
    assert (v["width"], v["height"]) == (1920, 1080) and v["pix_fmt"] == "yuv420p"
    assert v["avg_frame_rate"] == "24/1" and a["codec_name"] == "aac" and int(a["channels"]) == 2
    assert abs(ffmpeg_encode.probe_duration(out) - endscreen_outro.OUTRO_SECONDS) < 0.3  # no voice -> 12s
    assert _mean_luma(out) > 60.0                          # darkened image backdrop, NOT the flat near-black card
    assert not list(tmp_path.glob("*_backdrop.mp4"))       # temp backdrop cleaned up


def test_outro_card_backdrop_falls_back_when_missing_or_corrupt(tmp_path, _synth_outro_path):
    # missing image -> flat dark card, no crash
    out = branding.make_outro(tmp_path / "o1.mp4", backdrop_image=tmp_path / "nope.jpg")
    assert abs(ffmpeg_encode.probe_duration(out) - endscreen_outro.OUTRO_SECONDS) < 0.3
    assert _mean_luma(out) < 30.0                          # flat dark fallback
    # corrupt image -> render_segment fails -> graceful fallback, temp cleaned, no crash
    bad = tmp_path / "beat_01.jpg"; bad.write_bytes(b"not a jpeg")
    out2 = branding.make_outro(tmp_path / "o2.mp4", backdrop_image=bad)
    assert _mean_luma(out2) < 30.0
    assert not list(tmp_path.glob("*_backdrop.mp4"))


def test_last_still_image_walks_back_past_broll(tmp_path):
    from ai_operator.assembler import video_builder
    img_dir = tmp_path / "img"; img_dir.mkdir()
    (img_dir / "beat_03.jpg").write_bytes(b"x")            # last still is beat 3
    shot = [{"beat_id": 1}, {"beat_id": 3}, {"beat_id": 7}]  # beat 7 (last) is b-roll, no image
    assert video_builder._last_still_image(shot, img_dir) == img_dir / "beat_03.jpg"
    assert video_builder._last_still_image([{"beat_id": 9}], img_dir) is None
