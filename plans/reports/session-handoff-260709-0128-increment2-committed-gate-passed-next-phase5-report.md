# Session handoff 260709-0128 — increment-2 done + sequencing gate PASSED → next Phase 5

## State (resume here tomorrow)
- Branch `main`, working tree clean except untracked `.claude/` (tooling, intentionally uncommitted).
- Plan: `plans/260708-2109-anti-ban-motion-first-and-p1-roadmap/`. Phases 1-4 = **done**; 5-8 = pending.
- Test video #1 in `output/1/` (gitignored): `state=rendered`, `needs_revoice=True`, real Pixabay stills (7/10 beats) + 3 placeholder beats, edge-tts draft narration. It is a TEST artifact.

## Commits this session (on top of scaffold e90c147)
- `43d896e` feat(pipeline): increment-2 P1-4 (voice/revoice, content-quality gates, EDSA review, motion b-roll sourcing) + 47 key-free tests
- `c6543a6` docs(plans): increment-2 plan + reports
- `26a5937` docs(setup): ElevenLabs Creator tier + single brand voice
- `37e8c56` fix(llm): disable Gemini thinking (was returning empty text → crash)
- `590fc38` fix(assembler): beat-duration drift spread proportionally (was dumping ~94% on last beat)

## Sequencing gate result (the point: prove committed base pipeline runs)
PASSED end-to-end for real: `gen-topics`(seed) → `gen-script`(Gemini) → `gen-audio`(edge-tts draft) →
placeholder/real visuals → `assemble` → real `final.mp4` (458s, 1920x1080, H.264+AAC). Not yet run:
`notify-review`, `publish` (need Telegram + ElevenLabs + YouTube OAuth).

## Key environment facts (IMPORTANT for next session)
- `.env` exists (gitignored). Set: `ANTHROPIC_API_KEY` (but account **$0 credit** → 400), `GEMINI_API_KEY` (works),
  `PIXABAY_API_KEY` (works, 34 chars). Empty: ElevenLabs, Pexels, FAL, YouTube, Telegram.
- Content LLM = Claude-primary → **Gemini fallback** (`content/llm_client.py`); since Anthropic is $0, everything
  runs on Gemini free tier. Add Anthropic credit for higher-quality scripts (optional).
- edge-tts (free, no key) works → draft narration, sets `needs_revoice=True` (publish correctly blocked).
- No `torch`/`diffusers` (SDXL off) and no `fal-client` → beats flagged diagram/`illustration` get no generated
  image; they keep a placeholder still. faster-whisper + moviepy + ffmpeg all present.
- **Security (resolved):** the real Anthropic/Gemini keys were only ever in the working-tree `.env.example`
  (now blanked); verified they NEVER entered git history (not in e90c147, not in dangling initial 7013f12).
  History scrub = no-op. Rotating those two keys is precautionary only.

## Two quality bottlenecks — both are Phase 5
1. Render is slow (~22 min) — MoviePy software libx264. Phase 5a = ffmpeg-subprocess + `h264_videotoolbox`.
2. Static Ken-Burns slideshow + generic/off-topic stock stills. Phase 5b = motion b-roll assembly (uses the
   already-built Phase 4 sourcing). Consider better image sources (local SDXL for topic-specific, Archive.org footage).

## Next session — Phase 5
- Start with **Phase 5a** (encode refactor, deps: []): `phase-05-hybrid-assembler-ffmpeg-encode.md`. Buildable/
  verifiable on the current stills path now that a real render exists (gate satisfied).
- Then **5b** (motion assembly, deps: [4]) — needs a free Pixabay/Pexels **video** key when running for real.
- Reviewer notes to honor when building 5: F4 body-relative caption/audio timing, F5 branding via pure ffmpeg,
  F7 lock ONE fps=24 (move `kenburns_ffmpeg.py` 30→24), F12 output/<id>/ retention cleanup.
- `db/models.py` note: assembler selects b-roll by `Asset(kind="video_broll")` DB rows, NOT a `broll/*.mp4` glob
  (avoids the normalize-orphan trap).

## Housekeeping / open items
- Placeholder demo helper: `scratchpad/render_placeholder_visuals.py` (not committed; scratchpad only).
- To redo video #1 as a real one later: clear placeholders, add ElevenLabs, `operator revoice --video-id 1`.
- Base-pipeline mislabel (not fixed, cosmetic): `script_generator.generate` labels an LLM outage as
  "research_gate rejected topic". Non-blocking (FAILED→SCRIPTED recovers on retry).

## Unresolved questions (for user)
1. Phase 5a (fast encode) first, or 5b (motion) first? (Recommended: 5a — quicker win, unblocks 5b verification.)
2. Add Anthropic credit for script quality, or stay on free Gemini?
3. Image-source strategy for topic relevance: local SDXL install, Archive.org, or accept generic stock?
