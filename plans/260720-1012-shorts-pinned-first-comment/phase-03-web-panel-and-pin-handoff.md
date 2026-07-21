# Phase 03 — Web panel + pin hand-off

**Priority:** P1 | **Status:** ⬜ chưa làm | **Depends on:** phase 02

## Overview

Trên trang chi tiết video của một Short: một ô soạn comment, nút **Lưu & duyệt**, nút
**Đăng ngay**, và sau khi post — deep link mở thẳng vào comment để ghim + nút **Đã ghim**.

## Key insights

- **Lưu = duyệt.** Chỉ có một nút lưu, không có trạng thái "nháp chưa duyệt". Vì
  `comment_text` khác NULL là điều kiện để bot post, một ô "lưu nháp" riêng sẽ tạo đúng
  cái bug tệ nhất: bot đăng bản chưa duyệt. Ai muốn sửa thì lưu đè.
- **Deep link phải là `https://www.youtube.com/watch?v=<yt_id>&lc=<comment_id>`**, không
  phải link Studio. Link này mở thẳng vào đúng comment (nơi có nút ghim) và mở đúng trong
  app YouTube trên điện thoại. Studio → Community → Comments **không ghim được**
  ("This option only appears when viewing comments for an individual video").
- **Kênh push, không phải kênh pull.** Alert Telegram khi post thành công (kèm text + deep
  link) là thứ khiến việc ghim thực sự xảy ra. Một ô đếm "posted but unpinned" trên trang
  ops chỉ hữu ích nếu operator mở trang ops — cùng một failure mode với việc quên ghim.
- Ghim trên Shorts là đòn bẩy **thứ tự**, không phải đòn bẩy hiển thị: trên Shorts player,
  comment nằm sau một cú tap dù có ghim hay không. Giá trị thật là "chắc chắn slot #1
  trong số người đã mở panel" — đáng làm vì rẻ, không đáng xây thêm gì quanh nó.
- Sau khi `comment_id` đã có: render textarea **disabled**, NHƯNG route lưu **vẫn phải
  trả 409**. Mọi router được mount **hai lần** (`app.py:56-58`): bản HTML và bản `/api`.
  Tức `/api/videos/{id}/comment` không có UI nào đứng trước cả, và một tab cũ hoặc một lần
  submit lại sẽ âm thầm ghi đè `comment_text` — chính là artifact mà phase 02 chỉ định làm
  bằng chứng consent — trong khi `comment_id` vẫn trỏ tới comment đang sống với chữ khác.
- **Cột comment nằm trên `uploads`, mà dòng `uploads` chỉ sinh lúc publish**
  (`publish.py:181-204`). Short đã render/approved nhưng chưa publish thì `upload is None`
  (`routes_videos.py:236`). Viết copy trước khi publish là thao tác tự nhiên của operator,
  nên phải quyết định rõ chứ không để `AttributeError` → 500.
- Truy cập dòng `uploads` ở cả 3 route dùng đúng biểu thức latest-wins ở phase 02 (Bẫy 2).

## Related code files

**Modify**
- `src/ai_operator/web/routes_actions.py` — 3 route mới
- `src/ai_operator/web/routes_videos.py` — `_video_detail()` trả thêm state comment
- `src/ai_operator/web/templates/video_detail.html` — khối UI (chỉ hiện khi `kind == "short"`)

**Create**
- `tests/test_web_first_comment_actions.py`

## Routes

| Method | Path | Việc |
|---|---|---|
| POST | `/videos/{video_id}/comment` | Lưu & duyệt: ghi `comment_text`, **clear `comment_error`**. `comment_id` đã có → **409** |
| POST | `/videos/{video_id}/comment/post` | Gọi `first_comment.post_comment()` ngay (không phụ thuộc toggle autopost) |
| POST | `/videos/{video_id}/comment/pinned` | Đóng dấu `comment_pinned_at = utcnow()` |

Cả ba theo đúng pattern `_decided(...)` đang dùng trong `routes_actions.py`. 409 dùng đúng
mẫu đã có ở `routes_actions.py:125`:
`_decided(request, video_id, {"error": "comment đã đăng — không sửa được"}, status_code=409)`.

Cả ba route đều phải xử lý `upload is None` (short chưa publish) bằng `_decided(...)` với
thông báo rõ ràng — **không được** để `AttributeError` thoát ra thành 500; panel có hợp
đồng never-500 (`routes_actions.py:6-8`).

Nút **Đăng ngay** là đường đi mặc định (autopost toggle đang `False`). Nó chạy đồng bộ
trong request — `commentThreads.insert` là một lời gọi HTTP, không cần đẩy vào job queue.

## UI states (chỉ hiển thị với `kind == "short"`)

```
[chưa publish]        chưa có dòng uploads -> chỉ hiện ghi chú
                      "viết được sau khi short lên lịch publish"; không render form

[chưa có text]        textarea trống + [Lưu & duyệt]
                      + link tới playbook copy

[đã duyệt, chưa post] textarea (sửa được) + [Lưu & duyệt] + [Đăng ngay]
                      + dòng trạng thái: "chờ go-live" / "đã live, sẵn sàng đăng"

[đã post]             text đã đăng (disabled) + [🔗 Mở comment để ghim] + [Đã ghim]

[đã ghim]             text (disabled) + "Đã ghim lúc <thời điểm>"

[lỗi]                 banner đỏ comment_error + textarea sửa được + [Lưu & duyệt]
                      (lưu lại sẽ clear lỗi và cho bot thử lại)
```

## Implementation steps

1. **Dựng dict `comment` trong `video_detail()` (`routes_videos.py:196`), KHÔNG phải trong
   `_video_detail()`.** `_video_detail(v: Video)` (`routes_videos.py:138`) chỉ nhận một
   `Video`, không mở session và không bao giờ thấy `Upload` — mà cả 5 cột comment đều nằm
   trên `uploads`. Dựng dict ngay cạnh `upload_row` (`routes_videos.py:236-242`) từ object
   `Upload` đã có sẵn trong tay, rồi truyền vào template như một key cấp cao riêng
   (`"comment": ...`) bên cạnh `"upload"`.

   Nội dung dict: `text`, `id`, `posted_at`, `pinned_at`, `error`, `deep_link` (chỉ khi có
   `comment_id`), `has_upload` (`upload is not None`).
2. Ba route trong `routes_actions.py`. Route `comment` **phải** set `comment_error = None`
   khi lưu — đó là cách operator gỡ một dòng terminal.
3. Template: một khối `{% if video.kind == 'short' %}` với 6 nhánh trạng thái ở trên.
   Bám theo style của khối re-render/copy-subtitles đã có. Nhánh đầu tiên phải là
   `{% if not comment.has_upload %}` — nếu không, form render lên rồi mọi lần lưu đều lỗi.
4. Alert Telegram thành công đặt trong `first_comment.post_comment` (phase 02), không phải
   trong route — để cả đường autopost lẫn đường bấm tay đều gửi.

## Tests

- `test_save_comment_clears_previous_error`
- `test_save_comment_rejected_after_post` — 409, gọi qua mount `/api` (không có UI chắn)
- `test_save_comment_before_publish_is_graceful` — không có dòng `uploads` → không 500
- `test_post_now_calls_poster_and_persists_id`
- `test_post_now_is_noop_when_already_posted`
- `test_pinned_route_stamps_timestamp_only`
- `test_comment_block_hidden_for_main_videos`

## Success criteria

- Soạn → Lưu → Đăng ngay → comment xuất hiện thật trên Short trên YouTube.
- Deep link mở đúng comment đó trên app điện thoại.
- Bấm "Đã ghim" → panel hiển thị mốc thời gian; reload không mất.

## Risk assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Bấm "Đăng ngay" khi video chưa live | `_is_live` chặn, trả thông báo "chưa live" chứ không ghi error |
| Lưu comment khi short chưa publish (chưa có dòng `uploads`) | Form không render; route trả thông báo rõ qua `_decided`, không 500 |
| Ghi đè `comment_text` sau khi đã post (qua mount `/api` hoặc tab cũ) | Route trả 409 — bằng chứng consent không bị sửa lén |
| Operator quên ghim | Alert Telegram push kèm deep link; chấp nhận đây là bước thủ công không tự động hoá được |
| Panel không auth (loopback, no auth) | Không đổi gì — cùng mức rủi ro với mọi route hiện có |

## Next steps

Phase 04 (playbook) và 05 (metric) chạy song song.
