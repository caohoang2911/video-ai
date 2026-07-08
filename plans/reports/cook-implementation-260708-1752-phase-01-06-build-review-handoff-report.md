# Cook Handoff — Phase 01-06 built, reviewed, fixed (260708-1752)

## What shipped
Greenfield Python pipeline `ai_operator` (src layout, Python 3.11 venv). Package renamed from
`operator` → `ai_operator` (stdlib clash). ~3.9k LOC, **every file < 200 lines**.

| Phase | Package | State |
|---|---|---|
| 01 foundation | `config, constants, logging, db/{engine,models,models_ops,state_machine}, cost/{estimator,budget_guard}, checkpoint, dedup, cli` | ✅ done, runtime-verified |
| 02 content | `content/` (llm_client, schema, research_gate, pattern_tracker, prompt_builder, topic_backlog, script_generator, commands) + `prompts/` + seed_topics.yaml | ✅ code-complete + reviewed |
| 03 media | `media/` (tts_chunker, tts_providers, tts_narrator, stock_clients, visual_fetcher, local_sdxl, cloud_flux, asset_store, commands) | ✅ code-complete + reviewed |
| 04 assembler | `assembler/` (kenburns_ffmpeg, caption_whisper, audio_mixer, branding, beat_timing, video_builder, thumbnail_generator, commands) | ✅ code-complete + reviewed |
| 05 review | `review/` (telegram_bot, review_notifier, callbacks, decision_store/codes/finalize, keyboards, checklist, caption, media_host, review_report, text_handlers, commands) | ✅ code-complete + reviewed |
| 06 publisher | `publisher/` (authorize_once, oauth_headless, metadata_builder, youtube_uploader, quota_throttle, thumbnail_setter, ab_variants, publish, commands) | ✅ code-complete + reviewed |

CLI (auto-mounted, 15 cmds): init-db · status · costs · gen-topics · gen-script · gen-audio ·
gen-visuals · assemble · notify-review · run-bot · get-chat-id · review-report · authorize · publish · set-winner.

## Verification done (no API keys needed)
- `compileall` clean; `import ai_operator.cli` OK (auto-mounts all 5 phase cmd modules).
- **48/48 phase submodules import cleanly** (catches wrong-API-at-import; heavy deps lazy).
- Foundation runtime-tested: init-db → 9 tables; budget hard-cap rejects over-cap; state machine,
  checkpoint/idempotency, cost estimator all pass.
- Deps installed (non-torch): moviepy 2.2.1 (real; `__version__` misreports 2.1.2), Pillow 11.1.0,
  elevenlabs 2.x, python-telegram-bot 22.8, faster-whisper 1.2, google-api-python-client.

## Deep-research corrections baked in
- YouTube `containsSyntheticMedia=True` IS a real API field → compliance strategy valid.
- **Test&Compare A/B is Studio-only (no API)** → phase 06 emits variants + manual checklist + `set-winner` CLI.
- Pillow `11.1.0` (not 10.2.0); ElevenLabs `previous_request_ids` list + `with_raw_response`; whisper `base.en` CPU.
Full detail: `../260708-1548-.../reports/researcher-260708-1704-version-sensitive-api-implementation-reference-report.md`.

## Adversarial review — 7 CONFIRMED bugs fixed (+1 proactive)
1. **[CRIT]** `review/telegram_bot.py` `run_polling(read_timeout=30)` → TypeError on PTB 22.8 → dropped kwarg.
2. `content/llm_client.py` Anthropic call not try/except → stranded budget reservation → release to 0.0 on failure.
3. `content/script_generator.py` non-idempotent SCRIPTED transition → guard `if state != target`.
4. `assembler/video_builder.py` rendered-before-checkpoint bricked re-runs → tolerant resume + idempotent transition.
5. `media/tts_chunker.py` repeated-tail overlap re-spoke ~30s/video → removed overlap, rely on request-id stitching.
6. `review/review_notifier.py` + `caption.py` unescaped AI text in Markdown → Telegram 400 → send plain text.
7. `publisher/publish.py` published script.json metadata, dropping operator's DB edits → overlay DB fields.
8. (proactive) `review/review_notifier.py` non-idempotent PENDING_REVIEW re-notify → guarded.

Audit swept all `assert_transition` sites: media VOICED + publisher PUBLISHED already idempotent-guarded.

## NOT done (blocked / out of scope this pass)
- **No runtime/end-to-end test** — needs real API keys (phase 00) + heavy deps (torch/SDXL opt-in). Code is
  written for real execution, never mock, but has not produced a real video yet.
- **Phase 00** (user prerequisites) — see `docs/user-setup-checklist.md`. API Audit = 2-4wk lead, start now.
- **Phases 07-09** (scheduler/analytics, observability/deploy, validation run) — not implemented (P1 + validation).
- Not committed to git (index clean; gitignore verified to exclude .venv/data/output/.env — no secrets stageable).

## Next steps
1. User: complete `docs/user-setup-checklist.md` (submit YouTube API Audit today).
2. Once keys in `.env`: full `pip install -e .` (+ `[sdxl]` extra for local gen), then dry-run each CLI step on 1 topic.
3. Implement phases 07-09.
4. Consider a light pytest suite for the pure-logic units (chunker, state machine, cost, dedup, metadata_builder).

## Unresolved questions
- Music source (phase 04 default: YouTube Audio Library free) — confirm before first render.
- Residual (not fixed, low-risk): `review/decision_store.py` double-tap of a Telegram decision button could
  raise InvalidTransition on the 2nd tap (mitigated: buttons cleared after 1st decision) — verify during phase-05 live test.
