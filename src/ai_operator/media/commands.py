"""CLI commands for the media engine: `gen-audio` (TTS), `gen-visuals` (stock/SDXL/fal),
and `revoice` (force a full teardown+rebuild back onto the ElevenLabs brand voice).

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
from ..config import OUTPUT_DIR
from ..db import InvalidTransition, VideoState, assert_transition, can_transition
from ..db.engine import SessionLocal
from ..db.models import Video
from ..logging_setup import get_logger, setup_logging
from . import tts_narrator, visual_fetcher

log = get_logger("media.commands")

_TTS_STEP = tts_narrator.STEP
_TTS_CHUNKS_STEP = tts_narrator.CHUNKS_STEP
_VISUAL_STEP = "visual_fetch"
# Must match assembler.video_builder.STEP -- referenced by string only (cross-phase handoff
# is via files/DB/checkpoint keys, never direct imports between phase packages).
_ASSEMBLE_STEP = "assemble"


def register(app: typer.Typer) -> None:
    app.command("gen-audio")(gen_audio)
    app.command("gen-visuals")(gen_visuals)
    app.command("revoice")(revoice)


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


def gen_visuals(
    video_id: int = typer.Option(..., "--video-id", help="videos.id to fetch visuals for"),
    motion: bool = typer.Option(
        False, "--motion/--stills-only",
        help="fetch motion b-roll as the primary visual (needs the hybrid video assembler); "
             "default is stills-only, which the current assembler can render",
    ),
) -> None:
    # Stills-only is the DEFAULT until the hybrid video assembler ships: a b-roll beat has no
    # per-beat still, and the current stills assembler requires one, so a default motion run
    # would produce un-assemblable output. `--motion` opts in for testing the sourcing path.
    setup_logging()
    with SessionLocal() as session:
        video = _load_video(session, video_id)
        script = _load_script(video)
        assets = visual_fetcher.acquire(video_id, script["shot_list"], stills_only=not motion)
        _maybe_mark_voiced(video)
        session.commit()
    typer.echo(f"{len(assets)} visual assets acquired")


def revoice(
    video_id: int = typer.Option(..., "--video-id", help="videos.id to force re-voice with the brand voice"),
) -> None:
    """Full teardown+rebuild, never a narration-only patch (assemble already baked the old
    audio into final.mp4): (1) force an ElevenLabs re-synth of narration.mp3; if ElevenLabs
    is still unavailable, alert and stop there -- leave the render/state untouched, nothing
    better to rebuild from yet. Only once ElevenLabs actually lands: (2) delete the stale
    final.mp4 + invalidate the assemble checkpoint; (3) drive state back to VOICED so a
    later `assemble` re-enters its render branch; (4) clear `needs_revoice` LAST.
    """
    setup_logging()
    with SessionLocal() as session:
        video = _load_video(session, video_id)
        script_path = video.script_path

    if not script_path or not Path(script_path).exists():
        typer.echo(f"video {video_id} has no script.json (nothing to re-voice)", err=True)
        raise typer.Exit(1)
    narration_text = json.loads(Path(script_path).read_text(encoding="utf-8"))["narration"]

    # (1) force a full ElevenLabs re-synth -- without dropping the cached narration + its
    # per-chunk progress, `synthesize` would just hand back the old (possibly edge-tts) audio.
    checkpoint.invalidate(video_id, _TTS_STEP)
    checkpoint.invalidate(video_id, _TTS_CHUNKS_STEP)
    try:
        audio_path = tts_narrator.synthesize(video_id, narration_text)
    except Exception as exc:
        typer.echo(f"video {video_id}: elevenlabs re-synth failed, needs_revoice unchanged: {exc}", err=True)
        raise typer.Exit(1) from exc
    provider = (checkpoint.artifacts_of(video_id, _TTS_STEP) or {}).get("provider")

    if provider != "elevenlabs":
        # Still unavailable: alert, but do NOT tear down the existing render or move state --
        # there's nothing better to rebuild from yet, and discarding it would lose a still-
        # reviewable draft for no gain. `needs_revoice` stays True (tts_narrator set it again).
        with SessionLocal() as session:
            video = _load_video(session, video_id)
            video.audio_path = str(audio_path)
            session.commit()
        typer.echo(
            f"video {video_id}: elevenlabs still unavailable (re-synth used {provider}) -- "
            f"needs_revoice remains True, render/state left unchanged", err=True,
        )
        raise typer.Exit(1)

    # (2) the stale final.mp4 has the OLD voice baked in -- both the file and its checkpoint
    # entry must go, or a subsequent assemble would just reuse the stale render.
    final_path = OUTPUT_DIR / str(video_id) / "final.mp4"
    if final_path.exists():
        final_path.unlink()
    checkpoint.invalidate(video_id, _ASSEMBLE_STEP)

    with SessionLocal() as session:
        video = _load_video(session, video_id)
        video.audio_path = str(audio_path)
        _drive_to_voiced(video)  # (3)
        video.needs_revoice = False  # (4) clear LAST, only now that ElevenLabs actually landed
        session.commit()

    typer.echo(f"video {video_id}: re-voiced via elevenlabs -> {audio_path} (run assemble to rebuild final.mp4)")


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


def _drive_to_voiced(video: Video) -> None:
    """Reset `video.state` back to VOICED so a later `assemble` re-enters its render branch.

    There's no direct edge back to VOICED from every downstream state (by design -- it would
    let review/approval be bypassed); FAILED and RERUN_QUEUED are the two states that DO have
    a VOICED edge, so bridge through whichever is legally reachable from the current state
    rather than widening the shared transition table just for this command.
    """
    if video.state == VideoState.VOICED.value:
        return  # idempotent: nothing to reset
    if can_transition(video.state, VideoState.FAILED):
        bridge = VideoState.FAILED
    elif can_transition(video.state, VideoState.RERUN_QUEUED):
        bridge = VideoState.RERUN_QUEUED
    else:
        raise InvalidTransition(
            f"video {video.id} state={video.state} has no path back to voiced for revoice"
        )
    assert_transition(video.state, bridge)
    video.state = bridge.value
    assert_transition(video.state, VideoState.VOICED)
    video.state = VideoState.VOICED.value
