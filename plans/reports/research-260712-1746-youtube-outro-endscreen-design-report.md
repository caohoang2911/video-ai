# Research Report: High-Retention YouTube Outro + End Screen Layout (Correct YouTube Format)

Researched: 2026-07-12 17:46 (+07). Sources: 5 WebSearch sweeps, ~20 articles (2024–2026). Grounded against current pipeline (`src/ai_operator/assembler/branding.py`).

## Executive Summary

Current pipeline outro = 3s solid card, centered text, silent audio. Three problems: (1) too short — end screen elements need 5–20s of runway; (2) centered text sits exactly where YouTube overlays elements; (3) silent generic sign-off is a documented retention killer.

Recommended target: **12–15s outro**, text pushed to top third, two reserved zones matching YouTube's fixed element geometry (video 615×345, subscribe circle 294×294 at 1080p), continuous audio (music bed or TTS CTA line), per-video teaser line instead of generic "thanks for watching". Benchmarks: healthy end-screen click rate 3–7%; history channel case study got **35% of total watch time** from end-screen series chaining; verbal CTA formula lifted click rate from ~3% to 15%+.

End screen *elements* still cannot be set via YouTube Data API (verified earlier today — open feature request). Workflow: bake zones into outro card → position elements once in Studio → "Import from video" for every later upload.

## Key Findings

### 1. YouTube end screen mechanics (hard constraints)
- Elements display only in **last 5–20s** of video; video must be ≥25s. Always satisfied for long-form docs; N/A for Shorts (end screens don't run on Shorts).
- Up to 4 elements allowed; **2 elements (1 video + 1 subscribe) is the highest-converting config** — more choices dilute clicks.
- Element geometry at 1920×1080 (fixed by YouTube, not resizable for subscribe):
  - Video/playlist element: **≈615×345 px** (16:9).
  - Subscribe / channel circle: **≈294×294 px** (round).
- Safe zone: keep elements ~5–10% away from frame edges; avoid bottom strip (progress bar hover + captions) and bottom-right (duration badge).
- No API: add manually in Studio; **"Import from video"** copies a previous video's full layout in seconds.

### 2. CTR benchmarks
| Metric | Value |
|---|---|
| Healthy end-screen click rate | 3–7% (business channels 5–8%) |
| Compounding-growth threshold (series content) | >8% |
| Top performers | >15% |
| History-channel series chaining case study | 35% of total watch time from end-screen clicks |
| Verbal CTA (Link–Curiosity–Promise formula) | ~3% → 15%+ on some videos |

### 3. Retention best practices (what makes viewers click next instead of leaving)
1. **No hard cut.** Jarring transition (cut to black, music change) = click-away signal. Bridge: narration's final sentence flows into the outro visually + audibly.
2. **Verbal CTA starts 20–25s before video end** (i.e., in the last body beat), because elements only show in last 20s. Formula: Link ("watch this next") + Curiosity (tease the story) + Promise (what they'll get).
3. **Never a generic identical outro.** Same words/energy every video trains viewers to bail at the 20s mark. Parameterize: 1 teaser line per video.
4. **Don't say goodbye-words** ("thanks for watching, see you next time") as the ending — signals "video over, leave now". Better: "The next forgotten story is already on your screen."
5. **Silence kills.** Keep the music bed running under the outro (or a TTS CTA line). Current `anullsrc` silent card is the worst case.
6. **10–15s is the sweet spot** — enough time to click, not so long that retention graph craters.
7. Visual: simple, low-motion, brand-consistent background; arrows/labels pointing INTO the reserved zones; zones themselves stay empty.

### 4. Proposed 1080p layout (bake into ffmpeg card)

```
1920×1080, margins ≥96px, avoid bottom 120px
┌──────────────────────────────────────────────────────┐
│      The story continues...                          │  y≈150  headline (fontsize ~64)
│      {per-video teaser line, 1 sentence}             │  y≈240  teaser (fontsize ~40)
│                                                      │
│   Watch next ↓                     Subscribe ↓       │  y≈340  zone labels (~32)
│  ┌─────────────────┐            ╭─────────╮          │
│  │   VIDEO ZONE    │            │ SUB ZONE│          │  video: x=192  y=390  615×345
│  │   615 × 345     │            │ 294×294 │          │  sub circle: center (1540,560)
│  └─────────────────┘            ╰─────────╯          │        box (1393,413)–(1687,707)
│                                                      │
│              (bottom 120px kept clear)               │
└──────────────────────────────────────────────────────┘
```

- Draw faint outline boxes (`drawbox`, ~25% opacity white) so Studio element placement can be matched pixel-perfect once.
- Background: keep dark brand tone (`0x140a0a`) or a heavily-darkened archival still — low motion, no detail inside zones.

### 5. Pipeline changes (`branding.py` + upstream)

**Phase 1 — visual card (no new deps):**
1. `make_outro`: new `OUTRO_SECONDS = 12.0` (keep `CARD_SECONDS = 3.0` for intro).
2. Replace centered drawtext with top-anchored headline + teaser + 2 zone labels; add 2 `drawbox` outlines at coords above.
3. New param `teaser: str | None` — caller (video_builder) passes a per-video 1-liner; fallback static "Another forgotten story is waiting."
4. Teaser source: script/metadata generation already runs an LLM — add 1 field ("next-story hook", generic curiosity line since next video unknown at render time).

**Phase 2 — audio (bigger lift, flag first):**
- Best: extend music bed under outro with slow fade (needs music_picker/mux change — music currently only under body).
- Optional: TTS the CTA line (ElevenLabs quota impact ~1 sentence/video, small).

**Studio workflow (manual, once):**
- Upload → end screen editor → add "1 video + 1 subscribe", drag onto baked outlines → save. Every later video: **"Import from video"** (~15s). Element type: **"Best for viewer"** for standalone stories (our case); switch to explicit next-episode if a series is produced (that's where the 35%-watch-time case lives).

### 6. Security/quota considerations
- No new external calls in Phase 1. Phase 2 TTS option consumes ElevenLabs quota (currently gated by live subscription lookup — fine).
- Do NOT adopt unofficial `youtubei` Studio APIs for element automation — ToS risk, cookie fragility (already decided earlier today).

## Common Pitfalls
- Text/logo placed where elements overlay → looks broken after upload. (Current centered text does exactly this.)
- Outro < 5s → Studio refuses/clips element duration.
- 4 elements → lower CTR than 2.
- Identical outro audio+words every video → trained click-away.
- Forgetting bottom strip: captions + progress bar cover ~bottom 10%.

## Resources & References
- [Add end screens to videos — YouTube Help](https://support.google.com/youtube/answer/6388789?hl=en)
- [ThumbnailCreator — end screen sizes (615×345 / 294×294)](https://www.thumbnailcreator.com/specs/youtube-end-screen-size)
- [fetch. — end card dimensions deep dive](https://veryfetch.net/tutorials/an-in-depth-look-at-end-card-dimensions)
- [Gyre — high-converting end screens 2026](https://gyre.pro/blog/how-to-create-high-converting-youtube-end-screens-tips-and-examples)
- [NexLev — end screen tips 2026](https://www.nexlev.io/youtube-end-screen-tips)
- [Alan Spicer — final 20 seconds strategy](https://alanspicer.com/youtube-end-screen-strategy-final-20-seconds-grow-channel/)
- [TubeBuddy — end screen strategy / double watch time](https://www.tubebuddy.com/blog/youtube-end-screen-strategy-for-views-and-double-watch-time/)
- [tubeanalytics — end screens glossary + retention checklist](https://www.tubeanalytics.net/glossary/end-screens)
- [Humble & Brag — end screens setup + CTR benchmarks 2026](https://humbleandbrag.com/blog/youtube-end-screens)
- [videoboosters — end screen guide + safe zones](https://videoboosters.club/2024/08/21/youtube-end-screen/)
- [Fundmates — 7 end screen tips](https://www.fundmates.com/blog/7-tips-for-effective-youtube-end-screens)
- [Downloader Baba — ideal outro length](https://downloaderbaba.com/blog/ideal-length-for-youtube-outros-tips-for-creating-an-impactful-ending/)
- [Google Issue Tracker — end screen API feature request (still open)](https://issuetracker.google.com/issues/387277988)

## Next Steps
1. Implement Phase 1 in `branding.py` (12s card, top text, zones + outlines, teaser param). ~1 focused change + test render.
2. Decide Phase 2 audio approach (music-bed extension vs TTS line vs keep silent for now).
3. First upload after change: position elements in Studio on the outlines, save as the import template.

## Unresolved Questions
1. Music bed currently ends at body — extend under outro (mux change) or accept silent outro in Phase 1?
2. TTS CTA line per video: worth the ElevenLabs quota (~1 sentence/video)?
3. Element type: confirm "Best for viewer" (standalone stories) — switch to explicit next-video only if series format is adopted.
4. `assets/branding/outro.mp4` override path: if user later drops a custom outro.mp4, zone layout is their responsibility — document in README?
