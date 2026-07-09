# Deployment Guide

The operator is an always-on, self-guarding loop. Default deploy target: **the M1 Mac,
always-on** (no cloud infra at P0). A container path is included for a future move.

## Prerequisites

- Setup complete per `README.md` (venv installed, `.env` filled, `init-db` run).
- `ffmpeg` on PATH.
- The scheduler jobs self-guard on missing config, so starting before every key is set is a
  safe no-op loop — but publishing needs YouTube OAuth + ElevenLabs (see
  `docs/user-setup-checklist.md`).

## Run modes

### 1. Foreground (dev / manual)

```bash
PYTHONPATH=src .venv/bin/python -m ai_operator.cli run-scheduler   # Ctrl-C to stop
# or, with the installed entrypoint:
operator run-scheduler
```

### 2. Supervised always-on (recommended, terminal)

Restarts the scheduler on crash with backoff:

```bash
deploy/run-operator.sh            # from the project root; Ctrl-C to stop
```

Override the interpreter with `OPERATOR_PYTHON=/path/to/python deploy/run-operator.sh`.

### 3. Login-persistent always-on (launchd)

Survives logout/reboot and relaunches the supervisor if killed:

```bash
# 1. Edit the 4 /ABSOLUTE/PATH/TO/video-ai placeholders in the plist first.
cp deploy/com.aioperator.scheduler.plist ~/Library/LaunchAgents/
launchctl load  ~/Library/LaunchAgents/com.aioperator.scheduler.plist   # start
launchctl unload ~/Library/LaunchAgents/com.aioperator.scheduler.plist   # stop / remove
```

launchd stdout/stderr go to `output/logs/launchd.{out,err}.log`; the app's own rotating log
is `output/logs/operator.log`.

## Monitoring

```bash
operator health                   # one-screen: states, budget, char/YT quota, last publish,
                                  # recent errors, retention/CTR, output/ disk usage
operator health --json            # same, machine-readable
operator status                   # month-to-date USD budget
operator costs                    # cost ledger by provider
```

`health` tails `output/logs/operator.log` for ERROR/ALERT lines. Real problems (char quota
exhausted, dead OAuth token) also push to the Telegram review chat when configured.

### Disk hygiene

`health`'s disk line shows `output/` total + per-child size. A lingering numeric child
(`output/<id>/`) means a per-video working tree missed cleanup — safe to remove once the
video is `published` and `final.mp4` is archived off-disk.

## Validation (go/no-go)

After the first 10–20 published videos:

```bash
operator validation-report --window 20      # PASS_P0 / KILL_P0 / INSUFFICIENT_DATA + rationale
```

Record the decision outcome per run (see `docs/` / changelog). Policy strike count has no
public API — set it manually in `app_state` (`policy_strikes`) before running if any strike
was received.

## Cloud (optional, not activated)

`deploy/Dockerfile` builds the core pipeline (no SDXL/torch) for a future Fly.io/Hetzner
move. Off-Mac there is no `h264_videotoolbox`, so it forces `AI_OPERATOR_ENCODER=libx264`.
Mount `data/` and `output/` so the SQLite db + renders survive restarts.

```bash
docker build -f deploy/Dockerfile -t ai-operator .
docker run --env-file .env -v "$PWD/data:/app/data" -v "$PWD/output:/app/output" ai-operator
```
