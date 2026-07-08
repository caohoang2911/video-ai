# Research Report: Rủi ro nền tảng YouTube (ban/flag) & cách improve dự án

**Ngày:** 2026-07-08 17:44 · **Scope:** faceless AI documentary (Forgotten Maritime Disasters, EN, 8-15') · **Nguồn:** 5 WebSearch, tất cả 2026.

## Executive Summary

YouTube **KHÔNG cấm faceless/AI**. Cấm là **"inauthentic content"** (đổi tên từ "repetitious" 15/07/2025): video mass-produced, template-driven, **AI voice + slideshow ảnh tĩnh/stock generic, KHÔNG có góc nhìn/nhận định riêng**. Tháng 1/2026: **16 kênh bị xoá** (4.7B views, 35M subs, ~$10M/năm doanh thu bốc hơi). Escalation: cảnh báo → treo 90 ngày → xoá vĩnh viễn khỏi YPP; **kênh volume cao có thể bị xoá thẳng không báo trước**.

Dự án đã phòng đúng phần lớn (human review 2-tầng, `containsSyntheticMedia`, royalty-free, ≤3/tuần, pattern diversity, research gate, payoff quality gate, Ken Burns motion). **Nhưng research lộ 1 gap CRITICAL chưa ai bắt: TTS fallback chain đa-provider (ElevenLabs→OpenAI→Chatterbox→Edge) tạo GIỌNG KHÁC NHAU mỗi video → vừa vi phạm "consistent unique voice identity" vừa trông templated/inauthentic.** Đây là improvement quan trọng nhất.

## Bối cảnh rủi ro (2026, đã verify)

| Sự kiện | Chi tiết |
|---|---|
| Policy đổi tên | 15/07/2025: "repetitious" → **"inauthentic content"** = thiếu "genuine human creativity" |
| Enforcement wave | 01/2026: 16 kênh xoá, 4.7B views, ~$10M/năm |
| Auto-detection | 05/2026: YouTube tự nhận synthetic voice/deepfake/photorealistic AI **kể cả không khai báo** → auto-label |
| Escalation | 3-strike: warning → treo 90 ngày → xoá YPP; **volume cao bỏ qua bước, xoá thẳng** |
| Ví dụ bị flag | **StoriezTold**: AI-narrated animal content, cùng format voiceover+slideshow, khác title → dính filter |

## Cái GIẾT kênh (tránh tuyệt đối)

1. AI voice đọc trên **ảnh tĩnh slideshow / stock generic** → không góc nhìn.
2. **Template-clone**: mọi video "look/sound/move" giống nhau.
3. Narration synthetic trên clip bên thứ 3 **không editorial judgment**.
4. **Verbatim text-to-speech** (đọc nguyên văn bài scrape) + stock slideshow.
5. Volume cao + lặp mẫu.

## Cái SỐNG (research đồng thuận)

- **Substantial human transformation**: script tự viết, **nhận định/"hot take"/góc nhìn riêng máy không tổng hợp được**, custom animation/pacing.
- **Giọng nhất quán, độc nhất** (clone/custom voice ID) — **KHÔNG dùng default voice ai cũng xài**.
- **Motion b-roll** thay ảnh tĩnh.
- **Brand character nhất quán** (với faceless = narrator voice + intro/outro/branding).
- **Chất > lượng**: nhiều kênh <20 video dài → 100k subs.
- **Luôn toggle** `Altered/synthetic content` — **disclosure KHÔNG giảm reach/tiền**; chỉ UNdisclosed mới bị demonetize.

## EDSA exception = phao cứu sinh dự án

Documentary/educational được miễn NẾU **nêu basic facts trong chính audio/imagery**: who/what/when/where/why. Maritime disaster = ứng viên EDSA mạnh. → narration PHẢI nói rõ nạn nhân/tàu/năm/địa điểm/nguyên nhân (không chỉ ở title/desc).

## Gap Analysis: dự án vs rủi ro

| Rủi ro | Dự án đã có? | Hành động |
|---|---|---|
| Mass-produced/template | ✅ pattern diversity + payoff gate + ≤3/tuần | Giữ |
| AI không disclose | ✅ `containsSyntheticMedia=true` (phase 01/06) | Giữ |
| Ảnh tĩnh slop | 🟡 stock b-roll chủ đạo + Ken Burns | **Ép motion b-roll ≥ ảnh tĩnh; stills phụ** |
| **Giọng inconsistent (fallback chain)** | ❌ **4 provider → giọng đổi mỗi video** | **🔴 FIX: 1 giọng ElevenLabs cố định (custom/clone); fallback CHỈ Edge khi khẩn, đánh dấu re-voice khi quota về** |
| Default AI voice | 🟡 dùng voice ElevenLabs mặc định | **Chọn/clone 1 voice ID độc nhất, khoá vào `.env`** |
| Thiếu góc nhìn riêng | 🟡 có "angle" | **Nâng "angle" = luận điểm/POV diễn giải, không chỉ kể fact** |
| EDSA facts trong video | 🟡 research gate (facts ở metadata) | **Review gate check: who/what/when/where/why NÓI trong narration** |
| ElevenLabs license | ⚠️ Starter $5 (paid) | **Verify commercial license phủ YouTube monetized; Chatterbox/Edge check ToS thương mại** |
| Volume → skip-to-ban | ✅ ≤3/tuần | Giữ thấp |

## Improvements (ranked, actionable)

### 🔴 P0-1: Khoá 1 giọng nhất quán (phase 03) — QUAN TRỌNG NHẤT
- **Vấn đề:** fallback chain ElevenLabs→OpenAI→Chatterbox→Edge = giọng khác nhau giữa/trong video → inauthentic + phá brand voice.
- **Fix:** 1 ElevenLabs voice ID cố định (ưu tiên custom/clone → độc nhất). Fallback CHỈ khi hết quota, **đánh dấu `needs_revoice`** để voice lại bằng giọng chuẩn khi quota reset (đừng publish giọng lạ). Trong 1 video TUYỆT ĐỐI không trộn 2 provider.

### 🟠 P0-2: Motion-first visual (phase 03/04)
- Ép **stock b-roll motion ≥ 60% thời lượng**; ảnh tĩnh Ken Burns chỉ khi không có footage. Giảm "slideshow" signature.

### 🟠 P0-3: Angle = luận điểm, không phải tóm tắt (phase 02)
- `angle` field phải là **POV diễn giải** ("vì sao thảm hoạ này bị che giấu / bài học bị lãng quên"), review gate reject nếu chỉ kể lại fact trung tính.

### 🟡 P0-4: EDSA checklist ở review gate (phase 05)
- Thêm tickbox: narration có nêu **who/what/when/where/why** trong audio? (không chỉ title/desc) → củng cố EDSA claim.

### 🟡 P1-5: Verify license TTS provider
- ElevenLabs Starter: xác nhận commercial-use cho monetized YT. Chatterbox/Edge-TTS: check ToS dùng thương mại trước khi để trong chain.

## Điểm dự án đã LÀM ĐÚNG (không sửa)
Review gate 2-tầng + decision log (= "meaningful human review"), `containsSyntheticMedia`, royalty-free CC0, ≤3/tuần, pattern diversity guard, research gate ≥3 nguồn, payoff `surprise_score` gate, niche maritime = EDSA-friendly, ElevenLabs (không dùng free tier).

## Resources & References
- [YouTube Inauthentic Content Policy: AI Enforcement Wave 2026 – Flocker](https://flocker.tv/posts/youtube-inauthentic-content-ai-enforcement/)
- [YouTube's AI content crackdown 2026 – ScaleLab](https://scalelab.com/en/why-youtube-is-cracking-down-on-ai-generated-content-in-2026)
- [YouTube's New Policy Just Killed Faceless AI Channels – invideo](https://invideo.io/blog/youtube-kills-ai-faceless-channels/)
- [Faceless Creators Take a Hit – Hollywood Reporter](https://www.hollywoodreporter.com/business/digital/faceless-creators-youtube-ai-damage-1236617586/)
- [How we're helping creators disclose synthetic content – YouTube Blog](https://blog.youtube/news-and-events/disclosing-ai-generated-content/)
- [EDSA content evaluation – YouTube Help](https://support.google.com/youtube/answer/6345162?hl=en)
- [YouTube Reused Content Policy 2026 – vidIQ](https://vidiq.com/blog/post/youtube-reused-content-policy-guide/)
- [Is ElevenLabs Safe for YouTube – AI Agency Global](https://aiagencyglobal.com/is-elevenlabs-safe-for-youtube-adsense-and-copyright-compliance-guide/)
- [YouTube AI Content Monetization Policy 2026 – LastPlayDistro](https://lastplaydistro.com/blog/youtube-social-media-ai-content-monetization-policy-2026)
- [Why YouTube suspended thousands of AI channels – MilX](https://milx.app/en/news/why-youtube-just-suspended-thousands-of-ai-channels-and-how-to-protect-yours)

## Unresolved Questions
1. ElevenLabs Starter ($5) có phủ commercial-use cho YouTube monetized không? (đọc ToS mục license — chưa verify empirical).
2. Edge-TTS (Microsoft) dùng thương mại monetized có hợp lệ không? Chatterbox license? — cần đọc ToS trước khi giữ trong fallback chain.
3. Auto-detection 05/2026 có flag ảnh SDXL (bản đồ/tàu phi-thực) không, hay chỉ photorealistic người? (red-team report cũ cũng để ngỏ).
