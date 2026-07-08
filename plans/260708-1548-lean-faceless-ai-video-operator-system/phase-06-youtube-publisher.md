# Phase 06 — YouTube Publisher

## Context Links
- Overview: [plan.md](plan.md) · Prev: [phase-05](phase-05-review-gate-telegram.md)
- Research brief: "YouTube Data API v3 Auto-Upload cho Headless Server".
- **Blocker:** phase 00 API Audit + verified account + refresh_token.

## Overview
- **Priority:** P0
- **Status:** pending
- **Description:** Upload video `state=approved` lên YouTube qua Data API v3: OAuth refresh-token headless, resumable upload, metadata + thumbnail, **BẬT AI disclosure** (`containsSyntheticMedia=true`), schedule `publishAt`, throttle ≤3/tuần + quota guard.

## Key Insights (từ brief — CRITICAL)
- **Unverified API project → video khoá private-only.** Phải API Audit (phase 00). Cho tới khi approved, upload luôn `privacyStatus=private` (test OK).
- **Resumable upload:** `MediaFileUpload(resumable=True, chunksize=256*1024*1024)`; loop `next_chunk()` với exponential backoff `2^retry` (max 60s); 404→restart, 5xx→retry, khác→fail. Session URI hết hạn ~7 ngày.
- **Quota:** upload=1600 units, update=50, thumbnail=50; **10.000 units/ngày → ~5-6 upload/ngày** max. Cadence ≤3/tuần thừa an toàn. Guard: alert nếu remaining <2000.
- **Scheduling cần `privacyStatus=private` + `publishAt`** (ISO8601 UTC). YouTube tự chuyển public đúng giờ. Nếu set public/bỏ privacyStatus → `publishAt` bị bỏ qua âm thầm.
- **`selfDeclaredMadeForKids=false` PHẢI set explicit** (không để default kênh).
- **`containsSyntheticMedia=true`** cho AI disclosure (đặt qua `status` khi insert/update). *(đã có — verify xác nhận, giữ nguyên)*
- **Custom thumbnail** `thumbnails.set()` cần account verified SĐT; JPEG/PNG ≤2MB 1280x720; KHÔNG áp Shorts.
- **YouTube "Test & Compare" = tính năng Studio THỦ CÔNG, KHÔNG có public API** (tính đến 2026-06). Publisher KHÔNG auto-submit được — chỉ **ghi 3 title + 3 thumbnail variant vào `uploads`** làm metadata; user tự set Test & Compare trong Studio (thumbnail test là feature Studio thật, chạy trên impressions kênh, chọn winner theo watch-time). **Vòng đời A/B + winner do phase-07 `ab_test_tracker` sở hữu DUY NHẤT** (tránh trùng module).
  - **Title/Thumbnail variants:** ghi `title_options[3]` (script.json) + 3 thumbnail (generator). Mỗi thumbnail mang overlay `thumbnail_text` khớp 1 `title_option` (ghép cặp phase-02→04) → variant nhất quán thông điệp.
  - **Winner:** user chạy Studio 1-2 tuần → phase-07 đọc/nhập winner → `uploads.winning_title/winning_thumbnail`, `ab_status`.
  - **Feedback loop:** winner + `reject_reason` → phase-07 feed lại phase-02 (title/thumbnail học từ winner thật).
- **Refresh token hết hạn nếu 6 tháng không dùng; CHỈ endpoint token POST reset timer** (API call không reset) → phase 07 cron keep-alive.

## Requirements
Functional:
1. `oauth_headless`: từ `refresh_token + client_id + client_secret` → `Credentials` auto-refresh; build `youtube` service. Script `authorize` chạy 1 lần lấy refresh_token (phase 00 step 5).
2. `upload_video(video_id)`: resumable upload + metadata body + backoff; trả `youtube_video_id`; ghi bảng `uploads`.
3. `set_thumbnail` (nếu account verified + có thumb).
4. `schedule`: set `publishAt` (private→auto public).
5. `quota_guard` + `throttle` (≤3/tuần đọc `uploads` 7 ngày).
6. State: approved → published (hoặc scheduled).
Non-functional: idempotent (không upload trùng nếu retry); log units tiêu; error mapping; file <200 dòng.

## Architecture — flow
```
videos(state=approved) ─► publisher.publish(video_id)
   throttle_check(≤3/7d) & quota_check(remaining≥1600)
        │ ok
   oauth_service (refresh_token auto-refresh)
   build body: snippet(title, description, tags, categoryId=27 Education/22 People&Blogs)
               status(privacyStatus=private, publishAt=ISO, selfDeclaredMadeForKids=false,
                      containsSyntheticMedia=true)
   videos.insert(resumable, chunk256MB) →next_chunk loop+backoff→ youtube_video_id
   thumbnails.set(if verified) ; uploads row (scheduled) ; videos.state=published
   ghi title_options[3] + 3 thumbnail variant → uploads (ab_status='pending_manual')
        └► user chạy Studio Test & Compare (thủ công) → phase-07 ab_test_tracker đọc/nhập winner
            → feed lại phase-02
```

## Related Code Files
- Create: `src/ai_operator/publisher/oauth_headless.py` (Credentials + service builder), `src/ai_operator/publisher/authorize_once.py` (InstalledAppFlow → in refresh_token; chạy tay 1 lần), `src/ai_operator/publisher/youtube_uploader.py` (resumable + backoff), `src/ai_operator/publisher/metadata_builder.py` (snippet/status body từ script.json), `src/ai_operator/publisher/quota_throttle.py` (đếm quota app_state + throttle ≤3/tuần), `src/ai_operator/publisher/thumbnail_setter.py`. (**Không có module Test & Compare ở phase-06** — chỉ ghi variants vào `uploads`; vòng đời A/B do phase-07 `ab_test_tracker` sở hữu, tránh trùng.)
- Modify: `cli.py` (`authorize`, `publish --video-id X`), `db/models.py` (uploads: thêm cột `winning_title`, `winning_thumbnail`, `ab_status` để phase-07 đọc winner).
- Delete: none.

## Implementation Steps
1. `authorize_once.py`: `InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)` với `SCOPES=['youtube.upload','youtube','yt-analytics.readonly']`; `run_local_server()`; in `creds.refresh_token` → user dán vào `.env` `YT_REFRESH_TOKEN`. Chạy 1 lần (phase 00).
2. `oauth_headless.py`: `build_service()`: `Credentials(None, refresh_token=..., token_uri='https://oauth2.googleapis.com/token', client_id=..., client_secret=..., scopes=SCOPES)`; `build('youtube','v3',credentials=creds)`. Access token auto-refresh khi expired.
3. `metadata_builder.py`: từ `script.json` + chosen title (**mặc định `title_options[0]` cho upload đầu; Test & Compare test cả 3, winner áp sau qua phase-07**) → body dict: `snippet{title(≤100 ký tự), description(+ sources + AI disclosure text + music credit), tags, categoryId='27'}`, `status{privacyStatus:'private', publishAt: iso, selfDeclaredMadeForKids: False, containsSyntheticMedia: True}`.
4. `quota_throttle.py`: `throttle_ok()`: count uploads 7 ngày <3. `quota_remaining()`: đọc/ghi `app_state` (reset theo ngày PT); `reserve(units)`. Alert nếu <2000.
5. `youtube_uploader.py`: `upload(video_path, body)`: `MediaFileUpload(video_path, chunksize=256*1024*1024, resumable=True)`; `request=service.videos().insert(part='snippet,status', body=body, media_body=media)`; loop `status, response = request.next_chunk()`; backoff on 5xx (`min(2**retry,60)`), restart on 404, fail else. Trả `response['id']`.
6. `thumbnail_setter.py`: `set(video_id, thumb_path)`: `service.thumbnails().set(videoId=..., media_body=MediaFileUpload(thumb, ...)).execute()`; catch permission (chưa verified) → log warning, không fail publish.
7. Orchestrate `publisher.publish(video_id)`: throttle+quota check → build service → body → upload → thumbnail → ghi `uploads`(youtube_video_id, publish_at, status=scheduled) → `videos.state=published`. Idempotent: nếu uploads đã có youtube_video_id cho video → skip.
8. `test_and_compare.py`: sau upload thành công, `submit_ab(video_id, title_options[2..3], thumb_variants[3])` gọi Test & Compare (title mode + thumbnail mode) để YouTube auto-test theo watch-time. Idempotent: nếu `uploads.ab_status` đã submitted → skip. `read_winner(video_id)` (phase-07 gọi định kỳ) đọc kết quả khi test xong → ghi `uploads.winning_title`/`winning_thumbnail`, set `ab_status=done`. Non-blocking: lỗi Test & Compare chỉ log warning, không fail publish.
9. `cli.py`: `operator authorize`, `operator publish --video-id X --publish-at "2026-..."`.
10. Test: upload video test (private) → verify trên Studio: privacy private, publishAt set, madeForKids=No, **AI-content label hiện**, thumbnail (nếu verified), title/thumbnail variants đã ghi `uploads` (ab_status='pending_manual').

## Todo List
- [ ] authorize_once → lấy refresh_token (phase 00)
- [ ] oauth_headless service builder (auto-refresh)
- [ ] metadata_builder (containsSyntheticMedia + madeForKids=false + publishAt)
- [ ] quota_throttle (≤3/7d + units guard + alert)
- [ ] youtube_uploader (resumable 256MB + backoff 404/5xx)
- [ ] thumbnail_setter (verified-only, non-blocking)
- [ ] publisher.publish orchestrate + idempotent + uploads row
- [ ] ghi title/thumbnail variants + ab_status='pending_manual' vào uploads (KHÔNG API; vòng đời A/B do phase-07 ab_test_tracker)
- [ ] cli authorize / publish
- [ ] test upload private + verify labels trên Studio + Test & Compare submitted

## Success Criteria
- Video test lên YouTube (private), `publishAt` set đúng, `madeForKids=false`, **AI disclosure label hiển thị** trên Studio.
- Thumbnail set (nếu account verified) — hoặc log warning sạch nếu chưa.
- Throttle chặn upload thứ 4 trong 7 ngày; quota guard alert <2000.
- `uploads` row có youtube_video_id; `videos.state=published`; retry không tạo bản trùng.

## Risk Assessment
| Risk | L | I | Mitigation |
|---|---|---|---|
| API chưa audit → khoá private | High (đầu) | High | Upload private khi test; chờ audit approved mới bật publishAt→public thật. |
| Refresh token 6 tháng hết hạn | Med | High | Cron keep-alive POST token endpoint (phase 07). |
| Quota exceeded | Low | Med | Cadence ≤3/tuần; guard remaining; upload cách nhau ≥2h. |
| Upload trùng khi retry | Med | Med | Idempotent check uploads.youtube_video_id. |
| Thumbnail permission fail | Med | Low | Non-blocking; verify SĐT (phase 00). |
| Session URI hết hạn (>7 ngày) | Low | Low | Upload ngay sau approve; restart nếu 404. |
| Test & Compare không có API → không auto-submit | Med | Low | Ghi variants vào uploads; user chạy Studio thủ công; phase-07 track winner; không winner → giữ title/thumbnail gốc. Non-blocking. |

## Security Considerations
- `refresh_token`, `client_secret.json`, `token.json` gitignored. Không log token.
- SCOPES tối thiểu cần thiết. Không dùng service account (Analytics cần user-scope).
- Description ghi rõ AI-assisted + nguồn + music credit (minh bạch policy).

## Next Steps
→ Phase 07 scheduler tự publish `approved` + cron keep-alive token + analytics. Phase 09 chạy validate thật (public sau audit).

## Unresolved Questions
- categoryId: 27 (Education) hay 22 (People & Blogs)? — đề xuất 27 cho documentary.
- publishAt do user set khi approve (Telegram) hay scheduler tự rải đều ≤3/tuần? — đề xuất scheduler tự rải (phase 07), user override được.
