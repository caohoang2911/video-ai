---
phase: 4
title: "Tests + render + docs"
status: pending
priority: P1
effort: "2-3h"
dependencies: [1, 2, 3]
---

# Phase 4: Tests + render + docs

## Overview
Chốt an toàn: unit test template/gate/fallback + render thật 1-2 video (Estonia = hero fallback, Lusitania = archival) xem 3 thumbnail thật.

## Requirements
- Functional: test `draw_title` cinematic (accent đỏ, kicker degrade), `clip_reranker.score` best-effort None, gate loại đúng, fallback hero khi archival rớt.
- Non-functional: render thật KHÔNG chạy CInterface (mock CLIP/fal ở unit); render thật chỉ local thủ công.

## Architecture
- Unit: pattern test hiện có (`tests/` cho thumbnail_style/generator nếu có). Mock CLIP + fal (không tải model / gọi mạng trong test).
- Integration: chạy `thumbnail_generator.generate(video_id)` trên 1 video có archival tốt + 1 video archival yếu (Estonia) → mở 6 ảnh, đánh giá.

## Related Code Files
- Create/Modify: `tests/test_thumbnail_*.py` (template, gate, fallback)
- Read: `tests/` pattern; `src/ai_operator/assembler/thumbnail_generator.py`
- Modify: `docs/user-setup-checklist.md` / `.env.example` (THUMB_RELEVANCE_MIN, hero fallback note nếu thêm toggle)

## Implementation Steps
1. Grep test thumbnail hiện có → theo pattern.
2. Test: **negative-space box chọn đúng vùng ít-bận** (chủ thể không bị đè); accent đỏ đúng vị trí; kicker degrade khi thiếu năm; gate filter; **Kontext toggle off → PIL grade, không gọi fal** (mock); fallback path (mock archival rớt → synthetic hero gọi).
3. Full suite (`tester` agent) — xanh.
4. Render thật 2 video → so 3 variant mỗi cái; **kiểm chữ không đè chủ thể**; calibrate ngưỡng relevance + cường độ Kontext nếu cần.
5. Docs: ghi template negative-space + gate + Kontext enhance + synthetic hero + config toggle.

## Success Criteria
- [ ] Test suite xanh (mock CLIP/fal, không giả logic).
- [ ] Render thật: Estonia → hero drama (không Viking Sally); video archival-tốt → ảnh thật; cả 2 chữ template mới.
- [ ] Docs + config cập nhật.

## Risk Assessment
- **Ngưỡng relevance cần chỉnh sau khi thấy ảnh thật:** để ở config; ghi giá trị calibrate + lý do.
- **Coupling test với chi tiết pixel:** test hành vi (accent word nào đỏ, gate loại/giữ), tránh assert từng pixel.
