---
phase: 2
title: Headline Content Gen
status: completed
priority: P1
effort: 0.5d
dependencies:
  - 1
---

# Phase 2: Headline Content Gen

## Overview
Phần **"đồng bộ thuật toán"**: cho short tự sinh một **overlay headline** đúng standard (curiosity-gap, middling concreteness, 7-14 từ, partner với metadata title), thay cho `text_overlay` ≤6-từ hiện tại. Wire nội dung vào renderer P1.

## Requirements
- Functional: schema short mang headline 2 phần (setup + gap) để renderer tô đỏ đúng dòng gap.
- Functional: prompt short sinh headline theo inverted-U (1 known anchor, giấu payoff), 7-14 từ, khác metadata `title` (partners).
- Non-functional: back-compat — script cũ (chỉ có `text_overlay`) vẫn render (fallback).

## Architecture
- **Schema (`short_schema.py`):** thêm `overlay_headline: str` (2 dòng, ngăn bằng `\n`; setup ở dòng 1, gap ở dòng 2), `min_length`≈15, giới hạn từ 7-14 qua validator. Giữ `text_overlay` (deprecated, default) làm fallback cho script cũ. Renderer ưu tiên `overlay_headline`, else `text_overlay`.
  - Validator: đếm từ 7-14; phải có ≥1 known anchor (entity/năm/số) NHƯNG không được vừa-số-vừa-năm-vừa-toll (gate inverted-U mềm: cảnh báo, không cứng); dòng gap không kết bằng câu giải payoff.
- **Prompt (`short_script_generator.py` rules #7/#8):**
  - #8 đổi: `overlay_headline` = curiosity-gap headline 7-14 từ / 2 dòng; dòng 1 setup (chủ thể+hành động, bám entity vừa đủ), dòng 2 khuếch đại stake/scale/số **giữ payoff không giải**. Bỏ ép "≤6 từ, strongest word first".
  - #7 (`title`) nới: entity + angle; **bỏ ép "phải có concrete stake/number"** (đẩy specificity nặng về title là nơi search đọc, nhưng không bắt buộc số). Vẫn giữ entity (searchable) + batch-unique prefix.
  - Nhấn: overlay ≠ title (partners); overlay giữ middling, title giữ searchable.
  - Cập nhật JSON schema mẫu ở cuối prompt (`short_script_generator.py:78`) thêm `overlay_headline`.
- **Wire:** `short_builder.py:108` đọc `script.get("overlay_headline") or script.get("text_overlay")` → truyền vào `_pinned_title_fx`.

## Related Code Files
- Modify: `src/ai_operator/content/short_schema.py` (field + validators)
- Modify: `src/ai_operator/content/short_script_generator.py` (rules #7/#8 + JSON mẫu + `_SYSTEM`)
- Modify: `src/ai_operator/assembler/short_builder.py` (đọc field mới, fallback)

## Implementation Steps
1. `short_schema.py`: thêm `overlay_headline` + validators (word 7-14; known-anchor present; gap không giải). Field-level default `""`; renderer fallback về `text_overlay`.
2. `short_script_generator.py`: viết lại rule #8 (headline), nới #7 (title), cập nhật JSON mẫu + note partners/inverted-U. Giữ curiosity-gap contract cũ (rules 1-6) nguyên.
3. `short_builder.py`: chọn `overlay_headline or text_overlay`; nếu là headline 1 chuỗi không `\n`, để renderer auto-split (setup/gap theo dấu `—`/`.`); nếu có `\n` tôn trọng.
4. Render lại 1 batch short thật để kiểm nội dung sinh ra khớp standard (thủ công review 2-3 short).

## Success Criteria
- [ ] Short mới sinh `overlay_headline` 7-14 từ, 2 dòng, gap giữ payoff.
- [ ] `title` và `overlay_headline` khác nhau (partners), cùng mirror entity keyword.
- [ ] Script cũ (chỉ `text_overlay`) vẫn render không lỗi (fallback).
- [ ] Validator bắt được headline quá dài / thiếu anchor / giải payoff.

## Risk Assessment
- **LLM trả `overlay_headline` 1 dòng, không tách được setup/gap** → renderer auto-split theo dấu; nếu không có → cả headline off-white, đỏ rơi vào cụm số/từ cuối (vẫn hợp lệ). Không hard-fail.
- **Over-anchoring vẫn lọt** (inverted-U là mềm) → chấp nhận; đây là hướng, không phải ngưỡng cứng (caveat research: ngưỡng web không port sang Shorts).
- **Batch cũ trên đĩa** không có field → fallback đảm bảo không vỡ render lại.
