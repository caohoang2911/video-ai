"""Start/stop/inspect the run-scheduler process from the control panel.

The scheduler is a separate always-on process (ops.scheduler); the panel only manages its
lifecycle: pgrep to detect, a detached Popen to start, SIGINT to stop (the same Ctrl-C the
CLI banner advertises, so APScheduler shuts down cleanly). Loopback-only panel, single
operator — process-level control is acceptable here.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

_PATTERN = "ai_operator.cli run-scheduler"      # pgrep -f pattern; matches the CLI invocation
_SRC_DIR = Path(__file__).resolve().parents[2]  # .../src — for the child's PYTHONPATH
LOG_PATH = _SRC_DIR.parent / "data" / "scheduler.log"


def pids() -> list[int]:
    try:
        out = subprocess.run(["pgrep", "-f", _PATTERN], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(p) for p in out.stdout.split()]


def is_running() -> bool:
    return bool(pids())


def start() -> dict:
    """Spawn run-scheduler detached (survives web restarts); no-op if already running."""
    existing = pids()
    if existing:
        return {"ok": True, "running": True, "pid": existing[0], "note": "already running"}
    env = {**os.environ, "PYTHONPATH": f"{_SRC_DIR}:{os.environ.get('PYTHONPATH', '')}"}
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "ab") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "ai_operator.cli", "run-scheduler"],
            stdout=log, stderr=log, env=env,
            start_new_session=True,  # detach: web dying must not kill the scheduler
        )
    return {"ok": True, "running": True, "pid": proc.pid}


def stop() -> dict:
    """SIGINT every scheduler process and wait briefly for a clean shutdown."""
    victims = pids()
    if not victims:
        return {"ok": True, "running": False, "note": "not running"}
    for pid in victims:
        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            pass
    for _ in range(20):  # chờ tối đa ~2s cho APScheduler tắt sạch
        if not pids():
            break
        time.sleep(0.1)
    return {"ok": True, "running": is_running()}
