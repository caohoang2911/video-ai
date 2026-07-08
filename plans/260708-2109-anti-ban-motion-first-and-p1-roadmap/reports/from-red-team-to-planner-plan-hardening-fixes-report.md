# Red-team → planner: plan hardening fixes (260708-2149)

Adversarial red-team of the increment-2 plan (5 lenses, 20 verified findings, 1 verify-agent errored).
Below = the fixes to apply to the plan BEFORE cook. Verdicts: CONFIRMED = real defect; PARTIAL = real but severity/scope adjusted.

## CONFIRMED — apply to plan

### F1 [P1 CRITICAL] revoice never re-renders final.mp4
`revoice` re-synths narration.mp3 + clears `needs_revoice`, but `final.mp4` (what publish uploads) still has the
old edge-tts audio baked in. → publishes wrong voice despite the gate.
**Fix (phase 01):** revoice = full teardown+rebuild: (1) force ElevenLabs re-synth of narration.mp3 (invalidate `tts_narration` checkpoint); (2) delete `output/<id>/final.mp4` + invalidate `assemble` checkpoint so the assembler resume can't reuse the stale render; (3) drive state back to a re-renderable state (VOICED) so `assemble` re-runs; (4) clear `needs_revoice` LAST, only after a clean ElevenLabs render.

### F2 [P2 CRITICAL] publish.py is an omitted title_options consumer + dict-vs-attribute
Plan writes `TitleOption.title` (pydantic attribute) everywhere, but disk consumers load script.json → get **dicts**, not pydantic objects. And `publish.py` (not in phase-2 modify list) injects bare strings into `title_options` (publish.py:55 no-script fallback `[title]`, publish.py:66 DB-title overlay) → half-updated shape crashes/mismatches.
**Fix (phase 02):** (a) Add `src/ai_operator/publisher/publish.py` to Related Code Files. (b) Pick ONE on-the-wire shape: `list[dict] {title, thumbnail_text}` in script.json. (c) Attribute access (`.title`) ONLY in script_generator (real `ScriptOutput`); disk consumers use dict access (`opt["title"]`, `opt.get("thumbnail_text","")`) — metadata_builder, thumbnail_generator, ab_variants, publish. (d) Fix publish.py no-script fallback to `[{"title": title, "thumbnail_text": ""}]`; rewrite the DB overlay to dict shape.

### F3 [P3 HIGH] needs_revoice block placed after query.answer()
callbacks.py:41 already calls `await query.answer()`; a second answer in decision_store fails.
**Fix (phase 03):** do the block in callbacks.py BEFORE line 41: after parsing code/video_id, if `code in (PASS_POLICY, PASS_QUALITY)` and `Video.needs_revoice` → `await query.answer("Blocked: run revoice first", show_alert=True)` as the SINGLE answer, then return (no state change).

### F4 [P5 HIGH] intro/outro caption/audio desync (body-relative vs full-timeline)
captions.srt + narration.mp3 are body-relative (t=0 = first body beat); burning/muxing them over the full
intro+body+outro timeline shifts everything by the intro length (~3s) for the WHOLE video.
**Fix (phase 05):** body-first ordering (mirror current MoviePy structure): (1) concat body segments → base.mp4; (2) one encode pass burns captions.srt + muxes ducked narration/music ONTO base.mp4 (t=0 preserved) → body.mp4; (3) THEN concat pre-rendered intro + body.mp4 + outro → final.mp4. Do NOT fold subtitles+amix+intro/outro-concat into one full-timeline filtergraph.

### F5 [P5 HIGH] branding.py out of scope for the ffmpeg path
load_intro/load_outro return MoviePy objects; the ffmpeg render path can't consume them.
**Fix (phase 05):** add `branding.py` to scope; generate intro/outro synth cards via pure ffmpeg (color + drawtext, silent AAC) matching the segment spec (1920×1080, 24fps CFR, yuv420p, setsar=1); route any user intro.mp4/outro.mp4 through the same normalize.

### F6 [P5 HIGH] split phase 5 into 5a (encode refactor, independent) + 5b (motion assembly, needs P4)
Encode refactor (write_videofile → ffmpeg_encode + srt_writer + videotoolbox, removes Pillow/TextClip fragility) does NOT depend on phase 4. Keep BOTH this round (respect "item 2 = FULL"), but sequence 5a first (buildable/verifiable on the existing stills path before motion b-roll exists).
**Fix (phase 05):** restructure into 5a (deps: []) + 5b (deps: 4) sub-stages; 5a = ffmpeg encode on current Ken Burns path; 5b = motion b-roll segments + hybrid concat.

### F7 [P5 MEDIUM] fps 24 (b-roll) vs 30 (Ken Burns) concat mismatch → seam hitch + duration inflation + caption desync
kenburns_ffmpeg.py hardcodes 30fps; b-roll normalized to 24fps; concat without fps normalize inflates timeline (empirically 4s→5s) and desyncs same-pass captions.
**Fix (phase 05):** lock ONE project fps = 24. Move `kenburns_ffmpeg.py` from Reference → Modify (FPS 30→24). Add explicit CFR `fps=24` at the concat boundary (prefer the concat FILTER with per-input `fps=24` over the demuxer). Tighten success criteria to a single 24fps.

### F8 [cross HIGH] no real automated tests; plan wrongly claims tests are key-gated
**Fix (plan.md + every phase):** add a key-free pytest suite under `tests/` (pyproject already declares pytest): schema round-trip through script.json consumers (catches F2), needs_revoice gating, SRT/fps invariants via ffprobe fixture, scheduler throttle+jitter with a frozen clock, validation thresholds at boundaries. Correct the plan text that says tests are key-gated — most units are key-free.

## PARTIAL — apply (severity/scope adjusted)

### F9 [P1] ElevenLabs monthly CHARACTER cap is invisible to budget_guard
budget_guard enforces only a USD cap ($500); 30k chars ≈ $9 never trips it. With voice=1a (ElevenLabs-only publishable) + cadence ≤3/week (~13/mo), Starter (30k ≈ ~3 videos/mo) silently forces most videos to needs_revoice.
**Fix:** (a) Add an ElevenLabs monthly CHARACTER ledger (reuse CostLedger: sum `units` WHERE provider='elevenlabs' AND ym=current); guard/alert at ~70% of the tier's char quota (phase 01). (b) phase 06 publish/produce job skips + alerts when the char quota is exhausted rather than silently over-flagging. (c) **USER DECISION (surface, do not silently pick): ElevenLabs tier vs cadence** — Starter 30k (~3/mo) / Creator 100k (~5-6/mo) / Pro 500k (~29/mo). Put the chosen tier + char arithmetic in phase 01 + plan.md "Locked decisions". Do NOT re-add OpenAI (can't publish under voice=1a).

### F10 [P1] voice UNIQUENESS, not just provider consistency
Research warns against a DEFAULT ElevenLabs voice ("voice everyone uses"); it recommends a custom/cloned/lesser-used voice ID.
**Fix (phase 01 + docs):** add success criterion that `ELEVENLABS_VOICE_ID` is a custom/cloned or deliberately distinctive voice, provenance recorded; update `docs/user-setup-checklist.md`.

### F11 [P1] discard-all-and-rerun + revoice re-bills whole narration; previous_text over-billed
**Fix (phase 01):** (a) make ElevenLabs synth per-chunk resumable — checkpoint each successful chunk audio + request-id; on retry synth only the missing tail (don't discard all + drop to edge on a late failure). (b) In tts_providers, pass `previous_text=None` when `previous_request_ids` is non-empty (ElevenLabs ignores previous_text then; also removes the internal char over-count at tts_providers.py:47).

### F12 [P4/5/7 HIGH] no cleanup/retention of output/<id>/ working dirs
b-roll clips + normalized copies + per-beat segments + base + final accumulate unbounded.
**Fix (phase 05 + 07):** delete intermediate normalized clips + per-beat segments immediately after a successful final encode; delete/prune `output/<id>/` working files after `published` (keep final.mp4 or archive off-disk). Add a disk-usage line to `ops/health`.

### F13 [cross HIGH] base pipeline 01-06 has never run end-to-end (no .env, 0 DB rows, no mp4)
Building ~20-37h of increment-2 on never-executed code risks compounding integration bugs.
**Fix (plan.md sequencing gate):** before phase 5's rewrite (ideally before phase 4), insert a gate: obtain keys/.env + run ONE real video end-to-end through the existing 01-06 CLI (`gen-script → gen-audio → gen-visuals --stills-only → assemble → notify-review → publish` to a private test upload). Phase 5's encode refactor (5a) can proceed on the stills path once one real render exists.

## Unresolved questions (for user)
1. **ElevenLabs tier** (Starter/Creator/Pro) reconciled with cadence — blocks phase 01/06/08 numbers. (F9)
2. Voice uniqueness: use a cloned/custom voice, or an explicitly chosen distinctive ElevenLabs preset? (F10)
3. Run-one-real-video gate acceptable before the phase-5 rewrite, or build blind? (F13)
