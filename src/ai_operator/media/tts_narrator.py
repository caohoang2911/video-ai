"""Narration synth: chunk -> ElevenLabs single-provider synth (edge-tts draft fallback) ->
ffmpeg concat (crossfade for overlapped chunks) -> narration.mp3.

Per-chunk audio + its ElevenLabs request-id are checkpointed as EACH chunk completes (not
just once at the end, and not to a `TemporaryDirectory` that vanishes on failure) so a
crash/retry mid-narration resumes from the missing tail instead of re-billing/re-synthesizing
chunks that already succeeded. `needs_revoice` is only ever SET here (never cleared -- that's
`revoice`'s job, and only after its own re-render succeeds) whenever the whole narration had
to fall back to edge-tts.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .. import checkpoint
from ..config import OUTPUT_DIR
from ..db.engine import SessionLocal
from ..db.models import Video
from ..cost import elevenlabs_char_guard as char_guard
from ..cost.budget_guard import BudgetExceeded
from ..logging_setup import get_logger
from .tts_chunker import chunk_narration
from .tts_providers import (
    ProviderFailed,
    ProviderUnavailable,
    synthesize_elevenlabs,
    synthesize_video,
)

log = get_logger("tts_narrator")

STEP = "tts_narration"                # complete-narration checkpoint (narration_path + provider)
CHUNKS_STEP = "tts_narration_chunks"  # internal per-chunk resume progress; superseded by STEP on success
OUTRO_STEP = "tts_outro"              # short spoken end-screen outro voice (separate synth)
CROSSFADE_SEC = 0.35  # short crossfade hides the repeated-tail overlap seam between chunks


def narration_path(video_id: int) -> Path:
    return OUTPUT_DIR / str(video_id) / "narration.mp3"


def outro_voice_path(video_id: int) -> Path:
    return OUTPUT_DIR / str(video_id) / "outro_voice.mp3"


def _chunk_dir(video_id: int) -> Path:
    """Persistent (never a tempfile dir) so a crash mid-synthesis leaves resumable audio behind."""
    return OUTPUT_DIR / str(video_id) / "tts_chunks"


def synthesize(video_id: int, narration_text: str) -> Path:
    """Chunk -> ElevenLabs (or a whole-video edge-tts fallback) -> concat. Returns the
    narration.mp3 path (cached without re-synthesizing anything if already done)."""
    if checkpoint.is_done(video_id, STEP):
        cached = checkpoint.artifacts_of(video_id, STEP) or {}
        cached_path = cached.get("narration_path")
        if cached_path and Path(cached_path).exists():
            log.info("video %s: narration already synthesized, skipping", video_id)
            return Path(cached_path)

    if not narration_text or not narration_text.strip():
        raise ValueError(f"video {video_id}: narration text is empty")

    chunks = chunk_narration(narration_text)
    if not chunks:
        raise ValueError(f"video {video_id}: narration produced no TTS chunks")

    out_path = narration_path(video_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    chunk_dir = _chunk_dir(video_id)
    chunk_dir.mkdir(parents=True, exist_ok=True)

    chunk_records, prev_request_ids = _load_resumable_chunks(video_id, len(chunks))
    chunk_paths = [chunk_dir / f"chunk_{i:03d}.raw" for i in range(len(chunks))]
    on_chunk_done = _make_on_chunk_done(video_id, chunk_dir, chunk_records, len(chunks))

    synthesize_video(
        chunks,
        chunk_paths,
        video_id=video_id,
        done_indices=set(chunk_records),
        prev_request_ids=prev_request_ids,
        on_chunk_done=on_chunk_done,
    )

    # Authoritative provider comes from the persisted per-chunk records (not synthesize_video's
    # return value alone) -- this doubles as the runtime guard that a video is never a mix of
    # two providers, whether that mix would come from this run or from stitching onto a prior one.
    providers_used = {chunk_records[i]["provider"] for i in range(len(chunks))}
    if len(providers_used) != 1:
        raise RuntimeError(f"video {video_id}: mixed TTS providers across chunks: {providers_used}")
    provider = providers_used.pop()

    mp3_paths = [Path(chunk_records[i]["path"]) for i in range(len(chunks))]
    has_overlap = any(c.has_overlap_head for c in chunks)
    _concat(mp3_paths, out_path, crossfade=has_overlap)
    shutil.rmtree(chunk_dir, ignore_errors=True)  # narration.mp3 alone is the durable artifact now

    checkpoint.write(video_id, STEP, {"narration_path": str(out_path), "provider": provider})
    if provider != "elevenlabs":
        _mark_needs_revoice(video_id)
    log.info("video %s: narration.mp3 written via provider=%s", video_id, provider)
    return out_path


def synthesize_outro(video_id: int, outro_text: str | None) -> Path | None:
    """Synthesize the short spoken outro (the seal->crack end-screen handoff) as its OWN mp3,
    on the SAME ElevenLabs brand voice as the narration. Returns the mp3 path, or None when
    there is no text, the brand voice is unavailable, or the monthly char quota is spent -- the
    outro card then plays music/silence (its pre-spoken behaviour). Never raises: the spoken
    outro is an enhancement and must never block voicing or the render.

    edge-tts is deliberately NOT a fallback here: a draft voice would make the outro a different
    speaker than the body (an inauthenticity signal), so an unavailable brand voice just omits
    the spoken outro instead of swapping voices mid-video."""
    text = (outro_text or "").strip()
    if not text:
        return None

    out_path = outro_voice_path(video_id)
    try:
        if checkpoint.is_done(video_id, OUTRO_STEP) and out_path.exists():
            return out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        status = char_guard.check_char_quota()
        if status.exhausted:
            log.warning(
                "video %s: elevenlabs char quota spent (%s/%s) -> no spoken outro",
                video_id, status.chars_used, status.quota,
            )
            return None
        # ElevenLabs writes mp3_44100_192 straight to out_path; the outro card re-reads it.
        synthesize_elevenlabs(
            text, out_path, video_id=video_id,
            prev_text=None, next_text=None, prev_request_ids=[],
        )
        if not out_path.exists() or out_path.stat().st_size == 0:
            log.warning("video %s: outro synth produced no audio -> no spoken outro", video_id)
            out_path.unlink(missing_ok=True)
            return None
    except (ProviderUnavailable, ProviderFailed, BudgetExceeded) as exc:
        log.warning("video %s: spoken outro synth skipped (%s)", video_id, exc)
        out_path.unlink(missing_ok=True)
        return None
    except Exception as exc:  # noqa: BLE001 - best-effort enhancement: never block voicing/render
        log.warning("video %s: spoken outro synth failed unexpectedly (%s) -> skipping", video_id, exc)
        out_path.unlink(missing_ok=True)
        return None

    # The checkpoint only lets a re-render skip re-billing; a write hiccup must not discard the
    # good audio we just made or propagate out of this best-effort step.
    try:
        checkpoint.write(video_id, OUTRO_STEP, {"outro_voice_path": str(out_path)})
    except Exception as exc:  # noqa: BLE001
        log.warning("video %s: outro checkpoint write failed (%s) — audio kept", video_id, exc)
    log.info("video %s: spoken outro voiced -> %s", video_id, out_path.name)
    return out_path


def _load_resumable_chunks(video_id: int, total_chunks: int) -> tuple[dict[int, dict], list[str]]:
    """Recover prior chunk progress: skip re-synthesizing/re-billing chunks whose audio is
    already on disk; discard progress that can't be trusted (chunk count changed since the
    last attempt, or the audio file is gone)."""
    saved = checkpoint.artifacts_of(video_id, CHUNKS_STEP) or {}
    saved_chunks: dict[int, dict] = {c["index"]: c for c in saved.get("chunks", [])}
    if saved.get("total_chunks") != total_chunks:
        if saved_chunks:
            log.warning(
                "video %s: chunk count changed since last attempt (%s -> %s), discarding stale tts progress",
                video_id, saved.get("total_chunks"), total_chunks,
            )
        saved_chunks = {}
    saved_chunks = {i: c for i, c in saved_chunks.items() if Path(c["path"]).exists()}
    prev_request_ids = [
        saved_chunks[i]["request_id"] for i in sorted(saved_chunks) if saved_chunks[i].get("request_id")
    ]
    return saved_chunks, prev_request_ids


def _make_on_chunk_done(video_id: int, chunk_dir: Path, chunk_records: dict[int, dict], total_chunks: int):
    def _on_chunk_done(index: int, provider: str, request_id: str | None) -> None:
        raw_path = chunk_dir / f"chunk_{index:03d}.raw"
        mp3_path = chunk_dir / f"chunk_{index:03d}.mp3"
        _to_mp3(raw_path, mp3_path)
        raw_path.unlink(missing_ok=True)
        chunk_records[index] = {
            "index": index, "path": str(mp3_path), "provider": provider, "request_id": request_id,
        }
        # Persist immediately (not batched at the end) -- this IS the resumability point: a
        # crash right after this write loses at most the chunk in flight, never an earlier one.
        checkpoint.write(
            video_id, CHUNKS_STEP,
            {"total_chunks": total_chunks, "chunks": sorted(chunk_records.values(), key=lambda c: c["index"])},
        )

    return _on_chunk_done


def _mark_needs_revoice(video_id: int) -> None:
    with SessionLocal() as s:
        video = s.get(Video, video_id)
        if video is not None and not video.needs_revoice:
            video.needs_revoice = True
            s.commit()
    log.warning("video %s: narration used a fallback provider -> needs_revoice=True", video_id)


def _run_ffmpeg(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({cmd[0:2]}...): {result.stderr[-2000:]}")


def _to_mp3(src: Path, dst: Path) -> None:
    """Normalize every chunk to the same codec/rate so concat/crossfade never mismatches formats."""
    _run_ffmpeg(["ffmpeg", "-y", "-i", str(src), "-ar", "44100", "-ac", "1", "-b:a", "128k", str(dst)])


def _concat(mp3_paths: list[Path], out_path: Path, *, crossfade: bool) -> None:
    if len(mp3_paths) == 1:
        _run_ffmpeg(["ffmpeg", "-y", "-i", str(mp3_paths[0]), "-c", "copy", str(out_path)])
        return
    if not crossfade:
        _concat_demuxer(mp3_paths, out_path)
        return
    _concat_crossfade(mp3_paths, out_path)


def _concat_demuxer(mp3_paths: list[Path], out_path: Path) -> None:
    list_file = out_path.parent / f"_concat_list_{out_path.stem}.txt"
    list_file.write_text("\n".join(f"file '{p.resolve()}'" for p in mp3_paths), encoding="utf-8")
    try:
        _run_ffmpeg(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out_path)]
        )
    finally:
        list_file.unlink(missing_ok=True)


def _concat_crossfade(mp3_paths: list[Path], out_path: Path) -> None:
    """Chain `acrossfade` pairwise across N inputs so overlapped chunk boundaries blend
    instead of hard-cutting (concat demuxer alone can't crossfade)."""
    inputs: list[str] = []
    for p in mp3_paths:
        inputs += ["-i", str(p)]

    filter_parts = []
    prev_label = "0:a"
    for i in range(1, len(mp3_paths)):
        out_label = f"cf{i}"
        filter_parts.append(f"[{prev_label}][{i}:a]acrossfade=d={CROSSFADE_SEC}:c1=tri:c2=tri[{out_label}]")
        prev_label = out_label

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", f"[{prev_label}]",
        str(out_path),
    ]
    _run_ffmpeg(cmd)
