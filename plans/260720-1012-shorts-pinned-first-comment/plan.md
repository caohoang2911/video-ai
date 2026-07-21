# Shorts pinned first-comment — auto-post + manual pin hand-off

**Status:** planned | **Branch:** feat/ops-observability-validation | **Created:** 2026-07-20

## Goal

Sau khi một Short đi live, kênh tự đăng comment đầu tiên chứa một prompt thảo luận
(operator duyệt trước hoặc bấm đăng), rồi operator ghim nó bằng một deep link.
Mục tiêu là seed thảo luận **mà không** đụng vào 60s runtime của short và **không**
đóng curiosity gap đang nuôi funnel sang video dài.

## Owner decisions (locked)

| Quyết định | Chọn |
|---|---|
| Scope | **Chỉ Shorts.** Main video là đích của funnel, contract copy khác — để tăng sau |
| Posture | **Thủ công mặc định** + `SHORTS_COMMENT_AUTOPOST` toggle (mặc định `False`) |
| Advanced features | **Đã bật** → pin khả dụng, phần hand-off có giá trị thật |
| Copy source | **Operator viết tay.** Không thêm field vào `ShortScript`, không đụng `_SYSTEM` prompt |

## Hard constraints (verified)

- `commentThreads.insert` chỉ nhận scope `youtube.force-ssl` → **bắt buộc re-auth**;
  token hiện tại chỉ có `youtube.upload` + `youtube` + `yt-analytics.readonly`.
- YouTube **không cho comment lên video private**. `publish()` upload `private` +
  `publishAt` trong tương lai (`publish.py:238-249`, `scheduler.py:61-84`) → không post
  được lúc publish; phải đợi video flip public.
- **API không pin được** (không có method/field nào). Pin là thao tác tay trong Studio,
  và Studio **không có màn hình pin hàng loạt** — mở từng video.
- Dev Policies III.C.2 / III.E.3.d / III.I.2: comment tự động phải có consent rõ ràng
  của người dùng → mọi comment phải do người duyệt đúng từng chữ trước khi lên wire.
- Spam policy cấm comment "high-volume, repetitive" → copy phải khác nhau thật giữa
  các video; cấm template có slot dùng lại.

## Phases

Plan đã qua red-team (6 lens, 36 finding → 20 sống sót sau phản biện, 0 blocker).
Các sửa đã áp: bỏ scope-check khỏi `health.snapshot()`; cấm số học datetime phía Python
với `publish_at` (SQLite trả naive — đã repro); claim nguyên tử chống double-post; quy tắc
latest-`uploads`-row; sweep cảnh báo nằm ngoài kill switch; 409 khi sửa comment đã post;
xử lý short chưa có dòng `uploads`; và **viết lại toàn bộ copy mẫu sang tiếng Anh**.

| # | Phase | Trạng thái |
|---|---|---|
| 01 | [OAuth scope + schema](phase-01-oauth-scope-and-schema.md) | ⬜ chưa làm |
| 02 | [Comment poster + scheduler scan](phase-02-comment-poster-and-scheduler.md) | ⬜ chưa làm |
| 03 | [Web panel + pin hand-off](phase-03-web-panel-and-pin-handoff.md) | ⬜ chưa làm |
| 04 | [Comment copy playbook](phase-04-comment-copy-playbook.md) | ⬜ chưa làm |
| 05 | [Comments metric (đo hiệu quả)](phase-05-comments-metric.md) | ⬜ chưa làm |

Phase 04 không có code — nó là tài liệu copy operator dùng mỗi lần viết. Đọc nó
**trước** khi viết comment đầu tiên. Phase 05 nhỏ nhưng là điều kiện để biết feature
có tác dụng hay không; không có nó thì đây là máy móc không đo được.

## Dependencies

```
01 (scope + schema) ──> 02 (poster) ──> 03 (panel)
                                   └──> 05 (metric, độc lập)
04 (playbook) ── độc lập, làm song song bất kỳ lúc nào
```

Phase 01 chặn tất cả: re-auth làm **invalidate refresh token hiện tại**, nên upload sẽ
chết cho đến khi `authorize_once` chạy xong. Chọn thời điểm không có video nào đang chờ publish.

## Out of scope

- Comment cho main video (contract copy khác — increment sau).
- LLM sinh copy (đánh giá lại sau khi phase 05 có số liệu thật).
- Tự động pin (API không hỗ trợ, và không có đường vòng nào hợp lệ — browser
  automation vi phạm ToS "automated means").
- Trả lời comment của viewer tự động (self-reply chain = fake engagement).
