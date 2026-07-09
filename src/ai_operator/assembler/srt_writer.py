"""Whisper caption segments -> an SRT file that ffmpeg's `subtitles=` filter burns in.

Replaces the MoviePy TextClip/Pillow render path: one `.srt` on disk, one ffmpeg pass, no
per-caption Python rasterization. Timestamps are narration-relative (t=0 = first body beat),
which is exactly what the body-first mux burns onto `base.mp4` before intro/outro are joined.
"""

from __future__ import annotations

from pathlib import Path


def _ts(seconds: float) -> str:
    """Seconds -> `HH:MM:SS,mmm` (SRT's comma-decimal timestamp)."""
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments: list[dict], path: str | Path) -> Path:
    """Write `[{start, end, text}]` to `path` as SRT; returns the path.

    Empty-text segments are skipped; a non-increasing end (whisper occasionally emits
    end<=start on a very short segment) is nudged forward so the cue is still displayable.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks: list[str] = []
    index = 1
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        if end <= start:
            end = start + 0.5
        blocks.append(f"{index}\n{_ts(start)} --> {_ts(end)}\n{text}\n")
        index += 1
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path
