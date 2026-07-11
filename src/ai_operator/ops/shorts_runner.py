"""Create 2-3 child Shorts for a published main video and drive each to the review gate.

Flow per short: LLM short script -> child Video row (kind=short, parent_id) -> TTS ->
reuse parent visuals by keyword match -> vertical render -> review gate (or stop at
`rendered` when Telegram is unconfigured — same behavior as mains). One failing short
never aborts the batch; a rejected short is simply discarded (re-roll via force=True),
never reworked. Shorts NEVER auto-publish — the human gate is the same as for mains.
"""

from __future__ import annotations

import json
import shutil

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy import update as sa_update

from ..config import CHECKPOINT_DIR, OUTPUT_DIR, settings
from ..content.short_script_generator import generate_short_scripts
from ..db import SessionLocal, VideoState, assert_transition
from ..db.state_machine import can_transition
from ..db.models import Asset, Decision, Video
from ..db.models_ops import CostLedger, Job
from ..logging_setup import get_logger
from ..media import tts_narrator
from ..review.review_notifier import notify
from ..assembler.short_builder import build_short

log = get_logger("ops.shorts_runner")

SHORTS_PER_VIDEO = 3
_DISCARDABLE = frozenset(
    s.value for s in VideoState if s not in (VideoState.PUBLISHED, VideoState.ANALYZED)
)


def generate_shorts(parent_video_id: int, *, force: bool = False) -> list[int]:
    """Produce child shorts for a main video; returns the created child video ids.
    Idempotent: a parent that already has shorts is skipped unless force=True, which
    first discards the parent's non-published shorts and re-rolls a fresh batch."""
    with SessionLocal() as s:
        parent = s.get(Video, parent_video_id)
        if parent is None:
            raise ValueError(f"video {parent_video_id} not found")
        if parent.kind != "main":
            log.info("video %s is kind=%s -> shorts never spawn shorts", parent_video_id, parent.kind)
            return []
        existing = s.scalars(select(Video).where(Video.parent_id == parent_video_id)).all()

    if existing and not force:
        log.info("parent %s already has %s shorts -> skipping (use force to re-roll)",
                 parent_video_id, len(existing))
        return []
    if force and existing:
        _discard_unpublished(existing)

    parent_script = json.loads(
        (OUTPUT_DIR / str(parent_video_id) / "script.json").read_text(encoding="utf-8")
    )
    shorts = generate_short_scripts(parent_script, SHORTS_PER_VIDEO, video_id=parent_video_id)

    # Offset keeps idempotency keys unique across re-rolls that kept published shorts.
    offset = _next_index(parent_video_id)
    child_ids: list[int] = []
    batch_used: set[int] = set()  # parent images taken so far — keeps siblings visually distinct
    for i, short in enumerate(shorts):
        try:
            child_ids.append(
                _produce_one(parent_video_id, parent_script, offset + i, short, batch_used)
            )
        except Exception as exc:  # noqa: BLE001 - one bad short must not abort the others
            log.error("short %s/%s for parent %s failed: %s", i + 1, len(shorts), parent_video_id, exc)
    return child_ids


def _produce_one(
    parent_id: int, parent_script: dict, index: int, short, batch_used: set[int] | None = None
) -> int:
    child_id = _create_child(parent_id, index, short)
    child_dir = OUTPUT_DIR / str(child_id)
    child_dir.mkdir(parents=True, exist_ok=True)
    script_path = child_dir / "script.json"
    script_path.write_text(
        json.dumps(short.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with SessionLocal() as s:
        # publish reads script.json via script_path — without it the upload body falls back
        # to a bare-metadata dict and the curiosity question/hashtags silently vanish
        s.get(Video, child_id).script_path = str(script_path)
        s.commit()
    _advance(child_id, VideoState.SCRIPTED)

    try:
        audio_path = tts_narrator.synthesize(child_id, short.narration)
        with SessionLocal() as s:
            v = s.get(Video, child_id)
            v.audio_path = str(audio_path)
            s.commit()
        _advance(child_id, VideoState.VOICED)

        _reuse_parent_images(parent_id, parent_script, child_id, short, batch_used)
        build_short(child_id)  # -> rendered

        if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
            notify(child_id)  # -> pending_review (human gate, same as mains)
        else:
            log.info("short %s rendered; Telegram unconfigured -> stopping before review gate", child_id)
    except Exception:
        _mark_failed(child_id)  # visible, never masquerades as ready
        raise
    return child_id


def _create_child(parent_id: int, index: int, short) -> int:
    with SessionLocal() as s:
        child = Video(
            kind="short",
            parent_id=parent_id,
            state=VideoState.DRAFT.value,
            idempotency_key=f"short:{parent_id}:{index}",
            title=short.title,
        )
        s.add(child)
        s.commit()
        return child.id


def _advance(video_id: int, target: VideoState) -> None:
    with SessionLocal() as s:
        v = s.get(Video, video_id)
        if v is not None and v.state != target.value:
            assert_transition(v.state, target)
            v.state = target.value
            s.commit()


def _mark_failed(video_id: int) -> None:
    """Best-effort FAILED mark for the error path: some states (e.g. pending_review after a
    partial notify) have no FAILED edge — never let the bookkeeping mask the original error."""
    with SessionLocal() as s:
        v = s.get(Video, video_id)
        if v is not None and can_transition(v.state, VideoState.FAILED):
            v.state = VideoState.FAILED.value
            s.commit()


def _next_index(parent_id: int) -> int:
    """Smallest index whose idempotency key is free (counts every child ever created)."""
    with SessionLocal() as s:
        keys = s.scalars(
            select(Video.idempotency_key).where(Video.parent_id == parent_id)
        ).all()
    taken = {int(k.rsplit(":", 1)[1]) for k in keys if k and k.startswith("short:")}
    return max(taken) + 1 if taken else 0


def _discard_unpublished(children: list[Video]) -> None:
    """force=True re-roll: drop child rows that never published, then their files.

    Per child, one transaction, in this order: re-check state on a FRESH row (a snapshot
    from before the loop could race a concurrent scheduler publish), detach dependents the
    FK pragma would otherwise trip on (cost rows keep their spend history, decision rows of
    a discarded draft go), delete the row, commit — and only THEN remove the output dir and
    checkpoint. DB-first ordering means a failed delete never destroys artifacts a
    surviving row still references."""
    for child in children:
        with SessionLocal() as s:
            row = s.get(Video, child.id)
            if row is None or row.state not in _DISCARDABLE:
                continue
            s.execute(
                sa_update(CostLedger).where(CostLedger.video_id == row.id).values(video_id=None)
            )
            s.execute(sa_update(Job).where(Job.video_id == row.id).values(video_id=None))
            s.execute(sa_delete(Decision).where(Decision.video_id == row.id))
            s.execute(sa_delete(Asset).where(Asset.video_id == row.id))
            state = row.state
            s.delete(row)
            s.commit()
        shutil.rmtree(OUTPUT_DIR / str(child.id), ignore_errors=True)
        (CHECKPOINT_DIR / f"{child.id}.checkpoint.json").unlink(missing_ok=True)
        log.info("discarded unpublished short %s (state=%s)", child.id, state)


def _reuse_parent_images(
    parent_id: int, parent_script: dict, child_id: int, short,
    batch_used: set[int] | None = None,
) -> None:
    """Map each short beat onto the best keyword-matching parent beat image; copy it into
    the child's img/ dir under the beat_XX.jpg name build_short expects.

    `batch_used` carries beat_ids already taken by SIBLING shorts in the same batch —
    without it the popular images repeat across the 2-3 shorts and the batch looks like
    duplicates in the feed. Preference order: unused anywhere > unused in this short >
    keyword overlap."""
    parent_img = OUTPUT_DIR / str(parent_id) / "img"
    child_img = OUTPUT_DIR / str(child_id) / "img"
    child_img.mkdir(parents=True, exist_ok=True)

    parent_beats = parent_script.get("shot_list", [])
    batch_used = batch_used if batch_used is not None else set()
    used: set[int] = set()
    for i, beat in enumerate(short.beats):
        want = {w.lower() for kw in beat.keywords for w in kw.split()}
        scored = sorted(
            (
                (len(want & {w.lower() for kw in pb.get("keywords", []) for w in kw.split()}), pb["beat_id"])
                for pb in parent_beats
                if (parent_img / f"beat_{pb['beat_id']:02d}.jpg").exists()
            ),
            key=lambda t: (t[1] in used, t[1] in batch_used, -t[0]),
        )
        if not scored:
            raise FileNotFoundError(f"parent {parent_id} has no beat images to reuse")
        beat_id = scored[0][1]
        used.add(beat_id)
        batch_used.add(beat_id)
        shutil.copyfile(parent_img / f"beat_{beat_id:02d}.jpg", child_img / f"beat_{i + 1:02d}.jpg")
