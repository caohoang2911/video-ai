# Brainstorm Summary — Anti-ban improvements + motion-first + P1 roadmap (260708-2109)

> Status: **HỘI TỤ — sẵn sàng /ck:plan**. Builds on committed phases 01-06 (`e90c147`).
> Research: 3 workflows (TTS license, stock-video/motion, YouTube AI-detection 2026). Reports in `plans/reports/`.

## Problem
Phases 01-06 code-complete but plan flagged 5 "anti-ban/flag" spec changes NOT yet in code, plus P1 phases 07-09. Goal: harden against YouTube's 2026 "inauthentic content" enforcement (Jan-2026 wave removed 16 channels) without over-engineering.

## Research verdict — reprioritization (key insight)
- YouTube targets **inauthentic/mass-produced/zero-editorial**, NOT "video vs stills". Strongest survival signals = **consistent brand voice + editorial POV + varied cadence + human review** (mostly already built).
- **SDXL non-photorealistic images (maps/diagrams) = EXEMPT** from disclosure + auto-detection (only photorealistic flagged). No SDXL fear.
- **Disclosure = zero monetization penalty**; generic AI voice (no real-person impersonation) needs **no disclosure**.
- **edge-tts = Microsoft ToS violation for commercial** → must NEVER publish. **ElevenLabs Starter + Chatterbox (MIT)** = publish-safe.
- **Motion b-roll: NO rigid ratio** — just avoid 3+ min silent slideshow. → item 2 is the biggest build for a MEDIUM lever (still worth it: render-time + slideshow-avoidance).

## Decisions locked (user-confirmed 260708-2109)
- **Voice fallback = 1a: ElevenLabs is the ONLY publishable voice.** Any fallback → `needs_revoice=True`, publish blocked, re-voice with ElevenLabs later. Drop OpenAI from chain (different voice = pointless for brand). edge-tts = draft-only preview (never published → no ToS breach).
- **Item 2 = FULL this round** (motion-first hybrid + ffmpeg-subprocess encode).
- Scope includes P1 roadmap phases 07-09.

## Design

### Tier A — cheap, high anti-ban ROI
**Item 1 — voice consistency** (foundation + phase 03/06/05)
- Foundation: add `Video.needs_revoice` (bool, default False).
- `media/tts_providers.py`: PER-VIDEO single provider (no mixing). Order: ElevenLabs (publish) → edge-tts (draft, sets needs_revoice). Lock 1 `ELEVENLABS_VOICE_ID`.
- `media/tts_narrator.py`: if provider != ElevenLabs → set `needs_revoice=True`.
- `publisher/publish.py`: refuse to publish when `needs_revoice` (raise, surface in review).
- CLI: `revoice --video-id` (re-run ElevenLabs, clear flag).

**Item 3 — payoff quality gate + POV angle** (phase 02)
- `content/schema.py`: `PayoffNode{text:str, surprise_score:int 1-5}`; `payoff_nodes: list[PayoffNode]`. Reject script if <2 nodes with score ≥3.
- `angle` = interpretive POV ("why this was covered up / the overlooked lesson"), not neutral summary. Enforce in `prompts/script_system.md` + review reject.

**Item 4 — thumbnail_text pairing** (phase 02 → 04/06)
- `content/schema.py`: `TitleOption{title:str, thumbnail_text:str}`; `title_options: list[TitleOption]`.
- `assembler/thumbnail_generator.py`: overlay uses `thumbnail_text` (not keywords).
- `publisher/metadata_builder.py` + `ab_variants.py`: read `TitleOption.title`.

**Item 5 — EDSA checklist** (phase 05)
- `review/checklist.py`: add EDSA tickboxes (who/what/when/where/why SAID IN narration audio, not just metadata) + hook + payoff; block approval path when `needs_revoice`.

### Tier B — motion-first hybrid (phase 03 + 04, full)
- **Sourcing** (`media/stock_clients.py`, `visual_fetcher.py`, `asset_store.py`): add Pexels/Pixabay **Video** API search; video b-roll PRIMARY where available (~50-60%), Ken Burns stills for gaps. Coverage tiers: famous wreck 60-70% video, obscure ~0% (stills-heavy). `Asset.kind` gains `video_broll`. License: both no-attribution for monetized (verified).
- **Normalize** (new `media/video_normalize.py`): ffmpeg batch → 1920×1080@24fps CFR + `loudnorm=I=-16` before compositing (mixed fps/res/aspect otherwise breaks concat).
- **Assemble** (`assembler/segment_builder.py` new + `video_builder.py`): each beat = trimmed normalized video clip OR Ken Burns image segment; concat.
- **Encode refactor** (`assembler/ffmpeg_encode.py` new): replace MoviePy `write_videofile` (documented **10x regression** in 2.x) with ffmpeg subprocess using **`h264_videotoolbox` (M1 GPU accel, 3-5x)** → 10-min render ~6-9 min vs 40+. MoviePy kept only for orchestration/caption compositing. (Worth doing independent of motion.)

### Roadmap — phases 07-09 (P1)
- **07 scheduler + analytics** (`ops/` new pkg): APScheduler; cadence **2-4/week, randomized day/time** (anti-pattern signal); pull YouTube Analytics (views/retention/CTR); numeric kill-criteria; cron keep-alive (monthly `creds.refresh()`); read manual A/B winner → feed content-engine.
- **08 observability + deploy**: structured logs + metrics table; deploy target (Mac always-on vs Fly.io — still open).
- **09 validation run**: harness to track 10-20 video window vs kill/pass thresholds (retention >30-40%, CTR ~4-6%, 0 strikes).

## Implementation considerations / risks
- Schema changes (TitleOption, PayoffNode) ripple content→assembler→publisher (list[str]→list[obj]) — coordinate in one phase; update prompts + existing consumers.
- `needs_revoice` column = fresh-DB (delete dev `data/operator.db` + re-init, no real data yet).
- ffmpeg encode refactor is the riskiest (H.264 videotoolbox quality vs libx264; verify YouTube-accepted output). Keep libx264 fallback flag.
- Video b-roll download volume + storage (output/ gitignored) — cap clip count/size; cache.
- All runtime paths still blocked on phase 00 API keys — verify via compile+import+unit, real run after keys.

## Success metrics
- 1 video = exactly 1 voice provider; non-ElevenLabs → publish blocked until revoiced.
- Script rejected if <2 payoff nodes score ≥3, or angle is neutral summary.
- Thumbnails render `thumbnail_text`; publish title from `TitleOption.title`.
- Review shows EDSA checklist; needs_revoice blocks approval.
- Assembler produces hybrid video (b-roll where available) in <~10 min/10-min video via videotoolbox.
- Scheduler publishes at randomized 2-4/week cadence.

## Next steps
→ `/ck:plan` (default mode — greenfield additions, no critical behavior to lock via TDD). Feed this doc. Plan should phase: (A) foundation `needs_revoice` + Tier A items 1/3/4/5, (B) item 2 motion+encode, (C) phases 07-09.

## Unresolved questions
1. Deploy target P1 (Mac always-on vs Fly.io vs Hetzner) — phase 08.
2. Chatterbox brand-voice clone as publishable fallback — deferred to P1 (1a chosen for now); revisit if ElevenLabs quota churn hurts.
3. Archive.org public-domain historical footage integration (low-res but irreplaceable for specific wrecks) — P1 add to sourcing?
4. H.264 videotoolbox output quality acceptable vs libx264 — verify empirically at first real render.
