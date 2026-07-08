# Phase 00 — Prerequisites (User Setup)

## Context Links
- Overview: [plan.md](plan.md)
- Design doc: `plans/reports/brainstorm-summary-260708-1548-lean-faceless-ai-video-money-system-report.md`
- Blockers cho: phase 06 (YouTube publisher cần API audit + verified account), toàn bộ pipeline cần API keys.

## Overview
- **Priority:** P0 (BLOCKER tuyệt đối — chỉ NGƯỜI DÙNG làm được, không code thay được)
- **Status:** pending
- **Description:** Checklist tài khoản, xác minh, API keys, ngân sách, hạ tầng mà user phải hoàn tất trước/song song với dev. Nhiều mục có **lead-time dài** (API audit 2-4 tuần, kênh cần lịch sử) nên phải khởi động NGAY ngày 1.

## Key Insights
- **API Audit là đường găng dài nhất:** project Google Cloud tạo sau 28/07/2020 mà **chưa audit** → video upload bị **khoá private-only**, không set public/unlisted được. Submit audit ngay, chờ 2-4 tuần. Không có workaround.
- **Custom thumbnail cần Google Account xác minh SĐT** (không cần điều kiện sub/view). Verify sớm.
- **Refresh token hết hạn nếu 6 tháng không dùng** → phase 07 có cron keep-alive; nhưng user phải tạo OAuth client + consent lần đầu.
- **YPP (bật tiền)** cần 1.000 subs + 4.000 giờ xem (hoặc điều kiện Shorts) — KHÔNG phải blocker để upload; là mục tiêu P1. Vẫn nên bật AdSense sẵn.

## Requirements
Functional:
1. 1 Google Account (nên tài khoản riêng cho dự án), verify SĐT.
2. 1 YouTube channel (brand account) đúng niche + tên/branding.
3. Google Cloud project + YouTube Data API v3 + YouTube Analytics API enabled + OAuth consent + **API Audit submitted**.
4. API keys: ElevenLabs, Anthropic (và/hoặc Gemini), Pexels, Pixabay, (tuỳ chọn) fal.ai.
5. Telegram bot token (BotFather) + chat_id của user.
6. Ngân sách thanh toán gắn ElevenLabs (Starter) + card dự phòng cloud.
7. Hạ tầng: máy dev (M1 Max 64GB đã có) cho P0; quyết định deploy target ở P1.

Non-functional: bảo mật keys (không commit), bật 2FA Google, dùng email riêng dự án.

## Architecture
User cung cấp → dev nạp vào `.env` (phase 01). Không có code ở phase này; output là **file `secrets-checklist.md`** user tick + `.env` được điền.

## Related Code Files
- Create: `docs/user-setup-checklist.md` (bản in ra cho user tick).
- Modify: none.
- Delete: none.

## Implementation Steps (user thực hiện, dev hỗ trợ)
1. **Google Account:** tạo/chọn account dự án → verify SĐT tại myaccount.google.com (bật 2FA).
2. **YouTube channel:** tạo brand channel, đặt tên/handle/niche, avatar + banner (có thể tạm).
3. **Google Cloud Console:** tạo project → APIs & Services → Enable **YouTube Data API v3** + **YouTube Analytics API**.
4. **OAuth consent screen:** External, thêm scope `youtube.upload`, `youtube`, `yt-analytics.readonly`; thêm chính user làm test user.
5. **OAuth Client ID (Desktop app):** tải `client_secret.json`; chạy flow consent 1 lần (script phase 06) để lấy **refresh_token** → cất vào `.env`.
6. **Submit API Audit:** APIs & Services → YouTube Data API → Audit form (mô tả app: personal semi-auto uploader). Ghi ngày submit; theo dõi email (2-4 tuần).
7. **ElevenLabs:** đăng ký, mua **Starter** (~$5/mo, 30k chars), tạo API key. Chọn voice narration (gợi ý giọng BBC nam trầm; lưu `voice_id`).
8. **Anthropic:** tạo API key (Claude). (Tuỳ chọn Gemini key làm fallback rẻ.)
9. **Pexels + Pixabay:** đăng ký dev, lấy API key mỗi bên.
10. **(Tuỳ chọn) fal.ai:** tạo key nếu muốn cloud fallback ($0.025/img). P0 có thể bỏ qua (dùng local SDXL).
11. **Telegram:** chat @BotFather → `/newbot` → lấy token; nhắn bot 1 câu rồi lấy `chat_id` (script phase 05 in ra, hoặc dùng @userinfobot).
12. **Điền `.env`** (phase 01 tạo `.env.example`) đầy đủ keys. **Không commit.**
13. **Ngân sách:** xác nhận runway (design doc khuyến nghị $4-5K/1-2 năm); P0 đốt ~$0-30/tháng.

## Todo List
- [ ] Google Account + verify SĐT + 2FA
- [ ] YouTube brand channel + branding
- [ ] GCP project + enable Data API v3 + Analytics API
- [ ] OAuth consent + Desktop client_secret.json
- [ ] Refresh token lấy được (sau khi có script phase 06)
- [ ] **API Audit submitted** (ghi ngày: ________)
- [ ] ElevenLabs Starter + voice_id
- [ ] Anthropic key (+ Gemini fallback tuỳ chọn)
- [ ] Pexels key + Pixabay key
- [ ] Telegram bot token + chat_id
- [ ] `.env` điền đầy đủ, verify không nằm trong git
- [ ] Ngân sách/runway xác nhận

## Success Criteria
- `.env` có đủ mọi key, `python -c "import os,dotenv; dotenv.load_dotenv(); print(all(os.getenv(k) for k in [...]))"` trả True.
- API Audit đã submit (đang chờ hoặc approved).
- Google account verified (thử `thumbnails.set()` không lỗi permission — kiểm ở phase 06).

## Risk Assessment
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| API Audit bị từ chối/chậm | Medium | High | Submit ngay ngày 1; mô tả rõ "personal, review-gated, AI-labeled"; trong lúc chờ dev vẫn build phase 01-05 (không cần audit). Video test để private. |
| Account chưa verify → thumbnail fail | Medium | Medium | Verify SĐT sớm; nếu chưa, publisher tạm bỏ thumbnail (không block upload). |
| Refresh token lộ/ hết hạn | Low | High | Cất trong `.env` (gitignored); cron keep-alive (phase 07). |
| Chọn sai voice → phải re-gen | Low | Low | A/B 2-3 giọng trên 1 đoạn mẫu trước khi khoá. |

## Security Considerations
- Không bao giờ commit `.env`, `client_secret.json`, `token.json`, refresh_token. Đã có `.env*` trong `.gitignore`; thêm `client_secret.json`, `token.json`, `*.key` vào gitignore ở phase 01.
- Bật 2FA Google. Dùng account riêng dự án để cô lập rủi ro.

## Next Steps
→ Phase 01 (scaffold + `.env.example` + gitignore hardening). Phase 06 dùng refresh_token/audit. Dev KHÔNG chờ audit xong mới bắt đầu 01-05.

## Unresolved Questions
- Deploy target cuối (Mac always-on vs Fly.io vs Hetzner)? — chốt ở phase 08.
- Music library licensed nào (YouTube Audio Library free vs Epidemic/Artlist trả phí)? — ảnh hưởng phase 04.
