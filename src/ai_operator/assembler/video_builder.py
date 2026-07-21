"""Orchestrates the assemble step end-to-end, ffmpeg-native (no MoviePy on the render path):
Ken Burns segments -> concat body -> burn captions + mux ducked audio (body-first) -> join
outro (and a user-supplied intro bumper, when one exists) -> single hardware-encoded final.mp4.

Body-first ordering keeps caption/narration t=0 pinned to the first body beat; the cards are
stream-copy-concatenated around the finished body so their length never shifts the timeline.
Default opening is a COLD OPEN: narration + beat 1 at t=0 with the title fading over the top
band — a bumper only precedes it when the operator drops assets/branding/intro.mp4 in place.
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
from . import branding, chapter_builder, ffmpeg_encode, music_picker, segment_builder, srt_writer
from .beat_timing import compute_beat_durations
from .caption_whisper import transcribe
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
        # `skipped` lets the caller tell "rendered" from "nothing happened". The job worker
        # used to follow every assemble with a thumbnail pass, so pressing the button on an
        # already-rendered video re-rendered nothing, spent ~$0.09 of fal, and overwrote
        # thumb_a/b/c with no backup -- while the CLI `thumbs` command backs them up by
        # default. A no-op that costs money and destroys work is not a no-op.
        return {"video_path": str(final_path), "duration_sec": duration_sec or 0, "skipped": True}
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

    script_data = json.loads(script_path.read_text(encoding="utf-8"))
    shot_list = script_data["shot_list"]
    narration_dur = ffmpeg_encode.probe_duration(narration_path)
    durations = compute_beat_durations(shot_list, narration_dur)
    # Cold open by default: no bumper -> the body IS t=0, so chapters carry no offset.
    user_intro = branding.user_intro()
    _persist_chapters(
        script_path, shot_list, durations,
        intro_seconds=branding.CARD_SECONDS if user_intro else 0.0,
    )

    # Music resolves before the cards so the outro can fade the same bed back in after the
    # body's fade-out. pick_for_video rewrites script.json (music_credit), so it runs after
    # _persist_chapters; both re-read the file, neither clobbers the other's fields.
    music_path = _resolve_music_path(video_id, video_dir)

    # Cards next: they are cheap but can fail on a missing drawtext font -- fail fast here,
    # before the expensive segment render + whisper + hardware encode. Only a hand-made
    # assets/branding/intro.mp4 earns a bumper slot; otherwise the video cold-opens on
    # beat 1 with narration at t=0 and the title fading over the opening seconds instead
    # of a dead silent card.
    intro = branding.make_intro(title or "", video_dir / "intro.mp4") if user_intro else None
    title_fx = None if user_intro else branding.cold_open_title_fx(title or "", video_dir)
    # The spoken outro (if any) was synthesized in the voice step; assemble only consumes it,
    # keeping the render path free of TTS/billing. Absent -> the card stays music/silence.
    outro_voice = video_dir / "outro_voice.mp3"
    outro = branding.make_outro(
        video_dir / "outro.mp4",
        teaser=script_data.get("outro_teaser") or None,
        music=music_path,
        voice=str(outro_voice) if outro_voice.exists() else None,
        backdrop_image=_last_still_image(shot_list, video_dir / "img"),
    )

    segments_dir = video_dir / "segments"
    segments = segment_builder.build_segments(
        shot_list, durations, video_id, video_dir / "img", segments_dir
    )

    srt_path = srt_writer.write_srt(transcribe(narration_path), video_dir / "captions.srt")

    base = ffmpeg_encode.concat_copy(segments, video_dir / "base.mp4")
    body = ffmpeg_encode.burn_and_mux(
        base, srt_path, narration_path, music_path, video_dir / "body.mp4",
        # same ambient glow/flicker the Shorts use — stills-based footage reads less static
        pre_fx=ffmpeg_encode.ambient_glow_fx(narration_dur, (WIDTH, HEIGHT)),
        post_fx=title_fx,
    )
    parts = [intro, body, outro] if intro else [body, outro]
    ffmpeg_encode.concat_copy(parts, final_path, audio_reencode=True)

    rendered_duration = int(round(ffmpeg_encode.probe_duration(final_path)))
    _cleanup_intermediates(segments_dir, [base, body, outro, *([intro] if intro else [])])

    idem_key = make_idempotency_key(str(video_id), STEP, str(narration_path))
    _persist_rendered_state(video_id, str(final_path), rendered_duration)
    write_checkpoint(video_id, STEP, {"video_path": str(final_path), "idempotency_key": idem_key})
    return {"video_path": str(final_path), "duration_sec": rendered_duration}


def _persist_chapters(
    script_path: Path, shot_list: list[dict], durations: list[float], intro_seconds: float
) -> None:
    """Write the computed YouTube chapter lines back into script.json — assemble is the only
    step that knows real beat durations, and the publisher (or a manual-upload export) reads
    the description metadata from script.json. Never fails the render over chapter bookkeeping."""
    try:
        chapters = chapter_builder.build_chapters(shot_list, durations, intro_seconds=intro_seconds)
        data = json.loads(script_path.read_text(encoding="utf-8"))
        data["chapters"] = chapters
        script_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - chapters are an enhancement, not a render dependency
        log.warning("chapter persist failed (%s) — continuing without chapters", exc)


def _last_still_image(shot_list: list[dict], img_dir: Path) -> Path | None:
    """The closing beat's still, walking back past any b-roll beats that have no per-beat image
    (`beat_NN.jpg` naming matches segment_builder). Used as the outro card's documentary
    backdrop so the card reads like the film's final frame. None when no still exists."""
    for beat in reversed(shot_list):
        img = img_dir / f"beat_{beat['beat_id']:02d}.jpg"
        if img.exists():
            return img
    return None


def _cleanup_intermediates(segments_dir: Path, files: list[Path]) -> None:
    """Delete render-time working files once final.mp4 exists -- keep only final.mp4, captions.srt,
    and the source artifacts (img/, narration.mp3, script.json)."""
    shutil.rmtree(segments_dir, ignore_errors=True)
    for f in files:
        Path(f).unlink(missing_ok=True)


def _resolve_music_path(video_id: int, video_dir: Path) -> str | None:
    """Prefer a DB-tracked music asset (auditable license), else a manually-dropped music.mp3,
    else auto-pick a bed from the local royalty-free library (mood-matched, credit persisted),
    else silence."""
    with SessionLocal() as session:
        asset = session.execute(
            select(Asset).where(Asset.video_id == video_id, Asset.kind == "music")
        ).scalars().first()
        if asset and Path(asset.url_or_path).exists():
            return asset.url_or_path
    fallback = video_dir / "music.mp3"
    if fallback.exists():
        return str(fallback)
    try:
        return music_picker.pick_for_video(video_id, video_dir)
    except Exception as exc:  # noqa: BLE001 - a music bed is an enhancement, never a render blocker
        log.warning("music pick failed (%s) — rendering without music", exc)
        return None


def _persist_rendered_state(video_id: int, video_path: str, duration_sec: int) -> None:
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video.state != VideoState.RENDERED.value:
            assert_transition(video.state, VideoState.RENDERED)
            video.state = VideoState.RENDERED.value
        video.video_path = video_path
        video.duration_sec = duration_sec
        session.commit()
