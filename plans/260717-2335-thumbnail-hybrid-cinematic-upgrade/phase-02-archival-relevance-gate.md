---
phase: 2
title: "Archival relevance gate (CLIP)"
status: pending
priority: P1
effort: "2-3h"
dependencies: []
---

# Phase 2: Archival relevance gate (CLIP)

## Overview
Chặn ảnh archival chất-lượng-tốt-nhưng-sai-subject (vụ "Viking Sally" sai livery ở demo) khỏi thành hero. Archival chỉ được chọn khi **liên quan nội dung** (CLIP vs subject) đủ cao; không thì rớt sang **Phase 3** (archival rớt hết → synthetic FLUX hero; archival qua cổng → Kontext enhance).

## Requirements
- Functional: mỗi ảnh archival ứng viên chấm CLIP-relevance vs subject video; dưới ngưỡng bị loại khỏi pool thumbnail.
- Non-functional: best-effort — CLIP không khả dụng (no torch/model) thì gate bỏ qua (giữ hành vi cũ archival-first), KHÔNG chặn render.

## Architecture
- Thêm `clip_reranker.score(text, image_path) -> float` (cosine sim, dùng lại model đã load; trả None/-inf nếu unavailable). Hiện chỉ có `rank()`.
- Subject text = `video.title` split trước `:` (giống `_archival_anchor` trong visual_fetcher) — tên sự kiện/tàu.
- Trong `thumbnail_generator._thumbnail_sources`: sau khi rank archival theo frame-score, lọc thêm `score(subject, p) >= THUMB_RELEVANCE_MIN`. Ngưỡng calibrate bằng vài mẫu (Estonia sai-livery phải rớt; ảnh đúng tàu phải đậu). Bắt đầu ~0.22 (CLIP cosine điển hình 0.18-0.30), tinh sau.
- Archival rớt hết → `_thumbnail_sources` trả rỗng phần archival → Phase 3 (hero fallback) lo.

## Related Code Files
- Modify: `src/ai_operator/media/clip_reranker.py` (+`score()`)
- Modify: `src/ai_operator/assembler/thumbnail_generator.py` (`_thumbnail_sources` gate; helper subject text)
- Modify: `src/ai_operator/config.py` (`THUMB_RELEVANCE_MIN: float = 0.22`)

## Implementation Steps
1. `clip_reranker.score(text, path)`: encode text + image, cosine; best-effort None.
2. Subject text helper (tái dùng lối split title của visual_fetcher `_archival_anchor`).
3. Gate trong `_thumbnail_sources`: filter archival theo ngưỡng; log điểm để calibrate.
4. Thêm config ngưỡng.
5. Calibrate ngưỡng trên 2-3 video thật (Estonia rớt archival, Lusitania/Halifax đậu).

## Success Criteria
- [ ] Ảnh archival sai-subject (Viking Sally cho Estonia nếu score thấp) bị loại; ảnh đúng tàu giữ lại.
- [ ] CLIP unavailable → gate no-op, archival-first cũ vẫn chạy (không crash).
- [ ] Log điểm relevance để chỉnh ngưỡng.

## Risk Assessment
- **Ngưỡng sai loại nhầm ảnh tốt / giữ ảnh xấu:** calibrate trên mẫu thật; log điểm; ngưỡng ở config để chỉnh không cần deploy code.
- **CLIP không phân biệt được livery (Viking Sally vẫn "a ship"):** rủi ro thật — CLIP có thể vẫn cho điểm khá cao cho tàu chung. Nếu gate không đủ nhạy, Phase 3 hero fallback vẫn là lưới an toàn; ghi nhận giới hạn, không cố ép CLIP làm việc nó không giỏi.
