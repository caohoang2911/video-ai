# Brainstorm → Design: Auto-generate Shorts from published main videos

Date: 2026-07-10 · Source: /brainstorm · Status: approved → /ck:plan

## Problem
From each published main documentary, auto-produce **2-3 vertical Shorts** that tease the
story and **funnel viewers to the channel / full video**. Each short must be self-contained
but **end on a curiosity-gap question** so viewers search out the full video — without killing
interest (no cheap cutoff, no full spoiler).

## Confirmed requirements (user answers)
- **Content/audio:** LLM writes NEW self-contained short scripts (hook → 1-2 verified facts →
  curiosity-gap question CTA) + re-TTS. NOT literal slices of the main narration.
- **Render:** re-render **vertical 9:16 (1080×1920)** from assets (reuse assembler), not crop.
- **Trigger:** auto after the main video is `published`.
- **Publish flow:** shorts go through the **same review gate** (web/Telegram) → approve → publish.
- **Count/length:** 2-3 shorts/video, ~30-45s each.

## Scout facts grounding the design
- Highlight signals already in `script.json`: `payoff_nodes` (surprise_score 1-5), `hooks`,
  `shot_list` (keywords/mood). No new extraction pass needed.
- `beat_timing.compute_beat_durations()` → per-beat timestamps (slicing feasible, though not used).
- Assembler renders **landscape 1920×1080/24** (`video_builder.py`); **no vertical path yet** (the gap).
- Narration is one `narration.mp3`; re-TTS of a ~40s short ≈ ~600 chars ≈ **1.8% of the 100k
  ElevenLabs monthly quota for 3 shorts** → re-TTS is cheap (budget is NOT a blocker).
- Review gate (`record_decision`), publish/OAuth, web panel, job queue all reusable per-`video_id`.

## Recommended solution — "Short = child Video, vertical re-render, curiosity-gap script"
**Data model (DRY):** a short is a normal `Video` row + 2 new columns `kind` ("main"|"short",
default main) + `parent_id` (FK videos.id). Shorts reuse the SAME state machine, review gate,
publish, and web panel — near-zero new plumbing.

**Pipeline (auto after main `published`):**
1. Main → `published` → enqueue `gen-shorts` job (parent_id).
2. `short_script_generator` (LLM): reads parent `script.json` (rank by `surprise_score`, reuse
   citations/hooks) → 2-3 self-contained ~40s scripts, each ending on a curiosity-gap question +
   soft "full on the channel" CTA. Guard: satisfy but don't spoiler.
3. Create 2-3 child `Video` rows (kind=short, parent_id).
4. Short pipeline (reuses steps): re-TTS (char-guarded) · reuse parent Asset images matched by
   keyword (no new sourcing) · **vertical assemble 1080×1920** (Ken Burns pan within 9:16 or
   blurred-pad; burn-in captions since Shorts play muted; CTA end-card).
5. Short → `pending_review` → same review gate → approve.
6. Publish as YouTube Short: vertical <60s + `#Shorts` + **parent-video link in description** (funnel).

**Reuse:** state machine, record_decision, publish/OAuth, web panel, job queue, tts+char-guard,
assembler steps, budget guards. **New:** `kind`/`parent_id` columns, `short_script_generator`,
portrait render path, `gen-shorts` job + DISPATCH, publish `#Shorts`+link variant, auto-enqueue.

## Alternatives rejected
- **Crop final.mp4 → 9:16:** lossy crop, cuts overlays, awkward mid-narration audio.
- **Separate `Short` table:** re-implements review/publish → violates DRY.
- **Slice original narration:** doesn't stand alone; re-TTS is cheaper and better.

## Risks / mitigations
- Landscape stock → vertical framing: Ken Burns pan / blurred-pad.
- Curiosity-gap quality is make-or-break: strong prompt + surprise_score selection + human review in flow.
- **Dependency:** needs published main videos + working OAuth (currently blocked: `invalid_grant`,
  0 published videos). Capability builds now; runs once the channel is live.
- YouTube "Short" classification is automatic (vertical + ≤3min); #Shorts + <60s guarantees it.
- Extra YouTube upload-quota use (~1600 units/short) — fine within daily 10k.

## Scope
IN: short-script gen, vertical render, review-gate integration, publish-as-Short + parent link,
web-panel surfacing (kind badge/filter), auto-enqueue after publish.
OUT (this round): music beat-sync, face-cam, A/B on shorts, shorts→channel attribution analytics.

## Phased outline (for /ck:plan)
1. Data model: `kind` + `parent_id` on Video (+ init-db) + state-machine touch.
2. `short_script_generator` (LLM, curiosity-gap schema).
3. Vertical render path (portrait assembler, reuse kenburns/caption/branding/ffmpeg).
4. `gen-shorts` job + auto-enqueue after publish + child pipeline wiring.
5. Publish-as-Short (#Shorts + parent link) + web-panel surfacing.
6. Tests + docs.

## Success metrics
From 1 published main video → 2-3 vertical ≤60s shorts auto-generated, each self-contained
ending on a curiosity question with a parent-video link, landing in review; after approve,
published as Shorts.

## Unresolved questions
- Exact funnel copy/CTA card style (defer to implementation; templated).
- Which subset of parent assets maps to each short (keyword-match heuristic vs LLM-pick) — decide in Phase 2/3.
