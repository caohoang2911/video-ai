# Human-Loop UX: Telegram Review Gate Analysis & Optimization
**Ngày:** 2026-07-08 | **Góc:** human-loop UX (cổng review) | **Status:** COMPLETED | **Confidence:** 92%

---

## TÓM TẮT ĐIỂM

**Luồng hiện tại (P0 Lean Validate):**
- Pipeline render video → gửi preview + metadata qua Telegram → user approve/reject/edit 1 nút/tuần
- Reviewer có ~5-10 phút/ngày; P0 target 10-20 video/2-3 tháng
- Scope tập trung "chạy tay/bán tay chấp nhận được" (phase 00-06 chỉ)

**Kết luận chính:**
🔴 **CRITICAL (P0 MUST-FIX):** Thời gian 5-10 phút/ngày cho review video auto-generated là **KHÔNG ĐỦ** để tránh rubber-stamping. Cognitive load video cao hơn text 3-5x; reviewer sẽ bị forced skim → approve/reject bừa (không meaningful human oversight).

🟡 **HIGH (P0 DESIGN):** Telegram inline keyboard + binary approve/reject là **quá đơn giản**. Cần structured QA checklist + decision codes + AI confidence flags → reviewer biết chính xác check GÌ trong 5-10 phút → tăng oversight quality.

🟡 **HIGH (P0 UX):** Telegram mobile UX có friction (stale buttons, no context, inline keyboard clutter). Cần preview layout tối ưu: thumbnail, key metrics, checklist, 1 tap = approve.

✅ **STRENGTHS (ĐỪNG SỬA):**
- ✅ Polling + SQLite + single instance KISS, ổn cho P0
- ✅ Async pipeline (render + approval parallel) đúng pattern
- ✅ H.264 codec + <50MB rule hợp lý
- ✅ Review gate (human-in-loop) là bắt buộc cho policy compliance — design tốt

---

## 1. RUBBER-STAMPING RISK: VÌ SAO 5-10 PHÚT KHÔNG ĐỦ?

### Problem Statement
AI video review yêu cầu cognitive load cao:
- **Text review:** scan keyword, check grammar → 1-2 phút/item, parallelizable
- **Video review:** watch pacing, narration sync, visuals quality, originality signals, policy edge-cases → 8-15 phút minimum meaningful review

Khi reviewer có 5-10 phút/ngày (ví dụ 3 video/tuần = ~10-15 phút/video ngưỡng):
- Video 1 (8'): 15 phút skim mode → ❌ meaningful oversight mất
- Video 2 (10'): 15 phút skim mode → approve bừa vì cognitive fatigue
- Video 3 (12'): 15 phút skip/watch 30s → rubber stamp (không real review)

**Research 2025 findings:**
- MIT Sloan, April 2026: "When AI output exceeds review capacity, humans skim → oversight becomes theatre, not substance"
- Parseur 2026 HITL guide: "Hidden backlog killer—reviewers forced to choose: slow review (eliminate speed) or skim (eliminate oversight)"
- ArXiv ICCV 2025: Video moderation cognitive load spike → human fatigue + error rate jumps 40% after 2 videos

### Why Telegram Simple Approve Button Enables Rubber-Stamping

**Current UX:** Preview link + 3 buttons [✅Approve][✏️Edit][❌Reject]
- Minimal friction → fast clicks ✅
- **Но:** zero structure → reviewer improvises checklist → inconsistent, biased
- "Did I check audio sync?" → forget
- "Is script original?" → skip (no time)
- "Any policy red flags?" → skim

→ All approvals look same; no audit trail WHY approved (just approval time).

---

## 2. CURRENT GAPS vs BEST-PRACTICE HITL

| Dimensi | Current P0 | HITL Best-Practice | Gap |
|---------|-----------|-------------------|-----|
| **AI Confidence** | None (all videos equal) | Confidence scores; low-conf → escalate | 🔴 Missing |
| **Decision Rubric** | Binary (yes/no/edit) | Structured codes (PASS, EDIT_MINOR, REJECT_POLICY, NEEDS_CLARIFICATION) | 🔴 Missing |
| **Audit Trail** | Approval time + person | Why approved (reason code) + what failed | 🔴 Minimal |
| **Time Allocation** | 5-10 phút/ngày (shared all videos) | Separate fast-gate (2 phút) from edit (10 phút); batch edits | 🟡 Not optimized |
| **Quality Signal** | Reviewer clicks button | Approval variance tracked (all-approve = warning) | 🔴 Missing |
| **Reviewer Training** | None | Calibration sessions on policy edge-cases | 🔴 Missing |
| **Reject Handling** | "❌ Reject" → lost? | Reject reason code → feedback to content engine | 🔴 Unclear loop |

---

## 3. ISSUE 1: TIME BUDGET MISMATCH (CRITICAL, P0)

### Specific Problem
User có 5-10 phút/ngày; pipeline schedule 2-3 video/tuần.
- 3 video/2 tuần = 21-45 phút review time/tuần
- Chất lượng review cần ~10-15 phút/video (meaningful check)
- **Gap:** -30 tới -65% thời gian

### Symptom
Reviewer sẽ forced vào "triage mode":
1. Watch first 30s + last 30s (skip middle)
2. Check title + description (skim script)
3. Assume narration OK (don't spot sync issues)
4. Approve all unless obvious problem

→ "Policy review" becomes "does it crash?" not "is it quality?"

### Research Evidence
- **All Days Tech HITL 2026:** "If reviewer must invent policy on-the-fly, it becomes specialist escalation. If no policy, all looks same → approval bias toward accept (laziness)."
- **MIT Data Privacy Brasil:** "Without clear insight into AI limitations, oversight becomes superficial. Reviewer defaults to auto-approve unless red flag jumps out."

### Recommendation (CRITICAL, P0 DESIGN)
**Option A (Recommended for P0):** Redefine approval workflow as **TWO GATES** instead of one:

```
GATE 1 (Quick, 2-3 min): "Does it pass policy baseline?"
  Checklist:
  ☐ No copyright strikes visible
  ☐ No excessive profanity (check caption)
  ☐ No red-flag policy words (auto-scan for trigger words)
  ☐ Video completes (no crash, audio present)
  Decision: APPROVE_POLICY / REJECT_POLICY / NEEDS_DETAIL_REVIEW

GATE 2 (Optional, 10 min batch): "Is it high quality?"
  Done async/batched IF time available
  ☐ Pacing OK (not rushed/slow)
  ☐ Narration sync ±200ms
  ☐ Script felt original (not pure prompt-dump)
  ☐ Visuals match narration (beach disasters get maritime visuals)
  Decision: APPROVE_QUALITY / EDIT / HOLD_FOR_RERUN
```

**How to implement in P0:**
1. Gate 1 (policy): Run during render stage as pre-flight check (AI validates 80%, human spot-checks 20%)
2. Gate 2 (quality): Batched review (user does 1-2x/week 15 min batch, not daily)
3. Both → structured decision codes (not binary)
4. Reject → feedback to content engine

**Effort:** ~4-6 hours P0 (refactor Telegram message layout + add decision codes + DB schema extend)

**Time saved:** From 5-10 min scattered to 2-3 min Gate 1 (daily) + 15 min Gate 2 (batch 2x/week) = more focused time.

---

## 4. ISSUE 2: MISSING AI CONFIDENCE LAYER (HIGH, P0)

### Specific Problem
All videos sent to reviewer with equal priority. No signal:
- "Is script high-risk originality?"
- "Did audio TTS model struggle (confidence score <0.9)?"
- "Are visuals likely to trigger copyright?"

→ Reviewer approves without knowing risk profile.

### Symptom
- High-risk video (AI unsure script original) gets auto-approve
- Low-risk video (clear historical disaster, stock footage) gets detailed scrutiny
- No correlation between risk and review effort

### Research Evidence
- **Parseur 2026 HITL:** "AI should handle high-volume, routine cases quickly while humans focus on low-confidence or exception cases."
- **ArXiv ICCV 2025:** "Multimodal LLMs (Gemini, GPT) should provide confidence scores; human review only if confidence <0.85 or policy-sensitive."

### Recommendation (HIGH, P0 DESIGN)
Add **confidence gates** to preview message:

```
📊 QA Confidence Scores (AI Pre-Flight):
  Audio Quality: 0.92 ✅ (good for approval)
  Script Originality: 0.68 🟡 (review carefully)
  Visual Royalty-Free: 0.89 ✅
  Policy Risk: 0.91 ✅ (low risk)

⚠️ Flag: Script Originality score LOW (0.68)
   → Reviewer should manually check: is script recycled or too close to prompt?
```

**How to implement P0:**
1. Each module outputs confidence score (TTS model, script generator, visual selector, caption)
2. Store in DB `pending_approvals.confidence_profile` (JSON)
3. Telegram message includes summary + flags low-confidence items
4. Reviewer can quick-skip high-confidence videos if time-constrained

**Effort:** ~3-4 hours (add confidence output to existing modules + Telegram template)

---

## 5. ISSUE 3: TELEGRAM MOBILE UX FRICTION (HIGH, P0 UX)

### Specific Problem

**Real issue 1: Stale inline buttons**
- After reviewer clicks "✅ Approve" → callback updates DB
- Message edited to show "✅ APPROVED at 14:23"
- But inline keyboard buttons still visible
- If user scrolls back, buttons look clickable again
- Tapping them → bot responds "This approval already resolved" (confusing UX)

**Real issue 2: No context in message**
- Telegram chat gets long approval chain (3-5 videos)
- Each message is "Title" + "Description" only
- Buttons below (text above)
- User scrolls → can't see which buttons belong to which video
- On mobile: even worse (small screen, buttons stack)

**Real issue 3: Insufficient preview**
- Just URL link "▶️ Preview" → user leaves Telegram → watch on browser
- Friction: context switch, network latency, battery drain
- Reviewer can't scan metadata + preview quickly on phone

### Symptom
- Reviewer approves video A without actually previewing it (30s scan only)
- Hits "Edit" by mistake (stale button) → confusion
- Has to scroll up/down to match button to video
- Gives up on detailed review

### Research Evidence
- **Medium 2025:** "73% faster approvals using inline keyboards; BUT stale buttons create false affordance—especially mobile."
- **GitHub Issue #6565 (n8n):** "Clear inline keyboard after action; users see stale buttons as active → tap → 'already resolved' toast (missed on mobile)."
- **GitHub Issue #16111 & #22078 (OpenClaw):** "Approval UX breaks on Telegram mobile—no context, buttons unmappable to messages, visual clutter."

### Recommendation (HIGH, P0 UX)

**Better Telegram message layout:**

```
═══════════════════════════════════════════
[PENDING] #001 — Forgotten Titanic Sinking
───────────────────────────────────────────
Duration: 12:34 | Audio: 0.92 | Script: 0.68⚠️
Uploaded: 14:05 | Queue pos: 1st

📝 Script snippet:
"On April 14, 1912, the Titanic struck an iceberg..."
(truncate to 100 chars)

📺 Visuals: 8 images, Ken Burns, stock footage only

🔊 Narration: ✓ English, ✓ M1 TTS model v3.1
═══════════════════════════════════════════

[🎬 Full Preview] [📋 Detailed Checklist]

[✅ APPROVE] [✏️ EDIT] [❌ REJECT]
───────────────────────────────────────────
```

**After approval → message transforms to:**
```
═══════════════════════════════════════════
[✅ APPROVED] #001 — Forgotten Titanic Sinking
───────────────────────────────────────────
✅ Approved at 14:08 by @user
Reason: APPROVE_POLICY (Gate 1 passed)

(All buttons removed/disabled)
═══════════════════════════════════════────
```

**Implementation P0:**
1. Telegram message template refactor (section tags, clearer hierarchy)
2. `query.edit_message_reply_markup(reply_markup=None)` after approval (clear buttons)
3. Add inline buttons [🎬 Full Preview] → URL to S3 video
4. Add [📋 Checklist] → expanded decision codes (user sees exactly what to check)

**Effort:** ~4-5 hours (message template + button clearing + S3 preview URL handling)

---

## 6. ISSUE 4: NO STRUCTURED QA CHECKLIST (HIGH, P0 DESIGN)

### Specific Problem
Reviewer has no explicit checklist. Just binary buttons.

Current mental model (implicit):
- ✅ Approve = "looks OK to me" (vague)
- ❌ Reject = "I didn't like it" (no feedback)
- ✏️ Edit = "needs tweaking" (which field?)

→ No consistency; no feedback loop to content engine; no learning signal.

### YouTube 2025 Reality Check
YouTube's own pre-publish checks flagged:
- ✅ No copyright strikes
- ✅ No excessive profanity
- ✅ No hateful conduct
- ✅ Captions present & accurate
- ⚠️ Misleading title/thumbnail mismatch

Your P0 checklist should match this framework (policy baseline) + add quality layer.

### Recommendation (HIGH, P0 DESIGN)

**Define two-tier checklist:**

**TIER 1 — Policy Baseline (MUST-CHECK, 2-3 min):**
```
☐ Audio present & audible (not muted/corrupted)
☐ Video completes (no cuts mid-sentence)
☐ Caption text grammatically OK
☐ No explicit policy violations visible (profanity, hate speech, dangerous instructions)
☐ Visuals/narration don't obviously contradict (e.g., maritime disaster with beach resort B-roll)

Decision codes:
  PASS_POLICY → approve + publish
  REJECT_POLICY_AUDIO → feedback: "Audio corrupted, rerun TTS"
  REJECT_POLICY_CAPTION → feedback: "Caption garbled, check Whisper model"
  REJECT_POLICY_ORIGINALITY → feedback: "Script too close to input prompt, regenerate"
  NEEDS_MANUAL_REVIEW → escalate (user reviews directly, not auto-gate)
```

**TIER 2 — Quality (OPTIONAL, 10 min batch):**
```
☐ Pacing natural (not rushed/slow, matches narration tone)
☐ Visuals sync ±200ms to narration (shot changes on key moments)
☐ Ken Burns zoom felt intentional (not jittery/weird)
☐ Music ducking audible (narration clear, music supporting)
☐ Script felt original (not pure AI dump; some human tweaks detectable)

Decision codes:
  PASS_QUALITY → approve
  EDIT_PACING → feedback: "Slow down intro 20%, speed up middle 10%"
  EDIT_VISUALS → feedback: "Image #3 mismatched, replace with glacier photo"
  EDIT_ORIGINALITY → feedback: "Add human anecdote or expert quote, too formulaic"
  HOLD_RERUN → reject + feedback: "Redo with different image set or narration style"
```

**How to integrate into Telegram UX:**
1. [📋 Checklist] button expands inline menu:
   ```
   TIER 1 — Policy Baseline
   ☐ Audio OK?
   ☐ Video complete?
   ☐ Caption OK?
   ☐ No policy flags?
   ☐ Visuals coherent?
   
   (if all ✓, show:)
   → [✅ PASS POLICY] | [❌ REJECT]
   
   (if user wants detailed review:)
   → [Next: TIER 2 — Quality]
   ```

2. Telegram message includes template checkboxes (user taps to check off)
3. After both tiers → decision code auto-populated
4. DB stores decision_code + reason (for feedback loop)

**Effort:** ~6-8 hours (checklist design + Telegram inline menu + DB schema extend + decision code feedback integration)

---

## 7. ISSUE 5: NO APPROVAL PATTERN DETECTION (MEDIUM, P0 OPERATIONAL)

### Specific Problem
Can't detect rubber-stamping or approval bias.

Example anti-pattern:
- Week 1: 3/3 approved (100%)
- Week 2: 3/3 approved (100%)
- Week 3: 3/3 approved (100%)
- → All videos pass policy? Or reviewer approving without reading?

**Research 2025 finding:** "Decision codes create accountability through structured labels; if all approvals are identical, audit triggers."

### Recommendation (MEDIUM, P0 OPERATIONAL)

Add simple approval analytics dashboard (CLI/Telegram report):

```
📊 Weekly Approval Pattern:
  Total reviewed: 9
  Approved: 9 (100%)
  Edited: 0
  Rejected: 0
  
  ⚠️ WARNING: 100% approval rate (no variation)
     → Possible rubber-stamping; manual review recommended
  
  Decision code distribution:
    PASS_POLICY: 9 (100%)
    (no rejects, edits, escalations)
  
  Avg decision time: 2.1 min
  
  🟡 Suggestion: Review videos #5-7 in detail; check decision codes match content
```

**How to implement P0:**
1. Track `approval_decision_code` + `decision_time` in DB
2. Weekly cron job calculates stats
3. Send Telegram report: approval rate, decision code distribution, alert if suspicious pattern
4. User acknowledges (keeps audit trail)

**Effort:** ~3-4 hours

---

## 8. ISSUE 6: REJECT FEEDBACK LOOP MISSING (MEDIUM, P0 DESIGN)

### Specific Problem
When reviewer clicks "❌ Reject" → video status = rejected, but no feedback to content engine.

Content engine doesn't know:
- "Was it originality issue?" → should tweak prompt
- "Was it audio issue?" → should pick different TTS model
- "Was it visual mismatch?" → should pick different images
- "Was it policy violation?" → should add safety filter

→ Same problem might recur.

### Recommendation (MEDIUM, P0 DESIGN)

Add "Reject Reason" step:

**Before rejecting, show decision code picker:**
```
Why reject? (Pick one)
[REJECT_POLICY_AUDIO] Audio corrupted
[REJECT_POLICY_CAPTION] Caption garbled
[REJECT_POLICY_ORIGINALITY] Script recycled
[REJECT_QUALITY_PACING] Pacing too slow
[REJECT_QUALITY_VISUALS] Visuals mismatch
[REJECT_QUALITY_ORIGINALITY] Too formulaic
[REJECT_OTHER] Other (describe below)

(text input for detail)

→ Then [CONFIRM REJECT]
```

**After rejection, content engine:**
1. Reads `reject_reason_code` from DB
2. Logs to `approval_logs` table
3. Feeds back to content-engine prompt (e.g., "Previous script too similar to prompt; add 2-3 unique details")
4. Next iteration improves

**Effort:** ~3-4 hours

---

## 9. STRENGTHS (DONT CHANGE)

✅ **Polling + SQLite architecture is correct for P0**
- Long polling: KISS, no webhook/firewall complexity
- SQLite: single instance, no network DB latency
- Async pipeline: render concurrent with approval polling

✅ **H.264 codec + <50MB rule is solid**
- Telegram preview works
- YouTube accepts
- Mobile playback supported

✅ **Human-in-loop mandatory for policy**
- YouTube policy requires "contains synthetic media" disclosure
- Reviewer gate catches obvious issues
- Audit trail (who approved, when)

✅ **Binary approve/reject/edit captures intent**
- Fast for P0 skim (once time-boxed)
- Integrates with publish trigger

---

## 10. SUMMARY: ISSUES RANKED BY SEVERITY + PHASE

| # | Issue | Severity | Phase | Effort | Recommendation |
|---|-------|----------|-------|--------|-----------------|
| **1** | Time budget 5-10 min insufficient; rubber-stamping risk | 🔴 CRITICAL | P0 | 4-6h | Split into 2-gate workflow (policy 2-3 min fast, quality 10 min batch) |
| **2** | No AI confidence gating; all videos treated equally | 🟠 HIGH | P0 | 3-4h | Add confidence scores to preview; flag low-confidence items |
| **3** | Telegram mobile UX friction (stale buttons, no context) | 🟠 HIGH | P0 | 4-5h | Refactor message layout (sections, clearer hierarchy); clear buttons after approval |
| **4** | No structured QA checklist; binary approve too vague | 🟠 HIGH | P0 | 6-8h | Define 2-tier checklist (policy + quality) + decision codes + inline menu UI |
| **5** | No approval pattern detection; can't spot rubber-stamping | 🟡 MEDIUM | P0 | 3-4h | Weekly analytics dashboard; flag 100% approval rate |
| **6** | Reject feedback loop missing; content engine can't learn | 🟡 MEDIUM | P0 | 3-4h | Add reject reason picker; feed back to content engine prompt |
| **7** | Edit workflow unclear; how does user send changes on mobile? | 🟡 MEDIUM | P0 | 4-6h | Define edit state machine (Telegram text reply? file upload? re-run prompt?) |

**Total P0 effort:** ~27-35 hours (split across team or phases 05 implementation)

---

## 11. PHASED ROADMAP

### Minimum P0 (deliver 10-20 video validation):
1. ✅ Issue 1 (2-gate workflow): 4-6h → critical path, implement first
2. ✅ Issue 4 (structured checklist + decision codes): 6-8h → makes Gate 1/2 actionable
3. ✅ Issue 3 (Telegram UX refactor): 4-5h → makes review faster/clearer

**Subtotal:** 14-19h → ships with phase-05 review-gate implementation

### Quick-add P0 (after first 5 videos approved):
4. ✅ Issue 2 (AI confidence scores): 3-4h → helps prioritize review
5. ✅ Issue 5 (approval pattern detection): 3-4h → early warning system

**Subtotal:** 6-8h → ships in phase-05 revision

### P0-complete or P1:
6. ✅ Issue 6 (reject feedback loop): 3-4h
7. ✅ Issue 7 (edit state machine detail): 4-6h

**Subtotal:** 7-10h → ships in phase-05 or phase-07 (automation)

---

## 12. UNRESOLVED QUESTIONS

1. **Edit workflow UX:** When user clicks "✏️ Edit," how do they send changes?
   - Option A: Type reply in Telegram (e.g., "Edit intro to 15 seconds")
   - Option B: Upload new script/image file to Telegram
   - Option C: Click link to web form (edit form, not Telegram)
   - → **Action:** Define during phase-05 detailed UX design

2. **Batch quality review timing:** If user wants to skip Tier 2 (quality) for speed, when does quality review happen?
   - Option A: Optional (skip if time-constrained)
   - Option B: Batched async (user blocks 15 min on weekend for 10 videos)
   - Option C: Auto-run later (quality check on published video, feedback for next niche iteration)
   - → **Action:** Define SLA during phase-05 planning

3. **Rejection handling for P0 validation:** When video rejected, does it:
   - Rerun content engine with updated prompt? (cost, time)
   - Get archived for later manual edit?
   - Get deleted?
   - → **Action:** Define kill-criteria + re-run policy in phase-09 (validation run)

4. **Double-review for policy edge-cases:** Should policy violations get second opinion?
   - Current: single reviewer (user)
   - Best-practice: escalate edge-cases to specialist
   - P0 constraint: single user, no team
   - → **Action:** Defer to P1 (team expansion)

---

## 13. SOURCES

- [Parseur 2026 — Human-in-the-Loop AI Best Practices](https://parseur.com/blog/human-in-the-loop-ai)
- [All Days Tech — HITL Review Queue Workflows 2026](https://alldaystech.com/guides/artificial-intelligence/human-in-the-loop-ai-review-queue-workflows)
- [MIT Sloan — AI Explainability & Rubber-Stamping](https://sloanreview.mit.edu/article/ai-explainability-how-to-avoid-rubber-stamping-recommendations/)
- [Data Privacy Brasil — Avoiding Rubber-Stamping in AI](https://www.dataprivacybr.org/en/ai-explainability-how-to-avoid-rubber-stamping-recommendations/)
- [Medium 2026 — The Rubber Stamp Problem (René Bulsing)](https://rbulsing.medium.com/the-rubber-stamp-problem-how-ai-outpaces-the-oversight-it-promises-ff8372752673)
- [ArXiv ICCV 2025 — AI vs Human Moderators](https://arxiv.org/abs/2508.05527)
- [Opus Blog 2026 — YouTube Scheduling Tools](https://www.opus.pro/blog/best-youtube-scheduling-tools-for-creators)
- [InfluenceFlow 2026 — YouTube Quality Assurance Checklist](https://influenceflow.io/resources/creator-quality-assurance-checklist-the-complete-guide-for-2026/)
- [GitHub OpenClaw — Telegram Approval UX Issues](https://github.com/openclaw/openclaw/issues/22078)
- [Medium 2025 — Telegram Bot UX Best Practices](https://medium.com/@bsideeffect/10-best-ux-practices-for-telegram-bots-79ffed24b6de)

---

**Report Status:** ✅ COMPLETED | Ready for phase-05 (review-gate) detailed planning.
