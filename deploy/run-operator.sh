#!/usr/bin/env bash
# Keep the always-on operator alive on macOS: run the scheduler in the foreground and
# restart it if it ever exits non-zero (crash), with a backoff so a hard-failing start
# can't hot-loop. Ctrl-C (SIGINT/SIGTERM) stops the supervisor cleanly.
#
# Usage:  deploy/run-operator.sh            # from the project root
# Stop:   Ctrl-C, or `pkill -f run-operator.sh`
# For login-persistent always-on instead of a terminal, use the launchd plist alongside this.

set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

PYTHON="${OPERATOR_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
BACKOFF=5          # seconds; grows on repeated fast failures
MAX_BACKOFF=300

trap 'echo "[run-operator] stopping"; exit 0' INT TERM

echo "[run-operator] project=$PROJECT_ROOT python=$PYTHON"
while true; do
  start=$(date +%s)
  PYTHONPATH=src "$PYTHON" -m ai_operator.cli run-scheduler
  code=$?
  [ "$code" -eq 0 ] && { echo "[run-operator] scheduler exited cleanly"; break; }

  ran=$(( $(date +%s) - start ))
  if [ "$ran" -ge 60 ]; then
    BACKOFF=5                                   # ran a while -> reset backoff
  else
    BACKOFF=$(( BACKOFF * 2 )); [ "$BACKOFF" -gt "$MAX_BACKOFF" ] && BACKOFF=$MAX_BACKOFF
  fi
  echo "[run-operator] scheduler crashed (code=$code after ${ran}s) — restarting in ${BACKOFF}s"
  sleep "$BACKOFF"
done
