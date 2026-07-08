# Policy-Survival & Monetize Audit Report
**Gọi angle**: YouTube YPP Compliance, AI Content Disclosure, Content ID Risk, Editorial Value Threshold  
**Ngày**: 2026-07-08  
**Scope**: P0-Validate (10-20 video/2-3 tháng) trước scale.

---

## Summary: Nền tảng tốt, 3 lỗ hổng critical

Pipeline có compliance roadmap rõ (review gate, AI label, royalty-free, ≤3/tuần), nhưng **POLICY-SURVIVAL phát hiện 3 lỗ hổng tầm critical**:

### 1. "Meaningful Human Review" Gap — CRITICAL
- **Issue**: Cú bấp Telegram "Approve" 5-10 phút/video KHÔNG thỏa YouTube 2026 standard.
- **YouTube Requirement**: Audit holistically kiểm tra "unique creative fingerprint", "demonstrable editorial decisions", "original perspective". Documentary niche có EDSA exception nhưng yêu cầu "context in audio/imagery" rõ ràng (không chỉ title/description).
- **Risk**: Chỉ token approve/reject sẽ bị interpret là "template-driven mass-produced" → demonetize hoặc channel suspension khi apply YPP.
- **Why critical**: YouTube January 2026 removed 4.7B views từ 16 channels dùng faceless + AI voice + stock footage → nếu approval gate không chứng tỏ human editorial judgment, vẫn bị classify "AI slop".

### 2. AI Label Disclosure API Setup Incomplete — CRITICAL
- **Issue**: Pipeline chưa implement `status.containsSyntheticMedia=true` khi upload via YouTube Data API.
- **YouTube Policy** (May 2026): Auto-detect undisclosed AI content → retroactively label (not punitive, informational). Nếu không disclose qua API, YouTube auto-detect synthetic media → flag channel.
- **Risk**: "Non-disclosure + inauthentic content" combo trigger audit faster. Missing API setup = compliance debt.
- **Why critical**: Spec nói "set nhãn AI qua API" nhưng code không implement → fail policy requirement at upload.

### 3. Inauthentic Content Template Risk (Unaudited) — CRITICAL
- **Issue**: Faceless format + AI voice + stock footage + templated structure (intro → topic → story → conclusion → outro) có thể trigger inauthentic detection ngay cả khi ≤3/tuần.
- **YouTube Policy**: Nếu video "looks templated with little variation" → demonetize. Variation không phải chỉ title/thumbnail mà "detectable human creative direction" (pacing, shot-list, narrative angle).
- **Risk**: Chưa audit 10-20 script candidates → không biết template risk level.
- **Why critical**: P0 validate phase là lúc để phát hiện pattern risk. Nếu 10/20 video bị reject do template, mất 2-3 tháng.

---

## Strengths (đã tốt, KHÔNG sửa)

✅ **Compliance Roadmap Clear**: Review gate (token exist), AI label toggle (intent clear), royalty-free verification (Pexels/Pixabay CC0), upload cap (≤3/tuần).

✅ **Documentary Niche Advantage**: Maritime Disasters = educational/historical → EDSA exception candidate. YouTube treat documentary khác AI slop nếu editorial value rõ ràng. Research-based historical content ít bị confuse với "mass-produced slop".

✅ **Official Tools**: ElevenLabs (reputable, AI fingerprinting for voice protection), Pexels/Pixabay (CC0, no Copyright ID risk), MoviePy/FFmpeg (standard stack), YouTube Data API (official).

✅ **Local Production Control**: Apple M1 Max 64GB, local SDXL/Flux → limited batch size, reduces "scale-without-judgment" risk. Không mass-produce 100+ video/tuần.

✅ **Asset Royalty-Free Verified**: All stock from Pexels/Pixabay (CC0) → no Content ID claims on footage. AI images (SDXL ship, old maps) low-risk (non-photorealistic of people).

---

## Improvements (Priority: P0-Validate)

| # | Issue | Recommendation | Severity | Effort | Phase |
|---|-------|-----------------|----------|--------|-------|
| **1** | "Meaningful Human Review" gap: 5-10 min Telegram approve insufficient | Restructure review gate from token-only → **checklist-based + decision log**. Minimum review 15-20 min per video. Checklist: ① script originality (vs source material), ② research notes (cite 3+ sources), ③ editorial decisions (shot-list customization, pacing rationale), ④ unique narrative angle (this version's POV vs generic maritime disaster), ⑤ editing proof (custom animations, transitions, not template cuts). Save decision log (approval timestamp, reviewer notes, checklist scores) for YPP audit trail. | Critical | Medium | P0-Validate |
| **2** | AI Label API setup missing: `containsSyntheticMedia` not implemented | Implement in YouTube upload code: set `status.containsSyntheticMedia=true` in `videos.insert()` call when uploading (Python: `video_body['status']['containsSyntheticMedia'] = True`). Test on 2-3 pilot videos first, verify label appears in YouTube Studio before scaling. Add to pre-flight checklist: "AI label disclosure: ☐ set". | Critical | Low | P0-Validate |
| **3** | Inauthentic content template risk unaudited: no script structure diversity analysis | Audit 5-10 existing scripts + 5-10 draft scripts: analyze narrative structure (intro %, topic intro %, main story %, conclusion %). **Diversify 3-5 structure patterns**: (A) chronological (shipwreck timeline), (B) causal chain (why disaster happened), (C) perspective flip (survivor account), (D) mystery-first (puzzle reveal), (E) impact-backward (legacy first). Ensure 3-4 scripts follow different patterns in 10-20 video plan. Flag if >50% scripts use same structure → redesign. | Critical | Medium | P0-Validate |
| **4** | Editorial context not documented: Claude research + script not attributed, no audit trail | Mỗi video: document editorial process (GitHub notes or markdown file): ① research sources (URL + relevance), ② script drafts (original vs final, changes made), ③ voiceover pacing notes, ④ shot-list justification (why this footage, not generic stock). In video description: add "Research by [sources], Scripted & Edited by [creator], AI-assisted production (voiceover: ElevenLabs, images: SDXL)." Disclosure builds "clear human direction" narrative for YPP audit. | High | Low | P0-Validate |
| **5** | Content ID risk on voice + stock music not tested: ElevenLabs + stock music combo unknown | Pre-test 2-3 pilot videos: upload to YouTube unlisted, monitor Content ID dashboard 48 hours for claims (voice, music). Document ElevenLabs voice ID (model, custom training), verify no copyright flags. If stock music from Pexels, verify Audio Library URL in description. If 0 claims on 3 pilots → document as "green path", scale. If any claims → adjust voice model or music source. | High | Low | P0-Validate |
| **6** | YPP audit strategy missing: no pre-appeal documentation plan | Before YPP application (estimated month 2-3 of pipeline): prepare audit doc ① "Editorial Process & Original Value" (explain research-to-script workflow, show decision logs), ② "Content Variation Analysis" (script structure diversity matrix, upload frequency graph), ③ "Compliance Evidence" (AI labels set, royalty-free verification, research citations). Share with mock YPP reviewer (peer or advisor) 1 week before apply. If feedback critical → revise before submit. | High | Medium | P1-Scale (before YPP apply) |
| **7** | Telegram approval gate UX doesn't surface editorial review burden: creator may approve too fast | Add Telegram message format: instead of "Approve [video title]", send **structured message** with: ① checklist scores (originality %, research sources count, unique angle description), ② time spent (15+ min target), ③ concerns if any. Require creator to reply with specific checkbox confirmations ("✓ originality verified", "✓ 3+ sources cited", "✓ unique angle clear"). Adds 3-5 min overhead but forces deliberate review, creates YPP audit trail. | Medium | Low | P0-Validate |
| **8** | Retrofit risk: no retroactive disclosure for videos uploaded before May 2026 auto-detect | If pipeline already uploaded 1-5 videos (estimate?), go back to YouTube Studio for each → manually set "Altered or synthetic content" toggle if not already set. YouTube will NOT penalize (labels are informational), but retroactive setup prevents "non-disclosure" flag in YPP audit. Action: **audit past videos NOW, set labels retroactively**. | Medium | Low | P0-Validate |

---

## Unresolved Questions

1. **Telegram approval gate + enhanced checklist**: Even with 15-20 min review + decision log, does YouTube YPP audit treat this as "meaningful human supervision" or still flag as template-driven? (Risk: YouTube may require in-person review or live creator commentary, not async approval.)

2. **ElevenLabs voice + Content ID**: Has any creator reported Content ID claims on ElevenLabs-voiced content? Precedent? ElevenLabs watermark supposedly protects, but unknown if YouTube Content ID triggers on similar-sounding voices.

3. **Documentary niche exception**: Does maritime disaster / historical documentary get lighter YPP scrutiny or EDSA exception faster than general faceless channels? Or reviewed same as AI slop?

4. **"Significant photorealistic AI use" detection**: Does YouTube's May 2026 auto-detection flag SDXL-generated ship images + old maps, or only modern photorealistic people/faces? (Risk: if AI images auto-flagged, may need to disable SDXL, use only stock photos.)

5. **Inauthentic content + upload cap interaction**: ≤3 video/week is compliant, but if all 3 follow same narrative structure (e.g., all chronological), does YouTube's system flag as "low variation even under frequency cap"? Unclear if pattern-matching is per-video or per-batch.

6. **YPP "holistic review" timeline**: 30-day standard, but for faceless AI content, does YouTube escalate to manual review (60+ days)? If delayed, does approval rate drop?

---

## Compliance Risk Roadmap (Next Steps)

**Immediate (Day 1-2)**:
1. Implement `containsSyntheticMedia=true` in upload code + test on 1 pilot video.
2. Audit past videos (if any) → retroactively set AI label in Studio.
3. Draft review checklist template for Telegram gate.

**Short-term (Week 1-2)**:
4. Audit 10 script drafts for template risk → redesign top 3 risky scripts to different structure.
5. Pre-test 2-3 pilots: monitor Content ID for 48h post-upload.
6. Document editorial process (research sources, script iterations, pacing notes) for first 3-5 videos.

**Medium-term (Week 3-8, during 10-20 video produce)**:
7. Implement enhanced Telegram checklist review gate → track decision logs.
8. Monthly compliance dashboard: upload count, topic diversity, Content ID status, YPP readiness score.

**Pre-YPP (Month 2, before apply)**:
9. Compile YPP audit doc: editorial process, variation analysis, compliance evidence.
10. Mock review with peer or advisor; revise if critical feedback.
11. Submit YPP application with audit doc attached (optional but helps).

---

## Sources

- [YouTube's AI content crackdown in 2026: What changed, who is at risk, how to adapt – ScaleLab](https://scalelab.com/en/why-youtube-is-cracking-down-on-ai-generated-content-in-2026)
- [YouTube Inauthentic Content Policy: AI Enforcement Wave 2026 - Flocker](https://flocker.tv/posts/youtube-inauthentic-content-ai-enforcement/)
- [Improving AI labels for viewers and creators - YouTube Blog](https://blog.youtube/news-and-events/improving-ai-labels-viewers-creators/)
- [YouTube Now Auto-Labels AI Videos: What Every Content Creator Needs to Know in 2026 - Memeburn](https://memeburn.com/youtube-now-auto-labels-ai-videos/)
- [YouTube AI Monetization Policy 2026 — Rules, Disclosure, Tips - Vexub](https://vexub.com/blog/ai-generated-video-monetization-policies)
- [YouTube monetization requirements 2026 – MilX](https://milx.app/en/trends/youtube-monetization-requirements-for-2026)
- [YouTube Partner Program: Requirements and How to Join in 2026 - VidIQ](https://vidiq.com/blog/post/youtube-partner-program-guide/)
- [YouTube Content ID & AI Music Policy 2026 Explained - LastPlayDistro](https://lastplaydistro.com/blog/youtube-content-id-ai-generated-music-policy-2026-what-creators-must-know)
- [How YouTube evaluates Educational, Documentary, Scientific & Artistic (EDSA) content - YouTube Help](https://support.google.com/youtube/answer/6345162)
- [A look at how we treat educational, documentary, scientific, and artistic content on YouTube - YouTube Blog](https://blog.youtube/inside-youtube/look-how-we-treat-educational-documentary-scientific-and-artistic-content-youtube/)
- [YouTube will now automatically label AI videos | TechCrunch](https://techcrunch.com/2026/05/27/youtube-will-now-automatically-label-ai-videos/)
- [Disclosing use of GenAI content - YouTube Help](https://support.google.com/youtube/answer/14328491?hl=en&co=GENIE.Platform%3DAndroid)
- [AI-generated YouTube content to get 'more visible' disclosure label - 9to5Google](https://9to5google.com/2026/05/27/youtube-updating-ai-content-labels/)
- [Videos | YouTube Data API - Google for Developers](https://developers.google.com/youtube/v3/docs/videos)
- [YouTube AI Monetization Policy 2026 Explained - LastPlayDistro](https://lastplaydistro.com/blog/youtube-social-media-ai-content-monetization-policy-2026)
- [YouTube Monetization with AI Content: What's Allowed and What Gets You Demonetized in 2026 - Miraflow](https://miraflow.ai/blog/youtube-monetization-ai-content-2026-allowed-demonetized)
- [ElevenLabs Review 2026: YouTube-Tested + Best Voices - Nerdynav](https://nerdynav.com/elevenlabs-review/)
