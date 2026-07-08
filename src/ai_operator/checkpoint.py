"""Per-video checkpoints + idempotency keys.

A crash/restart between steps must not re-run a completed step (which could re-charge TTS
or re-upload to YouTube). After each step we atomically write the last completed step and
its artifact paths; `is_done`/`last_step` let the CLI/scheduler resume-from-last-step.
"""

from __future__ import annotations

import hashlib
import json
import os

from .config import CHECKPOINT_DIR


def _path(video_id: int | str):
    return CHECKPOINT_DIR / f"{video_id}.checkpoint.json"


def make_idempotency_key(*parts: str) -> str:
    """Stable 64-char key for a work unit (e.g. topic slug + step)."""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:64]


def read(video_id: int | str) -> dict | None:
    p = _path(video_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def write(video_id: int | str, step: str, artifacts: dict | None = None) -> None:
    """Record `step` complete (replacing any prior entry for the same step)."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    data = read(video_id) or {"video_id": video_id, "steps": []}
    data["steps"] = [e for e in data["steps"] if e["step"] != step]
    data["steps"].append({"step": step, "artifacts": artifacts or {}})
    data["last_step"] = step
    _atomic_write(video_id, data)


def last_step(video_id: int | str) -> str | None:
    data = read(video_id)
    return data.get("last_step") if data else None


def is_done(video_id: int | str, step: str) -> bool:
    data = read(video_id)
    return bool(data and any(e["step"] == step for e in data.get("steps", [])))


def artifacts_of(video_id: int | str, step: str) -> dict | None:
    data = read(video_id)
    if not data:
        return None
    for e in data.get("steps", []):
        if e["step"] == step:
            return e.get("artifacts")
    return None


def _atomic_write(video_id: int | str, data: dict) -> None:
    path = _path(video_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic on same filesystem
