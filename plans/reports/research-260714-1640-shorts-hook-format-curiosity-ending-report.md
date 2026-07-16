# Research Report: Shorts Hook Format + Curiosity Ending That Funnels to Full Video

Date: 2026-07-14 16:40 (+07) | Sources: 4 WebSearch sweeps (2026 material) + internal A/B evidence (Halifax trio, videos 22/23/24)

## Executive Summary

Best-performing 2026 Shorts pattern for narrative/history niches: **hook lands < 2s** (30% higher avg view duration), **50–60s storytelling length** (narrative niches beat list content by 40–60% on retention), and a **"cliffhanger Short"** ending — deliver ~60% of the answer, stop, point to the rest — which converts to long-form **3–5x better** than complete-answer Shorts. The single biggest funnel lever is NOT in the script: the **Related video link** (+ pinned comment); description links are near-invisible. Healthy funnel CTR benchmark ≈ 5%.

Internal evidence agrees: Halifax #22 ("Every Clock Froze at 9:04") — effect-first/cause-withheld hook — outperformed siblings #23/#24 which led with cause/aftermath. Proposed format below merges both.

## Recommended Format: "FROZEN CLOCK" (45–55s, 5 blocks)

```
0–2s   COLD ANOMALY (effect-first, cause withheld)
       - One hyper-specific verifiable anomaly/artifact ("every clock stopped at 9:04")
       - First FRAME shows the anomaly (visual jolt; no channel intro, no greeting)
       - text_overlay <=6 words, fragment rhythm, strongest word first ("Every clock. Same second.")
2–15s  DOUBT beat — pre-empt skepticism ("dismissed as folklore, too neat to be real")
15–30s VERIFICATION TWIST — the ONE satisfying delivered fact ("archivists confirmed independently")
       -> short feels complete here, not a trailer (existing rule 2 kept)
30–45s ESCALATION — rule-of-three stakes reveal ("no flags, no markings, no escort")
       - NEVER name the disaster/casualty count (protected reveal stays in the long video)
45–55s ENDING RECIPE (the ~60% stop):
       a. Land the fact (completion feeling)
       b. PLANT one nameable unresolved detail (document/person/number)
       c. curiosity_question aimed at planted detail — answerable ONLY by full video
       d. end_card: 2 fragments re-opening the gap + CTA
       e. OPTIONAL LOOP: final image/line mirrors the opening frame -> rewatch;
          >100% completion is weighted ~2x by the algorithm
```

### The 60% rule (key new finding)
Cliffhanger Shorts that show ~60% of the answer then explicitly say where the rest lives convert 3–5x better than self-contained ones. Map: blocks 1–4 = the 60%; block 5 = the stop + pointer. Current pipeline rule 2 ("must feel complete") stays but the *batch* must not exceed 60% of parent payoffs → pairs with the Protected Reveal recommendation (exclude top-surprise payoff node from `_distill_parent`).

### Distribution mechanics (outside the script — do not skip)
1. **Related video link → parent video**: highest-visibility funnel; NOT settable via Data API — manual Studio step per Short.
2. Pinned comment with parent link (manual).
3. Description: curiosity line + `▶ Full video:` link — already implemented (`metadata_builder.py:86-94`). Keep, but treat as tertiary.
4. Benchmark: ~5% CTR on related-link surfaces; Shorts→long viewers have ~40% higher lifetime value.

## Fit With Current Pipeline (`short_script_generator._SYSTEM`)

Already compliant: self-contained rule, one-fact rule, ending recipe (land → plant → question), overlay <=6 words, title entity+number, 5–6 beats.
Gaps to add:
- G1: effect-first/cause-withheld hook directive (anomaly before event) — internal winner evidence.
- G2: doubt→verification beat as mid-video payoff.
- G3: protected-reveal at batch level (top payoff excluded; all curiosity_questions aim at it).
- G4: optional loop ending (end image echoes opening beat keyword).
- G5: narration target 75–110 words ≈ 30–45s; consider raising to ~110–140 words for 50–60s sweet spot (data: >40s Shorts get 33% higher engagement) — needs A/B, not blind change.

## Sources
- https://www.opus.pro/blog/youtube-shorts-hook-formulas
- https://www.conbersa.ai/learn/best-youtube-shorts-hooks
- https://virvid.ai/blog/ai-shorts-increase-retention-watch-time
- https://subscribr.ai/youtube-strategy/drive-traffic-shorts-to-long-videos
- https://fluxnote.io/guides/youtube-shorts-to-subscribers-strategy-2026
- https://marketmakermgmt.com/blog-list2/how-shorts-and-long-form-work-together
- https://joyspace.ai/looping-hack-trick-algorithm-double-views
- https://www.socialmediaexaminer.com/youtube-shorts-hooks-and-curiosity-loops-that-explode-your-views/
- https://www.shortimize.com/blog/youtube-shorts-retention-rate
- https://virvid.ai/blog/best-ai-niches-faceless-channels-2026

## Unresolved Questions
1. Optimal narration length for THIS channel (45s vs 55s) — needs A/B with avg_view_pct once analytics rows land.
2. Loop ending vs hard end-card: loop boosts rewatch but end-card carries the funnel CTA — test which nets more parent-video traffic.
3. Third-party stats (3–5x conversion, 5% CTR) are creator-tool blog figures, not YouTube official — treat as directional, validate against own Studio traffic-source data.
