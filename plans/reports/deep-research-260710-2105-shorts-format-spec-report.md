# Shorts Format Spec — deep-research 260710

Question: optimal format for faceless history/documentary Shorts (stills + TTS + captions), retention + funnel to parent long-form.

**Caveat:** verify phase failed both runs (session rate limit) — claims unverified but multi-source convergent (opus.pro, vidiq, virvid, longstories.ai, support.google.com). Treat numbers as directional, calibrate with real channel analytics after ~10 shorts.

## Research findings (converged)

| Dimension | Finding |
|---|---|
| Hook | Complete hook in ≤2-2.5s; first spoken word ≤0.5s; captions from word 1; text overlay during hook (+18% watch time, ~60% watch muted); mid-action open beats chronological setup; 50-60% drop-off in first 3s |
| Length | Storytelling sweet spot 30-45s (retention drops sharply past 45s); loop-driven content 15-25s (loops count as views since 03/2025); >70% completion ≈ +30% distribution |
| Visual pacing | Cut every 2-4s; new visual/story beat every 5-7s |
| Captions | Middle third of frame; clear of top 20% + bottom 25% (UI zones); bold white on semi-transparent box; phrase-level |
| Ending/funnel | Official "related video" link is the funnel mechanism (gated: needs advanced-feature access); Shorts description links not clickable; ~5% CTR benchmark; Shorts watch history feeds long-form recs since 08/2022 (algorithmic funnel exists without CTA) |
| Audio | (verify died — kept our measured duck/swell chain) |

## Encoded into pipeline (this session)

1. **Pinned title** (user directive + research): hook overlay drawn at mux stage (`post_fx`), static on top blur band for whole body, gold `0xF5C542` on black@0.45 box — no longer rides Ken Burns; visible for mid-video swipe-ins. `short_builder._pinned_title_fx`.
2. **Ambient motion** (user directive): animated warm gradients light-wash (screen blend 10%) + two-frequency brightness flicker — haze/lamplight feel over stills. `short_builder._ambient_fx` via `burn_and_mux(pre_fx=...)`.
3. **Caption position**: MarginV 55→85 (~570px up, clear of bottom-25% UI zone), FontSize 11 (~73px).
4. **Beat pacing**: schema max 5→7, prompt asks 5-6 beats (~6-7s/visual at 40s).
5. Already aligned: length 41-43s (30-45 band), narration starts ~0s, captions from word 1, entity-anchored titles, music duck/swell.

## Recommendations NOT applied (need owner decision)

1. **End card**: research suggests a 3s static end-card hurts completion/loop — alternative: overlay curiosity question on the LAST beat + spoken CTA, no card. Plan-confirmed decision ("end card") — not reversed without approval. Revisit after analytics.
2. **Related-video link**: set manually in Studio per short once channel has advanced-feature access (pipeline can't set it via API today).
3. **Pinned comment** with parent link as interim funnel (manual, or later via API).
4. Loop-format variant (15-25s, no end card) as an A/B experiment vs the 40s format.

## Unresolved
- Claims unverified (rate limit x2). Re-run verify if decisions get contentious.
- Shorts cadence + publish-throttle sharing with mains (from earlier report) still open.
