"""Orchestrates the assemble step end-to-end, ffmpeg-native (no MoviePy on the render path):
Ken Burns segments -> concat body -> burn captions + mux ducked audio (body-first) -> join
pre-built intro/outro -> single hardware-encoded final.mp4.

Body-first ordering keeps caption/narration t=0 pinned to the first body beat; intro/outro are
stream-copy-concatenated around the finished body so their length never shifts the timeline.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..checkpoint import is_done, make_idempotency_key
from ..checkpoint import write as write_checkpoint
from ..config import OUTPUT_DIR
from ..db import InvalidTransition, SessionLocal, VideoState, assert_transition
from ..db.models import Asset, Video
from ..logging_setup import get_logger
from . import branding, ffmpeg_encode, srt_writer
from .beat_timing import compute_beat_durations
from .caption_whisper import transcribe
from .kenburns_ffmpeg import render_segments
from sqlalchemy import select

log = get_logger("assembler.video_builder")

STEP = "assemble"
WIDTH, HEIGHT, FPS = 1920, 1080, 24


def assemble_video(video_id: int) -> dict:
    """Render `output/<video_id>/final.mp4`, set `videos.state = rendered`, return
    `{"video_path", "duration_sec"}`. Idempotent: a finished run (final.mp4 + checkpoint/state)
    short-circuits without re-rendering."""
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None:
            raise ValueError(f"video {video_id} not found")
        state, title, duration_sec = video.state, video.title, video.duration_sec

    video_dir = OUTPUT_DIR / str(video_id)
    final_path = video_dir / "final.mp4"

    if final_path.exists() and (is_done(video_id, STEP) or state == VideoState.RENDERED.value):
        log.info("video %s: assemble already done -> reusing %s", video_id, final_path)
        return {"video_path": str(final_path), "duration_sec": duration_sec or 0}
    if state not in (VideoState.VOICED.value, VideoState.RENDERED.value):
        raise InvalidTransition(
            f"video {video_id} state={state}, expected {VideoState.VOICED.value} or {VideoState.RENDERED.value}"
        )

    script_path = video_dir / "script.json"
    narration_path = video_dir / "narration.mp3"
    if not script_path.exists():
        raise FileNotFoundError(f"missing {script_path}")
    if not narration_path.exists():
        raise FileNotFoundError(f"missing {narration_path}")

    shot_list = json.loads(script_path.read_text(encoding="utf-8"))["shot_list"]
    narration_dur = ffmpeg_encode.probe_duration(narration_path)
    durations = compute_beat_durations(shot_list, narration_dur)

    segments_dir = video_dir / "segments"
    segments = render_segments(shot_list, durations, video_dir / "img", segments_dir)

    srt_path = srt_writer.write_srt(transcribe(narration_path), video_dir / "captions.srt")

    base = ffmpeg_encode.concat_copy(segments, video_dir / "base.mp4")
    body = ffmpeg_encode.burn_and_mux(
        base, srt_path, narration_path, _resolve_music_path(video_id, video_dir), video_dir / "body.mp4"
    )
    intro = branding.make_intro(title or "", video_dir / "intro.mp4")
    outro = branding.make_outro(video_dir / "outro.mp4")
    ffmpeg_encode.concat_copy([intro, body, outro], final_path)

    rendered_duration = int(round(ffmpeg_encode.probe_duration(final_path)))
    _cleanup_intermediates(segments_dir, [base, body, intro, outro])

    idem_key = make_idempotency_key(str(video_id), STEP, str(narration_path))
    _persist_rendered_state(video_id, str(final_path), rendered_duration)
    write_checkpoint(video_id, STEP, {"video_path": str(final_path), "idempotency_key": idem_key})
    return {"video_path": str(final_path), "duration_sec": rendered_duration}


def _cleanup_intermediates(segments_dir: Path, files: list[Path]) -> None:
    """Delete render-time working files once final.mp4 exists -- keep only final.mp4, captions.srt,
    and the source artifacts (img/, narration.mp3, script.json)."""
    shutil.rmtree(segments_dir, ignore_errors=True)
    for f in files:
        Path(f).unlink(missing_ok=True)


def _resolve_music_path(video_id: int, video_dir: Path) -> str | None:
    """Prefer a DB-tracked music asset (auditable license), else a manually-dropped music.mp3,
    else silence -- most P0 videos have no music bed."""
    with SessionLocal() as session:
        asset = session.execute(
            select(Asset).where(Asset.video_id == video_id, Asset.kind == "music")
        ).scalars().first()
        if asset and Path(asset.url_or_path).exists():
            return asset.url_or_path
    fallback = video_dir / "music.mp3"
    return str(fallback) if fallback.exists() else None


def _persist_rendered_state(video_id: int, video_path: str, duration_sec: int) -> None:
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video.state != VideoState.RENDERED.value:
            assert_transition(video.state, VideoState.RENDERED)
            video.state = VideoState.RENDERED.value
        video.video_path = video_path
        video.duration_sec = duration_sec
        session.commit()
