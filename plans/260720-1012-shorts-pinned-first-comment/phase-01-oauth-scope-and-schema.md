# Phase 01 — OAuth scope + schema

**Priority:** P0 (chặn mọi phase khác) | **Status:** ⬜ chưa làm

## Overview

Mở scope `youtube.force-ssl` cho token và thêm 5 cột lên bảng `uploads` để lưu copy đã
duyệt + trạng thái post/pin. Không có logic nghiệp vụ trong phase này.

## Key insights

- `commentThreads.insert` **chỉ** nhận `https://www.googleapis.com/auth/youtube.force-ssl`.
  Không có scope hẹp hơn. Scope này kèm quyền **moderate + xoá comment toàn kênh** trên
  đúng cái token đang chạy mọi upload — chấp nhận blast radius này là điều kiện tiên quyết.
- Re-auth **huỷ refresh token hiện tại**. Trong lúc chưa chạy xong `authorize_once`,
  publish/analytics đều gãy. Chọn cửa sổ không có video approved đang chờ.
- Trạng thái được **suy ra** từ 5 cột, không có cột `comment_status`. Ít cột hơn, ít
  đường lệch pha hơn:

  | Điều kiện | Trạng thái |
  |---|---|
  | `comment_text IS NULL` | chưa có gì — bot không bao giờ đụng vào |
  | `comment_text` set, `comment_id NULL`, `comment_error NULL` | đã duyệt, chờ post |
  | `comment_id` set | đã post (terminal — không bao giờ post lại) |
  | `comment_error` set | lỗi terminal, chờ operator sửa & lưu lại (clear error) |
  | `comment_pinned_at` set | người đã ghim |

- `comment_posted_at` (bot ghi) và `comment_pinned_at` (người ghi) **tách riêng** có chủ
  đích: API không pin được, gộp một cột là panel báo cáo việc chưa từng xảy ra.
- `comment_error` tách khỏi `Upload.error` — cột kia nghĩa là *upload video* thất bại.

## Related code files

**Modify**
- `src/ai_operator/publisher/oauth_headless.py` — thêm scope vào `SCOPES` (dòng 22-26)
- `src/ai_operator/db/models.py` — 5 cột mới trên `Upload` (sau dòng 99)
- `src/ai_operator/db/schema_migrations.py` — 5 tuple vào `_PENDING`
- `src/ai_operator/constants.py` — `YT_COST_COMMENT = 50`, `YT_COST_VIDEO_LIST = 1`
- `src/ai_operator/config.py` — `SHORTS_COMMENT_AUTOPOST: bool = False`

**Create** — không có.

## Implementation steps

1. `oauth_headless.SCOPES` += `"https://www.googleapis.com/auth/youtube.force-ssl"`.
   Cập nhật comment ở dòng 20-21 giải thích **tại sao** scope rộng này cần thiết
   (đây là scope duy nhất `commentThreads.insert` chấp nhận) — không nhắc plan/phase.
2. Thêm cột vào `Upload`:
   ```python
   comment_text:      Mapped[str | None]      = mapped_column(Text, default=None)
   comment_id:        Mapped[str | None]      = mapped_column(String(64), default=None)
   comment_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
   comment_pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
   comment_error:     Mapped[str | None]      = mapped_column(Text, default=None)
   ```
3. `schema_migrations._PENDING` += 5 tuple tương ứng
   (`("uploads", "comment_text", "TEXT")`, `comment_id VARCHAR(64)`,
   `comment_posted_at DATETIME`, `comment_pinned_at DATETIME`, `comment_error TEXT`).
4. Constants + config flag như trên. `SHORTS_COMMENT_AUTOPOST` mặc định `False`.
5. **KHÔNG đưa kiểm tra scope vào `health.snapshot()`.** `snapshot()` (`health.py:129-155`)
   là dict literal thuần local, không try/except, và `routes_dashboard.py:20` gọi nó trên
   **mọi** `GET /`. Cách duy nhất đọc được scope đã cấp là `build_credentials()`
   (`oauth_headless.py:42-63`) — nó ép refresh token đồng bộ và raise `OAuthNotConfigured`
   khi thiếu env. Nhét vào đây là dashboard 500 trong đúng cửa sổ giữa bước 1 và bước 7.

   Nếu vẫn muốn có kiểm tra: đặt ở **CLI `operator health`**, bọc try/except, và dùng
   **đúng** biểu thức này:
   ```python
   "https://www.googleapis.com/auth/youtube.force-ssl" in (creds.granted_scopes or [])
   ```
   Không dùng `creds.has_scopes(...)` — nó so với danh sách `SCOPES` yêu cầu **cục bộ**
   (chính là list bước 1 vừa sửa), nên trả `True` kể cả khi token cũ chưa hề được cấp
   scope đó. Một kiểm tra không bao giờ fail còn tệ hơn không kiểm tra.
6. Chạy `operator init-db` để apply migration. Xác nhận `PRAGMA table_info(uploads)`.
7. **Người dùng tự chạy** re-auth (interactive, cần trình duyệt):
   `! PYTHONPATH=src .venv/bin/python -m ai_operator.cli authorize` — chạy đúng lệnh mà
   `publisher/authorize_once.py` expose, ghi `YT_REFRESH_TOKEN` mới vào `.env`.

## Todo

- [ ] Thêm scope + cập nhật comment giải thích
- [ ] 5 cột trên `Upload`
- [ ] 5 entry migration
- [ ] `YT_COST_COMMENT`, `YT_COST_VIDEO_LIST`, `SHORTS_COMMENT_AUTOPOST`
- [ ] `init-db` + verify schema
- [ ] Re-auth (người dùng chạy)

## Success criteria

- `operator init-db` chạy 2 lần liên tiếp không lỗi (migration idempotent).
- `GET /` (dashboard) vẫn 200 sau khi sửa `SCOPES` và **trước** khi re-auth.
- Toàn bộ test suite hiện có vẫn pass (migration không phá gì).

## Risk assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Re-auth làm chết upload giữa chừng | Chạy khi không có video approved chờ publish; verify ngay bằng `health` |
| Scope rộng cho phép xoá comment toàn kênh | Không có lựa chọn hẹp hơn. Code chỉ gọi `insert`; không viết bất kỳ path nào gọi `delete`/`setModerationStatus` |
| Quên re-auth → lỗi 403 trên video đã live | Alert của phase 02 nêu **nguyên văn** câu lệnh re-auth cần chạy khi gặp `insufficientPermissions` |

## Next steps

Phase 02 — module poster + scheduler scan.
