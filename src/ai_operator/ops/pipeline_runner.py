"""Chain the per-step pipeline for one video, resuming via each step's own checkpoint.

Each underlying step (`synthesize`, `acquire`, `assemble_video`, ...) already short-circuits
when its checkpoint says done, so `run_video` is safe to call again after a crash: completed
steps are skipped and it picks up where it stopped. The run halts at the human review gate
(`pending_review`); with no Telegram configured it stops one step earlier, at `rendered`.
"""

from __future__ import annotations

from sqlalchemy import select

from ..assembler.thumbnail_generator import generate as generate_thumbnails
from ..assembler.video_builder import assemble_video
from ..config import settings
from ..content import script_generator, topic_backlog
from ..db.engine import SessionLocal
from ..db.models import Topic, Video
from ..db.state_machine import VideoState, can_transition
from ..logging_setup import get_logger
from ..media import commands as media_commands
from ..review.review_notifier import notify

log = get_logger("ops.pipeline_runner")


def run_new(topic_id: int | None = None, *, motion: bool = False, gen_all: bool = False) -> int | None:
    """Pick a topic (given, else oldest backlog), generate its script, then run the pipeline.
    Returns the video id, or None if no topic was available."""
    with SessionLocal() as s:
        topic = s.get(Topic, topic_id) if topic_id is not None else topic_backlog.pick_next()
    if topic is None:
        log.warning("run_new: no topic available to produce")
        return None

    try:
        script_generator.generate(topic)  # creates the Video row + script.json (state=scripted)
    except Exception as exc:  # noqa: BLE001
        # A produce loop must never re-pick a topic that keeps failing (research/payoff reject,
        # or a transient outage). Mark it used so `pick_next` advances instead of jamming the
        # whole backlog on the same oldest topic forever and re-spending research budget.
        log.warning("run_new: topic %s failed to generate (%s) -> marking used to unjam the queue", topic.id, exc)
        topic_backlog.mark_used(topic.id)
        return None
    with SessionLocal() as s:
        video = s.scalar(select(Video).where(Video.topic_id == topic.id).order_by(Video.id.desc()))
    if video is None:
        log.error("run_new: script generated but no video row found for topic %s", topic.id)
        return None
    return run_video(video.id, motion=motion, gen_all=gen_all)


def run_video(video_id: int, *, motion: bool = False, gen_all: bool = False) -> int:
    """Advance one video through audio -> visuals -> assemble -> thumbnails -> review.
    Idempotent per step; stops at the review gate (or at `rendered` without Telegram)."""
    media_commands.gen_audio(video_id=video_id)
    media_commands.gen_visuals(video_id=video_id, motion=motion, gen_all=gen_all)
    assemble_video(video_id)
    generate_thumbnails(video_id)

    if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID):
        log.info("video %s rendered; Telegram unconfigured -> stopping before the review gate", video_id)
        return video_id

    # Only notify from a state that can still enter review -- re-running the pipeline on a video
    # already at/past the gate must be a no-op, not an InvalidTransition crash or a duplicate
    # preview re-sent to the review chat (mirrors the _maybe_mark_voiced guard).
    with SessionLocal() as s:
        state = (s.get(Video, video_id)).state
    if can_transition(state, VideoState.PENDING_REVIEW):
        notify(video_id)  # -> pending_review (human gate)
        log.info("video %s sent to review gate", video_id)
    else:
        log.info("video %s already at/past the review gate (state=%s) -> not re-notifying", video_id, state)
    return video_id
