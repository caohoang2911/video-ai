---
phase: 4
title: "Motion-first b-roll sourcing"
status: done
priority: P2
effort: "4-6h"
dependencies: []
---

# Phase 4: Motion-first b-roll sourcing

## Overview
Add motion video b-roll (Pexels/Pixabay Video API) as the PRIMARY visual, with Ken Burns stills as the
gap-filler where maritime footage is scarce. Reduces the "static-slideshow" signature. Downloaded clips
are normalized to one format so the assembler (Phase 5) can concat them cleanly.

## Requirements
- Functional: for each shot beat, fetch a matching stock VIDEO clip; fall back to stock image / SDXL when
  no suitable footage; target ~50-60% of runtime as video where available. Persist `Asset(kind="video_broll")`.
  Normalize all clips to 1920×1080@24fps CFR + loudness-neutral (audio stripped).
- Non-functional: cache + rate-limit (Pexels 200/hr, Pixabay); md5 dedup; royalty-free (no attribution) only;
  cap clip count/size (storage under gitignored `output/`).

## Architecture
Extends the existing image-only media layer. `stock_clients.py` gains video search. `visual_fetcher.py`
becomes hybrid: video-first per beat, then image tiers (existing Pexels/Pixabay image → SDXL map/diagram).
Coverage is disaster-tier-dependent (famous wreck ~60-70% video, obscure ~0% → stills-heavy). New
`video_normalize.py` runs an ffmpeg batch pass so mixed fps/res/aspect clips become uniform before Phase 5.

## Related Code Files
- Modify: `src/ai_operator/media/stock_clients.py` (add `search_pexels_video(kw)`, `search_pixabay_video(kw)` → clip URLs + resolution; reuse cached/rate-limited sessions)
- Modify: `src/ai_operator/media/visual_fetcher.py` (per beat: video-first → image fallback tiers; record chosen asset kind; enforce ~50-60% video target where footage exists)
- Modify: `src/ai_operator/media/asset_store.py` (download + store video clips, `kind="video_broll"`, md5 dedup, license)
- Create: `src/ai_operator/media/video_normalize.py` (ffmpeg batch → 1920×1080@24fps CFR, strip audio, pad/scale letterbox-safe)
- Modify: `src/ai_operator/media/commands.py` (`gen-visuals` now yields a mix; optional `--stills-only` escape hatch)

## Implementation Steps
1. `stock_clients.py`: add video search endpoints (Pexels `/videos/search`, Pixabay `?video`); return best
   landscape ≥1080p file URL per hit; keep 24h cache + rate limiter.
2. `video_normalize.py`: `normalize(src, dst)` → ffmpeg `scale=1920:1080:force_original_aspect_ratio=decrease,
   pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=24,setsar=1` + `-an` (drop b-roll audio). Batch a beat's clips.
3. `visual_fetcher.py`: for each beat, try video (asyncio stock video search) → download + normalize; if none
   (or beat is a map/diagram) → existing image path (stock image → SDXL non-photoreal). Track per-video the
   video-vs-still ratio; log when a video falls below the motion target.
4. `asset_store.py`: persist video clips as `Asset(kind="video_broll", source, url_or_path, license, md5)`; dedup.
5. `commands.py`: keep `gen-visuals --video-id`; add `--stills-only` for cheap/offline runs.
6. Verify: compile + import; a beat with obvious footage keywords resolves to a normalized 1080p24 clip;
   fallback to stills works when video search is empty.

## Success Criteria
- [ ] `gen-visuals` produces a mix of normalized video clips + stills; `assets` rows tagged `video_broll` vs `stock`/`gen`.
- [ ] All fetched clips normalized to 1920×1080@24fps, audio stripped, md5-deduped.
- [ ] Video-vs-still ratio logged; stills-only fallback path works.
- [ ] License recorded for every asset (royalty-free, no attribution).
- [ ] compile + import clean.

## Risk Assessment
- Footage scarcity for obscure wrecks: expected; stills-heavy fallback keeps the pipeline unblocked (log coverage).
- Storage/bandwidth: cap clip count + resolution; clips live under gitignored `output/`.
- Pixabay video cache/ToS: honor 24h cache like the image path.
- Archive.org public-domain historical footage: deferred (P1) — noted as a future sourcing tier.

## Interim behavior + known limitations (until the hybrid assembler ships)
- **`gen-visuals` defaults to stills-only.** A b-roll beat writes `broll/beat_NN.mp4` but no
  `img/beat_NN.jpg`, and the current stills assembler requires a `.jpg` per beat — so a default
  motion run would produce un-assemblable output. `--motion` opts into the sourcing path for
  testing; the default (and the sequencing-gate command) stay renderable. The hybrid video
  assembler removes this constraint and should flip the default back to motion-first.
- **`acquire` is checkpoint-idempotent only for completed runs.** A crash mid-run leaves partial
  `Asset` rows with no checkpoint; on resume a beat that got footage re-downloads the same clip →
  md5 dedup returns None → the beat silently downgrades to the stills tier (a second asset for that
  beat) and undercounts the motion ratio. The hybrid assembler must select b-roll by
  `Asset(kind="video_broll")` DB rows (not a `broll/*.mp4` glob) so a stray/duplicate file can't be
  picked; a per-beat existing-asset skip in `acquire` is the follow-up if resume churn bites.
