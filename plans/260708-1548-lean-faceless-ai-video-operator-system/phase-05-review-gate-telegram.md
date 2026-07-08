# Phase 05 — Review Gate (Telegram Bot)

## Context Links
- Overview: [plan.md](plan.md) · Prev: [phase-04](phase-04-video-assembler.md)
- Research brief: "Telegram Review Gate Bot — python-telegram-bot v21+".
- **Policy-critical:** đây là cổng người duyệt giữ "original value" để sống sót policy AI.

## Overview
- **Priority:** P0
- **Status:** pending
- **Description:** Bot Telegram gửi preview `final.mp4` + metadata (title/desc/tags/thumbnail) tới user; **review 2 tầng** (TIER-1 POLICY per-video, TIER-2 QUALITY per-batch) với **decision codes có cấu trúc** (không nhị phân) → ghi audit trail `decisions` → phát tín hiệu cho publisher. Long polling (KISS P0).

## Key Insights (từ brief)
- **[CRITICAL] Review 2 tầng thay cho approve/reject nhị phân** — vì nhị phân dễ dẫn tới "duyệt hình thức" (rubber-stamp), mất chính "original value" giữ hệ thống sống sót policy.
  - **TIER-1 POLICY** (2-3'/ngày, mỗi video): check audio · video · caption · policy-flags · visuals · **EDSA (narration NÓI rõ who/what/when/where/why trong audio — không chỉ title/desc → giữ documentary exception)** · **giọng thương hiệu (`needs_revoice`=false, không phải fallback lạ)** → `PASS_POLICY` / `REJECT_POLICY_AUDIO|CAPTION|ORIGINALITY|EDSA|OTHER`. Đây là gate bắt buộc trước publish.
  - **TIER-2 QUALITY** (10'/batch, gộp nhiều video): check **hook 30s (có giữ chân không)** · **payoff nodes (≥5 điểm bất ngờ THẬT xuất hiện đúng nhịp — đối chiếu `surprise_score` trong script.json; đây là editorial judgment con người, auto-gate không thay được)** · pacing · sync ±200ms · Ken-Burns · music · originality → `PASS_QUALITY` / `EDIT_HOOK|PAYOFF|PACING|META` / `HOLD_RERUN`. Không chặn publish nhưng feed chất lượng về content-engine. **WHY policy:** quyết định biên tập hook/payoff = "human creative fingerprint" YouTube đòi để không bị coi mass-produced/inauthentic.
- **Decision codes có cấu trúc (không nhị phân)** lưu DB (`decision_code` + `reason` + `timestamp`) = audit trail. WHY: chuỗi mã + lý do buộc người duyệt ra quyết định thực chất, chống rubber-stamp và cho phép content-engine học từ pattern reject.
- **Reject-reason picker** (chọn mã REJECT_* + text tự do cho REJECT_OTHER) → lưu DB làm training signal cho content-engine, không mất thông tin "vì sao trượt".
- **Rubber-stamp alert**: báo cáo tuần (đã duyệt/edit/reject, % approval, avg thời gian duyệt); cảnh báo nếu approval = 100% liên tục (dấu hiệu duyệt hình thức, không thực xem).
- **Long polling P0** (không webhook): single instance, không cần HTTPS/public IP; latency 30-60s chấp nhận. Webhook để P1.
- **URL-based video delivery** (KHÔNG upload 50MB trực tiếp): render MP4 → host (local static server / S3 / Cloudflare R2) → gửi Telegram link hoặc `send_video(url=...)`. Tránh block upload chậm.
- **callback_data ≤64 bytes** → chỉ nhét `action:video_id` (vd `approve:42`), metadata tra DB trong handler.
- **Single polling instance** — 2 process cùng token → 409 conflict crash. Chạy 1 instance (systemd/supervisor/foreground P0).
- **State qua DB**, không giữ trong RAM (recover sau crash). Bảng `videos.state`: `pending_review → approved|rejected|editing`.
- **codec H.264** để Telegram sinh thumbnail preview (phase 04 đã đảm bảo).

## Requirements
Functional:
1. Khi video `state=rendered` → `notify_review(video_id)`: gửi preview + caption metadata + inline keyboard [✅ Approve | ❌ Reject | ✏️ Edit].
2. Callback handler: `approve` → state=approved (+ optional set publish_at); `reject` → state=rejected (+ lý do); `edit` → state=editing + hướng dẫn user sửa (title/desc qua reply).
3. Helper `get_chat_id` (in chat_id khi user nhắn — hỗ trợ phase 00).
4. Poll: scheduler (phase 07) hoặc job_queue quét `state=rendered` chưa gửi → gửi; quét `approved` → trigger publish.
Non-functional: single instance; chat_id từ `.env`; retry send 3x backoff; fallback link nếu send_video fail; file <200 dòng.

## Architecture — flow
```
videos(state=rendered) ─► review_notifier.notify(video_id)
    ├─ host final.mp4 → URL (static server / R2)
    └─ bot.send_video(url) + caption có section headers + metadata
       (duration · confidence · script snippet · số visuals · hook đang dùng · #payoff node score≥3)
       + InlineKeyboard 2 tầng + [📋 Checklist] + [🎬 Full Preview](URL)
                              │ user tap
                              ▼
CallbackQueryHandler → parse action:id → ghi decision (code+reason+ts) → edit_message_text
    ── TIER-1 POLICY (mỗi video) ──
    PASS_POLICY            → state=policy_ok → mở TIER-2
    REJECT_POLICY_*        → reject-reason picker (AUDIO/CAPTION/ORIGINALITY/EDSA/OTHER+text) → state=rejected
    ── TIER-2 QUALITY (theo batch) ──
    PASS_QUALITY           → state=approved  → (phase 06/07 publisher pick up)
    EDIT_HOOK|PAYOFF       → state=editing   → swap hook variant / regen payoff → re-render (P1)
    EDIT_META              → state=editing   → metadata-only (title/desc/tags, P0)
    HOLD_RERUN             → state=rerun_queued
    [📋 Checklist]         → tickbox inline (audio/video/caption/policy/visuals/edsa/hook/payoff)
    sau duyệt → clear buttons + hiện "APPROVED hh:mm"

decisions(video_id, tier, decision_code, reason, created_at)  ← audit trail
weekly rubber-stamp report: #approved/#edit/#reject, %approval, avg review time
    (alert nếu approval=100% liên tục)
```

## Related Code Files
- Create: `src/ai_operator/review/telegram_bot.py` (Application, handlers, run_polling), `src/ai_operator/review/review_notifier.py` (build message + send + host URL), `src/ai_operator/review/callbacks.py` (approve/reject/edit logic + DB), `src/ai_operator/review/media_host.py` (expose final.mp4 qua URL — local `http.server` hoặc R2 upload).
- Modify: `cli.py` (`run-bot`, `notify-review --video-id X`, `get-chat-id`, `review-report --week`), `db/models.py` (thêm bảng `decisions(video_id, tier, decision_code, reason, created_at)` = audit trail; cột `reject_reason`, `publish_at` nếu chưa — uploads đã có publish_at).
- Delete: none.

## Implementation Steps
1. `media_host.py`: P0 đơn giản — nếu có Cloudflare R2/S3 bucket: upload → presigned URL. Fallback: chạy `http.server` trên VPS/localhost expose `output/` (chỉ khi có public IP). Trả URL công khai của `final.mp4`.
2. `review_notifier.py`: `notify(video_id)`: lấy row video + uploads metadata → build caption có **section headers + metadata block** (duration · confidence · script snippet · số visuals · hook đang dùng · #payoff node score≥3) → `media_host` URL → `bot.send_video(chat_id, video=url, caption=..., reply_markup=keyboard, supports_streaming=True)`. Keyboard TIER-1 POLICY: nút `PASS_POLICY` + `REJECT_POLICY` + `[📋 Checklist]` + `[🎬 Full Preview](url)`, `callback_data=f"{code}:{video_id}"`. Try/except → fallback `send_message` + link button. Đánh dấu `videos.state=pending_review` (đã gửi).
3. `callbacks.py`: `CallbackQueryHandler` → `query.answer()` → parse `code, vid = data.split(':')` → transaction: (a) INSERT `decisions(video_id, tier, decision_code, reason, created_at)` = audit trail; (b) update `videos.state` theo decision code (PASS_POLICY→policy_ok mở TIER-2; PASS_QUALITY→approved; REJECT_*→rejected; EDIT_*→editing; HOLD_RERUN→rerun_queued). `REJECT_POLICY`/`REJECT_QUALITY` → hiện **reject-reason picker** (nút con AUDIO/CAPTION/ORIGINALITY/EDSA/HOOK/PAYOFF/PACING/VISUALS + OTHER→prompt text reply) → lưu `reason` để content-engine học. `[📋 Checklist]` → edit message thành tickbox inline (audio/video/caption/policy/visuals/edsa/hook/payoff). Sau quyết định: `edit_message_reply_markup(None)` (clear buttons) + `edit_message_text` hiện "APPROVED hh:mm".
4. `telegram_bot.py`: `Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()`; add `CommandHandler('start')`, `CommandHandler('chatid')` (in chat_id), `CallbackQueryHandler(handle_callback)`, `MessageHandler` (nhận edit reply). `app.run_polling(read_timeout=30)`. `concurrent_updates=False` (default, tránh race SQLite).
5. `cli.py`: `operator run-bot` (chạy polling foreground), `operator notify-review --video-id X` (thủ công P0), `operator get-chat-id`, `operator review-report --week` (đọc `decisions` → #approved/#edit/#reject, %approval, avg review time; cảnh báo nếu approval=100% liên tục = rubber-stamp).
6. Test: gửi 1 video test → PASS_POLICY → policy_ok → PASS_QUALITY → approved; REJECT_POLICY_AUDIO → rejected + reason lưu `decisions`; verify audit trail có đủ code+reason+ts; verify không 409 (1 instance).

## Todo List
- [ ] media_host (R2/S3 presigned hoặc http.server) → URL
- [ ] bảng `decisions` (audit trail: tier/decision_code/reason/ts)
- [ ] review_notifier (send_video + caption metadata/section headers + keyboard 2 tầng + [📋 Checklist] + [🎬 Full Preview] + fallback link)
- [ ] callbacks TIER-1 POLICY (PASS_POLICY/REJECT_POLICY_* → decisions + state)
- [ ] callbacks TIER-2 QUALITY (hook/payoff/pacing → PASS_QUALITY/EDIT_HOOK|PAYOFF|PACING|META/HOLD_RERUN → decisions + state)
- [ ] reject-reason picker (mã REJECT_* + OTHER+text → lưu reason)
- [ ] checklist inline tickbox + clear buttons + "APPROVED hh:mm" sau duyệt
- [ ] telegram_bot (Application + handlers + run_polling)
- [ ] cli run-bot / notify-review / get-chat-id / review-report --week (rubber-stamp alert)
- [ ] test 2-tier + audit trail + reject-reason + no 409

## Success Criteria
- User nhận preview video xem được (thumbnail hiện) + metadata trong Telegram.
- TIER-1 PASS_POLICY → policy_ok, TIER-2 PASS_QUALITY → `videos.state=approved` trong <60s; REJECT_* → rejected + reason picker lưu `decisions`; EDIT_* → editing + nhận metadata mới; mỗi quyết định có row `decisions` (code+reason+ts).
- `review-report --week` chạy được, cảnh báo khi approval=100% liên tục.
- Chạy bền 1 instance, không 409 conflict.
- callback_data ≤64 bytes (chỉ `action:id`).

## Risk Assessment
| Risk | L | I | Mitigation |
|---|---|---|---|
| 409 conflict (2 polling) | Med | High | 1 instance (systemd P1 / foreground P0); guard PID lock. |
| send_video fail (>50MB/URL) | Med | Med | URL delivery + fallback link button. |
| Race SQLite trên callback | Low | Med | `concurrent_updates=False` + transaction ngắn + WAL. |
| Không có public IP để host preview | Med | Med | Dùng R2/S3 presigned URL (khỏi cần server); hoặc ngrok tạm P0. |
| chat_id hard-code | Low | Low | Load `.env`; `get-chat-id` helper. |
| Rubber-stamp (duyệt hình thức, approval 100%) | High | High | Review 2 tầng + decision codes bắt buộc reason; `review-report --week` cảnh báo khi approval=100% liên tục; audit trail `decisions` truy vết. |
| Decision code drift / callback_data >64B | Low | Med | Mã ngắn cố định (`PASS_POLICY:ID`); metadata reason lưu DB, không nhét callback_data. |

## Security Considerations
- Chỉ chấp nhận callback từ `TELEGRAM_CHAT_ID` (whitelist user) — bỏ callback lạ.
- Preview URL nên có token/expiry (presigned) tránh lộ video chưa publish.
- Token bot qua env; không log.

## Next Steps
→ Phase 06 publisher tiêu thụ `state=approved` → upload YouTube. Phase 07 scheduler tự động notify + publish.

## Unresolved Questions
- "Edit" nên cho sửa gì? — P0: chỉ metadata (title/desc/tags) không re-render; re-render script/media là P1 (tốn kém).
- Host preview: R2/S3 (cần user tạo bucket — thêm vào phase 00) hay ngrok tạm? — đề xuất R2 (free tier, presigned, bền).
