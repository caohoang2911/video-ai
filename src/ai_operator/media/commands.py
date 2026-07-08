"""CLI commands for the media engine: `gen-audio` (TTS) and `gen-visuals` (stock/SDXL/fal).

Each command loads script.json (written by the content phase), runs its media step, and
advances videos.state -> voiced only once BOTH audio and visuals are done -- one combined
state (not two half-states) keeps the state machine simple (KISS) while letting the two
commands run in either order, or be retried independently, without corrupting it.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .. import checkpoint
from ..db.engine import SessionLocal
from ..db.models import Video
from ..db.state_machine import VideoState, assert_transition
from ..logging_setup import get_logger, setup_logging
from . import tts_narrator, visual_fetcher

log = get_logger("media.commands")

_TTS_STEP = "tts_narration"
_VISUAL_STEP = "visual_fetch"


def register(app: typer.Typer) -> None:
    app.command("gen-audio")(gen_audio)
    app.command("gen-visuals")(gen_visuals)


def gen_audio(video_id: int = typer.Option(..., "--video-id", help="videos.id to narrate")) -> None:
    setup_logging()
    with SessionLocal() as session:
        video = _load_video(session, video_id)
        script = _load_script(video)
        path = tts_narrator.synthesize(video_id, script["narration"])
        video.audio_path = str(path)
        _maybe_mark_voiced(video)
        session.commit()
    typer.echo(f"narration -> {path}")


def gen_visuals(video_id: int = typer.Option(..., "--video-id", help="videos.id to fetch visuals for")) -> None:
    setup_logging()
    with SessionLocal() as session:
        video = _load_video(session, video_id)
        script = _load_script(video)
        assets = visual_fetcher.acquire(video_id, script["shot_list"])
        _maybe_mark_voiced(video)
        session.commit()
    typer.echo(f"{len(assets)} visual assets acquired")


def _load_video(session, video_id: int) -> Video:
    video = session.get(Video, video_id)
    if video is None:
        typer.echo(f"video {video_id} not found", err=True)
        raise typer.Exit(1)
    return video


def _load_script(video: Video) -> dict:
    if not video.script_path or not Path(video.script_path).exists():
        typer.echo(f"video {video.id} has no script.json (run the content phase first)", err=True)
        raise typer.Exit(1)
    return json.loads(Path(video.script_path).read_text(encoding="utf-8"))


def _maybe_mark_voiced(video: Video) -> None:
    audio_ready = checkpoint.is_done(video.id, _TTS_STEP)
    visuals_ready = checkpoint.is_done(video.id, _VISUAL_STEP)
    if audio_ready and visuals_ready and video.state != VideoState.VOICED.value:
        assert_transition(video.state, VideoState.VOICED)
        video.state = VideoState.VOICED.value
        log.info("video %s -> voiced", video.id)
