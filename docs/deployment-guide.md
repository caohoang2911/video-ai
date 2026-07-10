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

### 4. Web control panel (optional, alongside the scheduler)

A browser control panel + JSON API to view and drive the pipeline. Runs as its own long-lived
process; the scheduler must also be running for it to be useful (the panel only *enqueues* heavy
work — the scheduler drains the `jobs` table and executes it).

```bash
operator run-web                  # serves http://127.0.0.1:8000
operator run-web --port 9000      # override; host defaults to 127.0.0.1
```

Up to three processes share the one SQLite DB (WAL mode):

| Process              | Role                                                        |
|----------------------|------------------------------------------------------------|
| `operator run-scheduler` | executes queued jobs + the produce/publish/analytics loop |
| `operator run-web`   | control panel + API (enqueues jobs; never runs heavy work) |
| `operator run-bot`   | Telegram review (optional; coexists with the panel)        |

**Security:** binds `127.0.0.1` only and has **no auth** by design — the trust boundary is the
loopback interface. Do NOT expose it publicly or bind `0.0.0.0`. For remote access, tunnel over
SSH (`ssh -L 8000:127.0.0.1:8000 host`) rather than changing the bind.

Pages: `/` dashboard, `/videos`, `/videos/{id}`, `/topics`, `/jobs`, `/costs`, `/analytics`.
Every page has a JSON twin under `/api/...` (e.g. `curl http://127.0.0.1:8000/api/videos`).

**Analytics page:** `/analytics` shows real YouTube data — channel totals (subscribers / total
views / video count via the Data API), a cumulative-views trend chart (inline SVG), top videos,
per-video metrics, and a **"Refresh from YouTube"** button (enqueues `pull-analytics`; the
scheduler drains it). A "last pulled" line shows freshness.

> **Revenue is not shown.** `estimatedRevenue` / RPM need the `yt-analytics-monetary.readonly`
> OAuth scope, which is not requested (`oauth_headless.SCOPES`). To enable revenue: add that
> scope, re-run the one-time `authorize_once` flow to mint a new refresh token, then extend
> `analytics_puller` to query the monetary metrics. Until then the revenue columns stay empty
> and the UI omits them.

## Shorts (auto-generated from published mains)

When a MAIN video reaches `published`, one `gen-shorts` job is auto-enqueued (the scheduler
drains it). The job creates 2-3 child `Video` rows (`kind="short"`, `parent_id`), each:
fresh ~30-45s narration built from the parent's verified facts, ending on a curiosity-gap
question → TTS → vertical 1080×1920 render reusing the parent's images (blurred-pad + Ken
Burns, burned captions, question end card) → the SAME human review gate as mains.

- **Shorts NEVER auto-publish.** They stop at `pending_review` (or `rendered` without
  Telegram) and upload only after the same explicit approval a main needs.
- A short's upload description carries `#Shorts` + a `youtu.be` link to its parent; publish
  is refused while the parent has no YouTube id (dead-funnel guard).
- A REJECTED short is discarded, never reworked — re-roll a weak batch with the panel's
  "Tạo lại Shorts" button (`POST /videos/{id}/regenerate-shorts`, keeps published shorts).
- Filter the panel by kind: `/videos?kind=short`.

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
