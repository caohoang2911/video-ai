# AI Operator — Faceless YouTube Documentary Pipeline

Semi-automated pipeline that produces long-form (8–15 min) faceless documentary videos
for the **Forgotten Maritime Disasters** niche and publishes them to YouTube, with a
mandatory human review gate (Telegram) that keeps the channel compliant with YouTube's
AI-content policy.

**Flow:** `topic → script → voice → visuals → assemble → review (Telegram) → publish (YouTube)`

Each video moves through a state machine:
`draft → scripted → voiced → rendered → pending_review → policy_ok → approved → published → analyzed`
(plus `rejected`, `editing`, `rerun_queued`, `failed`).

## Requirements

- **Python 3.11** (target; not 3.12+ — MoviePy 2.x / faster-whisper stability)
- **ffmpeg** on PATH
- Apple Silicon recommended for local SDXL (optional)

## Setup

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .          # full deps
# or minimal foundation only during early dev
cp .env.example .env                          # then fill keys (see plans/phase-00)
PYTHONPATH=src .venv/bin/python -m ai_operator.cli init-db
```

## CLI (early P0 — run each step by hand)

```bash
operator init-db                 # create SQLite schema
operator status                  # month-to-date budget remaining
operator costs                   # cost ledger by provider
operator run-scheduler           # always-on loop: produce/publish/analytics + job queue
operator run-web                 # local control panel + JSON API on 127.0.0.1:8000
# later phases add: gen-topics, gen-script, gen-audio, gen-visuals,
#                   assemble, run-bot, notify-review, authorize, publish
```

`run-web` is a browser control panel to view and drive the whole pipeline. It binds loopback
only with no auth (see `docs/deployment-guide.md` → "Web control panel"); it enqueues heavy
work into a DB `jobs` table that `run-scheduler` drains — run both together.

## Architecture & plan

Design + phased plan live in `plans/260708-1548-lean-faceless-ai-video-operator-system/`.
Guardrails baked into the foundation: monthly **budget hard-cap**, **idempotency keys** +
**checkpoints** (no duplicate charges/uploads on retry), and **semantic topic dedup**
(no near-duplicate content). All AI media is disclosed on upload and only royalty-free
assets are used.

## Security

Secrets live in `.env` (gitignored). Never commit `.env`, `client_secret.json`,
`token.json`, or refresh tokens.
