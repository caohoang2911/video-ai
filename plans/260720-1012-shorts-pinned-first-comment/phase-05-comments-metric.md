# Phase 05 — Comments metric

**Priority:** P1 | **Status:** ⬜ chưa làm | **Depends on:** không (độc lập)

## Overview

Kéo thêm `comments` (và `likes`) từ YouTube Analytics API vào bảng `analytics`. Không có
nó thì toàn bộ increment này là máy móc không đo được — sẽ giữ mãi vì "cảm giác đúng".

## Key insights

- `analytics_puller._METRICS` hiện là `"views,estimatedMinutesWatched,averageViewPercentage"`
  — không có chiều comment. Model `Analytics` (`models_ops.py:23-38`) cũng không có cột.
- `comments` và `likes` đều là metric hợp lệ của YouTube Analytics API cho video report.
  **NHƯNG:** doc chính chủ không publish bảng tương thích giữa các metric, nên việc gọi
  chung `views,estimatedMinutesWatched,averageViewPercentage,likes,comments` trong MỘT
  request là **suy luận chưa kiểm chứng**, không phải sự thật có nguồn (đã tra
  `analytics/v2/channel_reports` + `mets_and_dims`: không có xác nhận, cũng không có cấm).
  → Bước 1 của phase này là **thử thật một query**, không phải sửa code luôn. Nếu API từ
  chối tổ hợp, fallback là request thứ hai chỉ gồm `likes,comments` — vẫn rẻ, `_query_ctr`
  ở `analytics_puller.py:65` đã là tiền lệ cho pattern request-phụ này.
- Kéo cả `likes` vì gần như miễn phí và `likes` **có** trong danh sách ranking input chính
  thức của Shorts, trong khi `comments` thì không — có cả hai mới so sánh được.
- Đây là baseline, không phải thí nghiệm có kiểm soát. Short không ghim comment (trước khi
  ship) so với short có ghim (sau khi ship) là so sánh trước/sau, nhiễu bởi mọi thứ khác
  đang thay đổi trên kênh. Đọc nó như tín hiệu, đừng đọc như bằng chứng.

## Related code files

**Modify**
- `src/ai_operator/ops/analytics_puller.py` — `_METRICS`, `_query_video`, `_upsert`
- `src/ai_operator/db/models_ops.py` — 2 cột trên `Analytics`
- `src/ai_operator/db/schema_migrations.py` — 2 entry
- `src/ai_operator/web/analytics_view.py` — hiển thị 2 cột (nếu bảng đang liệt kê metric)

**Modify (test)**
- `tests/` — file test analytics hiện có

## Implementation steps

0. **Thử tổ hợp metric trước khi sửa code.** Gọi tay một `reports.query` với
   `metrics="views,estimatedMinutesWatched,averageViewPercentage,likes,comments"`,
   `ids="channel==MINE"`, `filters="video==<một id đã publish>"`. Chấp nhận → bước 1.
   Bị từ chối → tách `likes,comments` thành request thứ hai theo mẫu `_query_ctr`.
1. `_METRICS = "views,estimatedMinutesWatched,averageViewPercentage,likes,comments"`
   (hoặc `_ENGAGEMENT_METRICS` riêng, tuỳ kết quả bước 0).
2. `Analytics`: `likes: Mapped[int] = mapped_column(Integer, default=0)`,
   `comments: Mapped[int] = mapped_column(Integer, default=0)`.
3. Migration: `("analytics", "likes", "INTEGER DEFAULT 0")`, `("analytics", "comments", "INTEGER DEFAULT 0")`.
4. `_query_video` map thêm 2 giá trị vào dict trả về; `_upsert` ghi 2 cột.
   Giữ nguyên pattern hiện có: chỉ overwrite khi đo được, không đè giá trị tốt bằng 0.
5. Bảng analytics trên web hiện thêm 2 cột. Với short, cột đáng nhìn là
   **comments / views**, không phải comments tuyệt đối.

## Success criteria

- `operator pull-analytics` chạy xong, các dòng `analytics` có `comments`/`likes` khác 0
  với video đã có tương tác thật.
- Migration idempotent (chạy `init-db` hai lần).
- Test analytics hiện có vẫn pass sau khi cập nhật fixture.

## Cách đọc số về sau

Sau ~8 short có comment ghim, so **comments/views** với các short trước đó, và **đồng thời**
kiểm tra `avg_view_pct` không tụt. Comment tăng mà retention tụt thì không phải thắng —
retention nằm trong ranking input chính thức của Shorts, comment thì không.

## Điều chưa giải quyết

- Analytics API không tách được comment do kênh tự đăng và comment của người xem; con số
  `comments` gồm cả comment ghim của chính mình (+1 mỗi video). Với short vài chục comment
  thì +1 là nhiễu đáng kể — trừ đi thủ công khi so sánh.
