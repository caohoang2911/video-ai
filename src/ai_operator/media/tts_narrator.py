"""Narration synth: chunk -> provider fallback chain -> ffmpeg concat (crossfade for
overlapped chunks) -> narration.mp3. Idempotent via the checkpoint step so a crash/retry
never re-synthesizes (and re-charges) an already-finished narration.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .. import checkpoint
from ..config import OUTPUT_DIR
from ..logging_setup import get_logger
from .tts_chunker import chunk_narration
from .tts_providers import synthesize_chunk

log = get_logger("tts_narrator")

STEP = "tts_narration"
CROSSFADE_SEC = 0.35  # short crossfade hides the repeated-tail overlap seam between chunks


def narration_path(video_id: int) -> Path:
    return OUTPUT_DIR / str(video_id) / "narration.mp3"


def synthesize(video_id: int, narration_text: str) -> Path:
    """Chunk -> synth chain per chunk -> concat. Returns narration.mp3 path (cached if done)."""
    if checkpoint.is_done(video_id, STEP):
        cached = checkpoint.artifacts_of(video_id, STEP) or {}
        cached_path = cached.get("narration_path")
        if cached_path and Path(cached_path).exists():
            log.info("video %s: narration already synthesized, skipping", video_id)
            return Path(cached_path)

    if not narration_text or not narration_text.strip():
        raise ValueError(f"video {video_id}: narration text is empty")

    chunks = chunk_narration(narration_text)
    out_path = narration_path(video_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"tts_{video_id}_") as tmp:
        tmp_dir = Path(tmp)
        prev_request_ids: list[str] = []
        providers_used: list[str] = []
        chunk_mp3s: list[Path] = []

        for i, chunk in enumerate(chunks):
            raw_path = tmp_dir / f"chunk_{i:03d}.raw"
            provider = synthesize_chunk(chunk, raw_path, video_id=video_id, prev_request_ids=prev_request_ids)
            providers_used.append(provider)
            mp3_path = tmp_dir / f"chunk_{i:03d}.mp3"
            _to_mp3(raw_path, mp3_path)
            chunk_mp3s.append(mp3_path)

        has_overlap = any(c.has_overlap_head for c in chunks)
        _concat(chunk_mp3s, out_path, crossfade=has_overlap)

    checkpoint.write(video_id, STEP, {"narration_path": str(out_path), "providers": providers_used})
    log.info("video %s: narration.mp3 written via providers=%s", video_id, providers_used)
    return out_path


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
