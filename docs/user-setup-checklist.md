# User Setup Checklist (Phase 00 — prerequisites only YOU can do)

> Code cannot do these. Several have long lead times — **start today**, in parallel with development.
> The longest pole is the **YouTube API Audit (2–4 weeks)** — submit it first.

## 🔴 Start immediately (long lead time)

- [ ] **Submit YouTube Data API Audit.** Google Cloud Console → your project → APIs & Services →
      YouTube Data API v3 → Audit form. Describe: *"personal, semi-automated, human-review-gated,
      AI-labeled documentary uploader."* Without approval, uploads are locked **private-only forever**.
      Record submit date: `____________`. Track email (2–4 weeks).

## Google account + channel

- [ ] Dedicated Google account for the project; verify phone; enable **2FA**.
- [ ] Create the **YouTube brand channel** (name/handle/avatar/banner) — niche: *Forgotten Maritime Disasters*.
      _(Note: custom thumbnails do NOT require phone verification per current YouTube docs, but 2FA is still recommended.)_

## Google Cloud / OAuth

- [ ] Create Google Cloud project → enable **YouTube Data API v3** + **YouTube Analytics API**.
- [ ] OAuth consent screen (External); scopes: `youtube.upload`, `youtube`, `yt-analytics.readonly`; add yourself as test user.
- [ ] OAuth **Desktop** client → download `client_secret.json` into the repo root (gitignored).
- [ ] Run `operator authorize` once → paste the printed **refresh token** into `.env` as `YT_REFRESH_TOKEN`.

## API keys (paste into `.env` — copy from `.env.example`)

- [ ] **ANTHROPIC_API_KEY** (Claude — script generation).
- [ ] **GEMINI_API_KEY** _(optional fallback)_.
- [ ] **ELEVENLABS_API_KEY** + **ELEVENLABS_VOICE_ID** (buy Starter ~$5/mo; pick a BBC-style deep male voice).
- [ ] **OPENAI_API_KEY** _(optional — TTS-1 fallback when ElevenLabs quota runs out)_.
- [ ] **PEXELS_API_KEY** + **PIXABAY_API_KEY** (free dev keys).
- [ ] **FAL_KEY** _(optional — cloud image fallback; P0 uses local/stock)_.
- [ ] **TELEGRAM_BOT_TOKEN** (from @BotFather `/newbot`) + **TELEGRAM_CHAT_ID** (run `operator get-chat-id`).

## Budget / infra

- [ ] Attach billing to ElevenLabs (Starter). P0 burn ≈ **$0–30/month**.
- [ ] Confirm runway (design doc recommends ~$4–5K over 1–2 years for a real shot).
- [ ] Dev machine: this M1 Max 64GB is enough for P0 (local SDXL optional). Deploy target decided later (phase 08).

## Verify when done

- [ ] `.env` filled; `git status` shows **no** secrets staged (`.env`, `client_secret.json`, `token.json`).
- [ ] `operator status` runs; API Audit submitted (pending or approved).

## Not blocking upload

YPP monetization (1,000 subs + 4,000 watch-hours) is a **P1 goal**, not required to upload. Enable AdSense when eligible.
