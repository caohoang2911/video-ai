"""Orchestrates the assemble step end-to-end: Ken Burns segments -> captions -> ducked
audio -> branding -> single H.264 export. Composited in one pass so we never re-read a
clip mid-pipeline (a real source of audio/video drift on longer renders).
"""

from __future__ import annotations

import json
from pathlib import Path

from moviepy import AudioFileClip, CompositeVideoClip, VideoFileClip, concatenate_videoclips
from sqlalchemy import select

from ..checkpoint import is_done, make_idempotency_key
from ..checkpoint import write as write_checkpoint
from ..config import OUTPUT_DIR
from ..db import InvalidTransition, SessionLocal, VideoState, assert_transition
from ..db.models import Asset, Video
from ..logging_setup import get_logger
from .audio_mixer import mix as mix_audio
from .beat_timing import compute_beat_durations
from .branding import font_path, load_intro, load_outro
from .caption_whisper import build_text_clips, transcribe
from .kenburns_ffmpeg import render_segments

log = get_logger("assembler.video_builder")

STEP = "assemble"
WIDTH, HEIGHT, FPS = 1920, 1080, 30


def assemble_video(video_id: int) -> dict:
    """Render `output/<video_id>/final.mp4`, update `videos.state = rendered`, return
    `{"video_path", "duration_sec"}`. Safe to call again after a crash: a finished run is
    detected via checkpoint + DB state and short-circuited without re-rendering."""
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None:
            raise ValueError(f"video {video_id} not found")
        state, title, duration_sec = video.state, video.title, video.duration_sec

    video_dir = OUTPUT_DIR / str(video_id)
    final_path = video_dir / "final.mp4"

    # A genuinely finished run: final.mp4 present AND (checkpoint says done OR the row already
    # advanced to rendered). Tolerates a lost checkpoint after a successful render.
    if final_path.exists() and (is_done(video_id, STEP) or state == VideoState.RENDERED.value):
        log.info("video %s: assemble already done -> reusing %s", video_id, final_path)
        return {"video_path": str(final_path), "duration_sec": duration_sec or 0}
    # Allow an idempotent re-render from VOICED (first render) or RENDERED (e.g. final.mp4 was
    # deleted to force a re-render, or a crash landed between the state commit and checkpoint).
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

    script = json.loads(script_path.read_text(encoding="utf-8"))
    shot_list = script["shot_list"]

    narration = AudioFileClip(str(narration_path))
    durations = compute_beat_durations(shot_list, narration.duration)
    segments = render_segments(shot_list, durations, video_dir / "img", video_dir / "segments")
    seg_clips = [VideoFileClip(str(p)) for p in segments]
    base_video = concatenate_videoclips(seg_clips, method="chain")

    captions = transcribe(narration_path)
    text_clips = build_text_clips(captions, font_path())
    composite = CompositeVideoClip([base_video, *text_clips], size=(WIDTH, HEIGHT))
    composite = composite.with_audio(mix_audio(narration, _resolve_music_path(video_id, video_dir)))

    full = concatenate_videoclips(
        [load_intro(title or ""), composite, load_outro()], method="compose"
    )

    final_path.parent.mkdir(parents=True, exist_ok=True)
    full.write_videofile(
        str(final_path), fps=FPS, codec="libx264", preset="fast",
        ffmpeg_params=["-crf", "23", "-pix_fmt", "yuv420p"], threads=8, audio_codec="aac",
    )
    rendered_duration = int(round(full.duration))

    idem_key = make_idempotency_key(str(video_id), STEP, str(narration_path))
    _persist_rendered_state(video_id, str(final_path), rendered_duration)
    write_checkpoint(video_id, STEP, {"video_path": str(final_path), "idempotency_key": idem_key})
    return {"video_path": str(final_path), "duration_sec": rendered_duration}


def _resolve_music_path(video_id: int, video_dir: Path) -> str | None:
    """Background music sourcing is still an open decision upstream (royalty-free library
    vs licensed service) -- most videos will have none in P0. Prefer a DB-tracked asset
    (auditable license/source), else a manually-dropped conventional file, else silence."""
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
        # Idempotent: a re-render (deleted final.mp4, or crash before checkpoint) re-enters
        # with the row already RENDERED, which has no self-loop — only advance when needed.
        if video.state != VideoState.RENDERED.value:
            assert_transition(video.state, VideoState.RENDERED)
            video.state = VideoState.RENDERED.value
        video.video_path = video_path
        video.duration_sec = duration_sec
        session.commit()
