# Consolidated Brief Analysis & YAGNI Filter — P0-VALIDATE (10-20 Video / 2-3 Tháng)

**Date:** 2026-07-08  
**Context:** Lean faceless AI video operator system (YouTube documentary, Maritime Disasters, 8-15 phút)  
**Scope:** 10-20 video validate niche before scale  
**Status:** Analysis complete, categorization finalized

---

## EXECUTIVE SUMMARY

Pipeline foundation **solid** (lean scope, compliance layer, state machine, review gate). 

**3 CRITICAL BLOCKERS** (fix before video #1):
1. YouTube AI Label API `containsSyntheticMedia=true` not implemented → retroactive YPP penalty risk
2. Telegram review gate 5-10 min insufficient for "meaningful human review" standard → audit trail weak
3. Analytics loop vague "feedback to step 1" → validation metric-blind

**8 HIGH-IMPACT P0 IMPROVEMENTS** (implement weeks 1-2):
Hook + visual consistency + research depth + pacing + structured checklist + topic dedup + title A/B + Telegram UX fix enable metric collection for niche validation decision.

**Recommendation:** Fix 3 critical + 4-5 core improvements weeks 1-2, defer Shorts/posting-time/advanced optimization to week 3+ or P1 if validation signals strong early.

---

## DEDUPLICATION & CONSOLIDATION

**Briefs with overlapping findings:**
- Brief 1 + 4: Hook optimization, analytics vague
- Brief 4 + 5: Thumbnail missing, tool evaluation
- Brief 2 + 6: Telegram approval quality, audit trail
- Brief 3: Error handling, state tracking, cost guardrail

**Consolidated unique clusters:** 21 distinct issues across all briefs.

---

## CATEGORIZED FINDINGS

### MUST FIX BEFORE BUILD (7 CRITICAL ITEMS)

Block P0 pipeline start if unresolved. Policy-blocking, budget-blocking, or validation-blind.

#### 1. YouTube AI Label Disclosure API (containsSyntheticMedia)
**Why:** Chưa implement `status.containsSyntheticMedia=true` trong YouTube Data API upload. May 2026 auto-detect synthetic media → YouTube retroactively label content "undisclosed". "Non-disclosure + inauthentic" combo = faster YPP audit escalation → demonetize risk.

**Change:** Set `video_body['status']['containsSyntheticMedia'] = True` trong videos.insert() call (Python YouTube API client). Test 2-3 pilot uploads, verify label appears YouTube Studio.

**Effort:** Low (~30 min)

**Lens:** Policy survival

---

#### 2. Meaningful Human Review Gate Insufficient
**Why:** Telegram "Approve" 5-10 phút/ngày không đạt YouTube 2026 standard "meaningful human review" (holistic audit kiểm tra "unique creative fingerprint", "demonstrable editorial decisions"). Token approval = template-driven mass-produce signal → demonetize nếu YPP audit detect. MIT Sloan 2026: khi AI output exceed review capacity, humans skim → oversight thành theatre.

**Change:** Split 2-tier approval workflow:
- **Gate 1 Policy Baseline (2-3 phút):** Audio OK, video complete, caption OK, no policy flags, visuals coherent → decision codes (PASS_POLICY / REJECT_POLICY_*)
- **Gate 2 Quality (10 phút batch 1-2x/tuần):** Pacing, sync ±200ms, Ken Burns, music ducking, originality → decision codes (PASS_QUALITY / EDIT_* / HOLD_RERUN)

Structured decision codes (not binary). Tier 1 daily (user đơn giản), Tier 2 batched (dedicated time).

**Effort:** Medium (2-3 ngày)

**Lens:** Policy + UX

---

#### 3. Analytics Loop Specification Missing
**Why:** Bước 8 "đọc YouTube Analytics → feedback bước 1" quá vague. Không nêu: (a) metrics nào track (watch time? retention curve? RPM?), (b) decision rule gì (khi nào kill topic, khi nào retry?), (c) audit trail feedback. **Kết quả: P0 validation bị black-box** — biết view nhiều hay ít nhưng không hiểu tại sao, không iterate dựa signal thực.

**Change:** Design Phase 07 metrics schema:
- **Per-video track:** CTR (4-6% target), retention curve (25%/50%/75% checkpoints), watch time, subs/video ratio, RPM
- **Decision rules:**
  - CTR < 3% after 1K impressions → thumbnail regenerate + A/B test
  - Retention < 30% → pacing/hook issue, skip similar topic 2 tuần
  - RPM < $5/1K → niche saturated signal
  - Subs/video > 0.5% → topic resonates, double-down
- **Logging:** Decision trail (why picked topic X, thumbnail A won, retention dropped m3) → feed back recommendation engine Phase 02
- **Tools:** YouTube Analytics API (daily fetch, cache 24h) + local SQLite, pandas agg layer

**Effort:** Medium (2-3 ngày)

**Lens:** Validation

---

#### 4. Error Handling & Exponential Backoff Missing
**Why:** API call fail (ElevenLabs 429, YouTube timeout, Pexels error) → script crash giữa chừng, rerun = duplicate charges (không idempotent). Không retry logic = mất effort viết script, mất chi phí.

**Change:** Add try/except + exponential backoff wrapper tất cả API calls:
- ElevenLabs, YouTube, Pexels, Claude API
- Backoff: start 1s, max 32s, jitter ±10%
- ElevenLabs concurrency limit → distinguish vs rate_limit, use request queue
- YouTube ETag caching reduce quota spend
- Request queue track concurrent_limit_exceeded separately (queue not backoff)

**Effort:** Medium (3-4 ngày)

**Lens:** Tech robustness

---

#### 5. Idempotency Keys & State Tracking DB Missing
**Why:** Rerun script → duplicate uploads: trùng video file YouTube, trùng ElevenLabs charge. Pipeline không track "đã làm đến bước nào" → cảnh báo: Uber 2025 loop bug burned entire quarterly AI budget in 4 months.

**Change:** Add SQLite DB track:
- `video_id` (UUID), `topic_name`, `status`, `step_phase` (1-8), `idempotency_key`, `output_file_path`, `created_at`, `updated_at`
- Before each step check DB: if status=completed skip
- Idempotency key sent to APIs prevent duplicate charge
- On startup: read DB, if video in progress → resume from last step
- Write `{video_id}.checkpoint.json` after each step

**Effort:** Medium (3-4 ngày)

**Lens:** Tech robustness

---

#### 6. Cost Guardrail Missing
**Why:** Không có cost estimate trước run. Loop bug → burn ElevenLabs quota (Pro account ~$50-100/tháng). Precedent: automation team 2025 bug tiêu tốn $500 budget trong 3 ngày.

**Change:** Add cost estimator per-step:
- Script length → token count → ElevenLabs cost estimate (±10%)
- Set hard limit: if `estimated_cost > budget_remaining` → reject video + alert
- Config file: `MONTHLY_BUDGET=$500` (adjustable)
- Track cost per-step, accumulate to monthly total

**Effort:** Low (1 ngày)

**Lens:** Budget control

---

#### 7. Inauthentic Content Template Unaudited
**Why:** Faceless + AI voice + stock footage + templated structure (intro→topic→story→conclusion→outro) có thể trigger inauthentic detection ngay cả ≤3/tuần. Chưa audit 10-20 script → check nếu narrative structure >50% similarity = demonetize risk.

**Change:** Audit 5-10 existing + 5-10 draft script trước build:
- Analyze narrative structure %
- Diversify 3-5 patterns:
  - A: Chronological timeline
  - B: Causal chain
  - C: Perspective flip
  - D: Mystery-first
  - E: Impact-backward
- Ensure 3-4 script/10-20 video follow pattern khác nhau
- Flag nếu >50% same structure → redesign

**Effort:** Medium (1-2 ngày)

**Lens:** Policy survival

---

### IMPROVE DURING VALIDATE (13 HIGH-IMPACT ITEMS)

Do in P0 để collect validation metrics. Không block pipeline nhưng essential cho niche viability signal.

#### 1. Hook Optimization: 30-45s Pattern Interrupt + Text Overlay
**Why:** Documentary genre: 30-45s hook critical (open shocking statistic + visual mismatch, context teaser). Chưa có template → bình thường mất 30-40% viewer trong 30s. Top channels (Fascinating Horror, Mark Felton) dùng tối ưu hook → giữ 70%+.

**Change:** Bước 2 (Viết kịch bản) thêm structured hook template:
- 5s pattern interrupt: shocking statistic/visual mismatch
- 15-25s context + teaser đậm
- Text overlay 1-2 frame key claim (on-screen)
- Music dramatic sync

Ví dụ: "47 advanced warships vanished in 72 hours" (on-screen) → 10s context ("Here's what actually happened") → main narrative.

A/B test 2-3 hook styles trước release. Track: 30s retention % per variant.

**Effort:** Medium (1-2 ngày)

**Phase:** P0-validate

---

#### 2. AI Visual Consistency: SDXL + Stock Footage Aesthetic Coherence
**Why:** SDXL temporal drift (2025 research) → frame-to-frame inconsistency flickering, morphing. Stock footage = real camera. Mix → jarring visual if SDXL ảnh không carefully curated. Documentary benchmark (Fascinating Horror, Into the Shadows) dùng consistent visual language. Viewer drop retention 15-25% nếu detect "AI slop" look.

**Change:** Bước 4 tách 2 sub-streams:
- **(A) Stock b-roll (real motion, historical)** — maintain majority (Pexels/Pixabay)
- **(B) SDXL synthesis CHỈ cho maps/diagrams/historical reconstruction** (non-photorealistic style, e.g., watercolor illustrations, schematic maps)

Constraint: SDXL prompts hard-code style consistency (e.g., "hand-drawn historical map, muted 19th century colors, no realistic texture").

Test: generate 10 SDXL batch per story, grade consistency. Target: >80% coherent, reject <80%.

**Effort:** High (2-3 ngày)

**Phase:** P0-validate

---

#### 3. Research Depth & Fact-Checking: Pre-Script Gate
**Why:** Bước 1 topic choice từ seed kho có thể shallow. Top channels (Mark Felton, Fascinating Horror) meticulous research (expert interviews, archival sources). Risk: AI-generated shallow stories → credibility fail, comment section expose, drop retention + hurt channel reputation. Documentary niche = depth signal critical.

**Change:** Add Bước 1.5 (research gate) trước kịch bản:
- List ≥3 credible sources (archival databases, academic papers, expert accounts)
- Cross-verify dates/locations/names
- Identify unique angle vs existing docs
- Implement "research_depth" scoring (Low/Medium/High)
- Reject Low. Medium cần supplementary sources
- Script Phase 02 include source citations (hidden metadata, not video)
- P0 validate: add script review step — 1 external fact-checker (volunteer maritime historian)

Cost: +2-3h/video, nhưng critical avoid credibility loss.

**Effort:** Medium (1-2 ngày)

**Phase:** P0-validate

---

#### 4. Pacing Precision: Payoff Rhythm 60-90s + Shot Duration Strategy
**Why:** Best practice 2025: mỗi 60-90s cần "payoff" (surprising fact / visual climax / transition). Luồng hiện không mention → flat narrative, viewer boredom m3-5 (high dropout). Benchmark: 31.5% retention cho 5-10m video với tight pacing.

**Change:** Bước 2 (kịch bản) add pacing grid:
- Mỗi 90s mark "payoff node" (1 key fact / plot twist / visual reveal)
- 8m video = 5-6 payoff nodes
- Template: m1 (hook), m2-3 (setup, 1 payoff), m3-5 (main, 2-3 payoffs), m5-7 (climax, 1 payoff), m7-8 (outro)

Bước 5 (video assembler) enforce shot duration rules:
- Establishing: 4-6s
- Detail/reaction: 2-3s
- Montage: 1-2s per shot

Sync: narration tone + music rhythm + cut timing (Ken Burns hợp lý + hard cuts, pan tilt).

Test: edit sample 2min, review retention curve internally.

**Effort:** Medium (1-2 ngày)

**Phase:** P0-validate

---

#### 5. ElevenLabs Chunk Splitting: Natural Pacing vs Seam Artifacts
**Why:** Bước 3 "chia chunk & nối" không specify strategy. Risk: awkward splits narration (breathing, prosody break), seam clicks, unnatural pauses. ElevenLabs Turbo v2.5 tốt nhưng chỉ nếu chunk strategy đúng.

**Change:** Bước 3 protocol:
- Chunk mỗi 1-2 câu complete (15-30s audio)
- LUÔN split tại natural punctuation (full stop, colon)
- Avoid split giữa subject+verb
- Test ElevenLabs API: chunk_callback parameter (if available) để control prosody across chunks
- Golden rule: full narration 1 lần nếu tổng <5min; nếu >5min thì chunk + overlap 5-10% audio (crossfade) để avoid seam glitch

**Effort:** Low (1-2h)

**Phase:** P0-validate

---

#### 6. Topic Deduplication: Semantic Similarity Check
**Why:** Kho seed không track topic đã làm → lựa chọn ngẫu nhiên có thể lặp (e.g., 3 video cùng Titanic). Platform overhead + viewer boredom.

**Change:** Add topic_history table:
- `topic_name`, `topic_embedding` (sentence-transformer all-MiniLM-L6-v2)
- Before bước 1: compute embedding topic_candidate, compare past topics (cosine similarity ≥0.85 reject)

**Effort:** Low (2-3h)

**Phase:** P0-validate

---

#### 7. Structured Telegram Approval: Checklist + Decision Codes + Audit Trail
**Why:** Current binary "Approve/Edit/Reject" quá vague, không audit trail. YouTube YPP audit kiểm tra "clear human creative direction" — cần structured process chứng tỏ deliberate review không rubber-stamp.

**Change:** Structured approval workflow:

**TIER 1 Policy Checklist (must-check):**
- ☐ Audio present
- ☐ Video complete
- ☐ Caption OK
- ☐ No policy flags
- ☐ Visuals coherent
- Decision codes: PASS_POLICY / REJECT_POLICY_AUDIO / REJECT_POLICY_CAPTION / REJECT_POLICY_ORIGINALITY / NEEDS_MANUAL_REVIEW

**TIER 2 Quality Checklist (batch 1-2x/week):**
- ☐ Pacing natural
- ☐ Visuals sync ±200ms
- ☐ Ken Burns OK
- ☐ Music ducking clear
- ☐ Script original
- Decision codes: PASS_QUALITY / EDIT_PACING / EDIT_VISUALS / EDIT_ORIGINALITY / HOLD_RERUN

Implementation: Telegram [📋 Checklist] button → expand inline tickboxes (user tap ☐→☑️). After both tiers, auto-populate decision_code. DB store decision_code + reason + timestamp (audit trail).

**Effort:** Medium (2-3 ngày)

**Phase:** P0-validate

---

#### 8. TTS Quota Management & Backup Strategy
**Why:** ElevenLabs Starter = 30k chars/tháng. 1 video ~9-12k chars → 2.5-3 video/tháng. P0-validate target = 10-20 video/3 tháng → exceed quota khi ramp up. Fallback Edge-TTS (free) quality thấp. Backup chưa clear.

**Change:** 2-tier TTS fallback:
1. ElevenLabs Starter (chính, $10/mo)
2. OpenAI TTS-1 ($15/1M tokens, ~$0.90/video) hoặc Chatterbox (free, open-source, beat ElevenLabs blind test 63.8%)
3. Edge-TTS (cuối fallback)

Logic: try ElevenLabs → if 429/over-quota → try OpenAI/Chatterbox → if fail → Edge-TTS

Set alert **70% quota** (not 80%) để kịp thay. Test OpenAI/Chatterbox audio quality vs ElevenLabs trước P0.

**Effort:** Low (1-2h)

**Phase:** P0-validate

---

#### 9. Approval Pattern Detection & Rubber-Stamp Alert
**Why:** Khi approval rate = 100% tuần này/tuần sau → có phải policy quá thoải hay reviewer skim không đọc? Không detect = oversight thành theatre. Add weekly analytics alert nếu approve rate constant 100%.

**Change:** Weekly approval analytics (Telegram report):
- Total reviewed / Approved / Edited / Rejected
- % approval rate
- Decision code distribution
- Avg decision time per video

Alert nếu:
- Approval rate = 100% (possible rubber-stamp)
- Decision code distribution uniform (all PASS_POLICY, no variance)

User acknowledge report → audit trail saved.

**Effort:** Low (2-3h)

**Phase:** P0-validate

---

#### 10. Title A/B Test Native Support
**Why:** Phase 02 generate `title_options[3]` (3 lựa chọn). Pipeline chỉ upload 1 title, không leverage YouTube native Title A/B test (Dec 2025). Title + thumbnail combo test = 15-40% CTR uplift, nhưng 50% creators skip.

**Change:** Phase 06 integrate YouTube Data API (title mode):
- Set initial title snippet.title
- Immediately after upload, call Test & Compare API (title mode)
- Set alternate titles từ title_options[2] vs [3]
- YouTube test 1K-5K impressions, winner picked by watch time share
- Phase 07 track: which title variant won → log reason → inform Phase 02 next round

**Effort:** Low (1 ngày)

**Phase:** P0-validate

---

#### 11. Thumbnail Generation & A/B Test Integration (Hooksnap API)
**Why:** Pipeline Phase 05/06 không mention thumbnail. Thumbnail = 80% CTR decision. YouTube Test & Compare (Dec 2025) available A/B test 3 variants auto, nhưng pipeline absent. Cold-start exploit recommendation algorithm cần maximize CTR.

**Change:** Thêm module `thumbnail_generator.py`:
1. Extract 3 key frames từ video (scene cuts, high motion)
2. Overlay text (1-2 từ key dari title) + bold sans-serif
3. Color-optimize (high contrast: yellow/red/cyan trên background)
4. Output 3 variants (color schemes, text position)
5. Integrate Hooksnap API (free tier 10 credits/tháng ~ 2-3 video):
   - Auto-generate 3 on-brand thumbnails per video
   - YouTube Test & Compare: upload 3 variants, YouTube pick winner bằng watch time
   - Track: CTR prediction, variant chosen

Phase 07 log winning thumbnail schema → inform future choices.

**Benchmark:** CTR 4-6% target (cold-start baseline 2-4%), A/B test optimize +15-40%.

**Effort:** Medium (2 ngày)

**Phase:** P0-validate

---

#### 12. Telegram Mobile UX Fix: Metadata + Confidence Scores + Clear Buttons
**Why:** Stale inline buttons remain after approval (confusing). Wall of identical messages = unmappable mobile. No metadata summary = reviewer can't scan quick → approve bừa.

**Change:** Refactor Telegram message:
1. Metadata section (duration, confidence scores, script snippet, visuals count)
2. Section headers visual hierarchy (PENDING / Audio / Script / Visuals)
3. [🎬 Full Preview] button (S3 video URL, not just text link)
4. [📋 Checklist] button (expand inline menu, user tap checkboxes)
5. After approval: `edit_message_reply_markup(reply_markup=None)` → clear buttons, show "APPROVED at 14:08"
6. Message transform: before = interactive buttons, after = static "APPROVED" header

**Effort:** Medium (3-4h)

**Phase:** P0-validate

---

#### 13. Reject Reason Tracking & Feedback Loop
**Why:** Click reject → video.status=rejected, xong. Content engine không biết tại sao → same problem recur, lặp lại lỗi, waste time + resources.

**Change:** Add reject reason picker:
- Telegram message: "Why reject?" + buttons
- Options: REJECT_POLICY_AUDIO, REJECT_POLICY_CAPTION, REJECT_POLICY_ORIGINALITY, REJECT_QUALITY_PACING, REJECT_QUALITY_VISUALS, REJECT_QUALITY_ORIGINALITY, REJECT_OTHER
- If REJECT_OTHER → text input field (user describe)
- Store `reject_reason_code` + `reject_detail` DB `approval_logs`
- Content engine reads reject reason → logs feedback → next iteration tweak prompt

**Effort:** Low (2h)

**Phase:** P0-validate

---

### DEFER TO SCALE (10 ITEMS — P1+)

Nice-to-have, không ảnh hưởng P0 validation signal. Prioritize sau P0 niche validation confirm.

1. **Shorts Funnel (2-3/week)** — Optional validation learnings, accelerate discovery nhưng not essential P0. Recommend P0 test first 5 videos long-form, P1 add Shorts nếu signal strong.

2. **Posting Time Test & Optimization** — 10-20% CTR uplift measured, nhưng first collect baseline posting time data P0. P1 optimize schedule based on learned patterns.

3. **Flux schnell Evaluation** — If SDXL performance adequate (<15s/image), defer upgrade. If SDXL becomes bottleneck, swap to Flux schnell.

4. **Cloud Backup (tar+S3)** — Low risk 10-20 videos, add later. P0 keep local SQLite + checkpoint files.

5. **MoviePy Render Optimization** — If render time <45min per 10' video, defer tweaking. Performance adequate.

6. **End-Screen + Playlist + Pinned Comments** — Retention engagement layers. Add after validating watch-time signal, not P0.

7. **Gemini 3.1 Pro Cost Swap** — Save $0.02/video, negligible P0 impact. Nice-to-have efficiency improvement.

8. **Distil-whisper Evaluation** — If faster-whisper becomes bottleneck, benchmark & consider upgrade.

9. **Artlist/Epidemic Sound Upgrade** — YouTube Audio Library sufficient P0. Escalate if copyright issues or variety needed.

10. **Edit Workflow Web Form** — Text reply Telegram OK P0. Web form nice-to-have P1 UX enhancement.

---

### REJECTED OVER-ENGINEERING (10 ITEMS — Why Exclude)

Proposed but YAGNI for P0-VALIDATE single M1 instance lean scope:

1. **Full Observability Suite (Prometheus/Datadog/Grafana)** — Overkill P0: SQLite + Telegram logging sufficient single instance. Defer to P1 when multi-region.

2. **Distributed Task Queue (Celery/RQ)** — Single M1 local sequential render adequate, no concurrent job queue needed P0.

3. **Advanced Speaker Diarization** — Documentary solo narrator, unnecessary. Add P1 if multi-narrator format.

4. **Complex LLM Prompt Engineering (RAG, Fine-Tuning)** — Seed topics + varied templates sufficient P0. RAG/fine-tune expensive iteration, skip.

5. **Asset Governance Platform** — Simple SQLite license track adequate. Defer formal DAM to P1+.

6. **Custom A/B Test Framework (Statistical Testing)** — YouTube native Test & Compare sufficient. No custom statistical framework needed P0.

7. **Real-Time Analytics Dashboard** — Weekly Telegram report adequate P0. Defer live dashboard to P1.

8. **Multi-Language Support** — English-only P0, scale to other languages P1 after niche validated.

9. **Advanced Caption NLP (Sentiment, Topic Extraction)** — Faster-whisper + simple search adequate. Defer to P1.

10. **Kubernetes Deployment** — Single M1 local execution, no Kubernetes P0. Scale infrastructure to K8s only if multi-region P1+.

---

## TOP TOOL SWAPS (Only if Truly Warranted)

**Current stack solid**, no forced swaps. Recommended additions (not swaps):

- **Hooksnap API** (new tool) for thumbnail generation + A/B test integration → free tier adequate P0
- **OpenAI TTS-1 or Chatterbox** (new fallback) for ElevenLabs backup → test both, recommend OpenAI first
- **Flux schnell benchmark** vs SDXL (not swap yet, evaluate) → keep both, select winner empirically

**No tool deletions warranted.** Stack sufficient: MoviePy 2.x, ElevenLabs, Pexels/Pixabay, local SDXL, Faster-whisper, YouTube API.

---

## UNRESOLVED QUESTIONS

1. **Rubber-stamp rate threshold:** What approval % is acceptable? (e.g., if >95% consistent, escalate audit?) No baseline specified.

2. **Shorts strategy for P0:** Include Shorts extraction 3/week to validate hook + thumbnail appeal in vertical format, or defer to P1?

3. **Niche validation exit criteria:** When is P0 "validated" enough to scale P1? (e.g., RPM>$5, retention >50%, sub growth >0.5%/video?) Not defined.

4. **Inauthentic detection escalation:** If early inauthentic flag → retry with narrative diversity or pivot niche entirely? Recovery strategy missing.

5. **Confidence score weightage:** How heavily should low confidence (<0.75) items influence review decision? (Block or just flag?) Threshold undefined.

---

## IMPLEMENTATION ROADMAP (RECOMMEND ORDER)

**Week 1 (CRITICAL BLOCKERS):**
1. YouTube AI Label API implementation (30 min)
2. Cost guardrail module (1 day)
3. Error handling + exponential backoff (3-4 days)
4. Idempotency keys + state tracking DB (3-4 days)

**Week 2-3 (HIGH-IMPACT P0 IMPROVEMENTS):**
5. Analytics loop specification + Phase 07 metrics (2-3 days)
6. Meaningful review gate + structured checklist (2-3 days)
7. Hook optimization template + Phase 02 updates (1-2 days)
8. Topic deduplication semantic check (2-3 hours)
9. Thumbnail generation + Hooksnap integration (2 days)

**Week 3-4 (REMAINING P0 VALIDATION):**
10. Visual consistency strategy + SDXL segmentation (2-3 days)
11. Research depth fact-checking gate (1-2 days)
12. Pacing precision + shot duration rules (1-2 days)
13. ElevenLabs chunk splitting protocol (1-2 hours)
14. TTS backup strategy testing (2-3 hours)
15. Telegram mobile UX fixes (3-4 hours)
16. Approval pattern detection + weekly alerts (2-3 hours)
17. Reject reason tracking + feedback loop (2 hours)

**Total effort:** ~30-35 days (6-7 weeks agile, with P0 video production concurrent).

---

## COMPLIANCE SUMMARY

**Policy-Safe Stack:**
✅ AI label disclosure (`containsSyntheticMedia=true`)  
✅ Meaningful human review (structured 2-tier gate)  
✅ Royalty-free assets (Pexels/Pixabay CC0)  
✅ Rate limit compliance (≤3 video/tuần)  
✅ Editorial audit trail (decision codes + timestamp logs)  
✅ Inauthentic defense (narrative diversity audit, fact-checking gate)

**YouTube 2026 Ready:**
✅ AI content auto-labeling integration  
✅ Title + Thumbnail native A/B test support  
✅ Analytics loop for retention feedback  
✅ No synthetic media undisclosed  
✅ Educational documentary niche (EDSA exception candidate)

---

**Report Complete.** Ready for Phase 00 implementation planning.
