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
- [ ] **ELEVENLABS_API_KEY** + **ELEVENLABS_VOICE_ID** — buy the **Creator tier ($22/mo, 100k chars/mo ≈
      5–6 narrations/mo)**; ElevenLabs is the ONLY publishable voice. Pick a **custom/cloned or
      deliberately distinctive** voice, NOT a popular default preset (a widely-reused default voice is
      itself an inauthenticity signal). Record the voice's provenance (cloned-from source / library id): `____________`.
- [ ] ~~**OPENAI_API_KEY**~~ — no longer used for TTS. The only fallback when ElevenLabs is unavailable is
      **edge-tts**, which produces a **draft-only** narration: the video is flagged `needs_revoice` and the
      publisher refuses to upload it until it is re-voiced with the brand voice (`operator revoice`).
- [ ] **PEXELS_API_KEY** + **PIXABAY_API_KEY** (free dev keys).
- [ ] **FAL_KEY** _(**required** with the default `IMAGE_GEN_BACKEND=fal_flux` — fal.ai FLUX.1-dev is now the
      primary image generator: ~$0.025/image, commercial output license via fal, ~$0.30/video / ~$4/month.
      Set `IMAGE_GEN_BACKEND=sdxl` for a free, fully-offline render using local SDXL first)_. The same key
      powers the **thumbnail hero** (FLUX Kontext relight of the primary archival photo, ~$0.04/video —
      toggle off with `THUMBNAIL_KONTEXT_ENHANCE=false`). `THUMB_RELEVANCE_MIN` (default 0.5, Gemini vision
      score 0..1) gates archival photo relevance; Gemini must confirm the image shows the event itself —
      not a memorial, plaque, museum model or illustration of it — else the hero falls back to synthetic.
      Requires `GEMINI_API_KEY`. `GEMINI_VISION_MODEL` (default `gemini-3.1-flash-lite`) is picked for
      free-tier request quota: the gate fires one call per candidate, and `gemini-2.5-flash`'s 5 req/min
      free limit left most images unjudged. If the backend can't judge half a pool, ops gets an alert.
- [ ] **TELEGRAM_BOT_TOKEN** (from @BotFather `/newbot`) + **TELEGRAM_CHAT_ID** (run `operator get-chat-id`).

## Budget / infra

- [ ] Attach billing to ElevenLabs (Starter). P0 burn ≈ **$0–30/month**.
- [ ] Confirm runway (design doc recommends ~$4–5K over 1–2 years for a real shot).
- [ ] Dev machine: this M1 Max 64GB is enough for P0. Image generation defaults to fal.ai FLUX.1-dev (cloud);
      local SDXL is the offline fallback (`IMAGE_GEN_BACKEND=sdxl` to force it). Deploy target decided later (phase 08).

## Verify when done

- [ ] `.env` filled; `git status` shows **no** secrets staged (`.env`, `client_secret.json`, `token.json`).
- [ ] `operator status` runs; API Audit submitted (pending or approved).

## Not blocking upload

YPP monetization (1,000 subs + 4,000 watch-hours) is a **P1 goal**, not required to upload. Enable AdSense when eligible.
