---
phase: 4
title: Tests + Docs
status: completed
priority: P1
effort: 0.5d
dependencies:
  - 1
  - 2
  - 3
---

# Phase 4: Tests + Docs

## Overview
Test renderer + schema + regression thumbnail; cập nhật docs ghi nhận standard. Đóng plan.

## Requirements
- Functional: unit test phủ nhánh mới; regression thumbnail xanh.
- Non-functional: theo `development-rules.md` — không fake/mocks cheat qua build; test verify code cuối cùng.

## Architecture
Test theo tầng: (1) primitives `headline_text` (thuần PIL, unit hoá được), (2) banner render + accent, (3) schema validators, (4) fallback back-compat, (5) regression thumbnail sau extract.

## Related Code Files
- Create/Modify: `tests/` — test file cho `headline_text` + overlay banner; mở rộng test short_schema; giữ/chạy test thumbnail hiện có.
- Modify: `docs/codebase-summary.md` hoặc `docs/design-guidelines.md` — ghi standard overlay (1-2 đoạn, link plan).

## Implementation Steps
1. `test_headline_text`: `accent_targets` (số → dòng số; lẻ dòng → cụm số; không số → dòng cuối/từ cuối) — port từ hành vi `_accent_targets` cũ để chứng minh extract không đổi logic.
2. `test_headline_banner`: render trắng/đỏ với case title/upper; assert kích thước banner, có pixel đỏ ở dòng gap, trong suốt nền; wrap 2-3 dòng.
3. `test_short_schema`: `overlay_headline` word 7-14 pass; <7/>14 fail; thiếu anchor fail/warn; fallback `text_overlay` khi thiếu field.
4. `test_short_builder` (hoặc smoke): `_pinned_title_fx` trả `movie=...overlay` khi có headline, None khi rỗng; đọc `overlay_headline or text_overlay`.
5. **Regression:** chạy toàn bộ test thumbnail hiện có sau khi `thumbnail_style` import từ `headline_text` → phải xanh y cũ.
6. Full suite (`pytest`) xanh; cập nhật docs.

## Success Criteria
- [ ] Unit tests mới xanh (headline_text, banner, schema, builder).
- [ ] Test thumbnail cũ xanh (không regression sau extract).
- [ ] Full `pytest` xanh (khớp baseline ~407).
- [ ] Docs ghi standard overlay + link plan.

## Risk Assessment
- **Test ffmpeg overlay chậm/khó CI** → tách: logic banner (PIL) unit test thuần; phần `movie` filter kiểm ở smoke/manual render (không đưa ffmpeg nặng vào unit).
- **Regression baseline count đổi** do thêm test → cập nhật con số kỳ vọng, không tắt test để cho pass.
