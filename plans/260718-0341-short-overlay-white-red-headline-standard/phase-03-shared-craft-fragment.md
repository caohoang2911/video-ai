---
phase: 3
title: "Shared Craft Fragment"
status: pending
priority: P2
effort: "0.5d"
dependencies: [2]
---

# Phase 3: Shared Craft Fragment

## Overview
DRY phần **nội dung**: craft "searchable entity + information-gap + inverted-U + never-clickbait-past-facts" hiện **trùng 2 nơi** — long ở `prompts/script_system.md:118-167` (external), short hard-code trong `short_script_generator.py`. Tách ra **1 fragment dùng chung** để hết trôi lệch. (Deferrable — feature chạy được không có phase này; nhưng đúng ý "đồng bộ thuật toán".)

## Requirements
- Functional: 1 nguồn duy nhất cho quy tắc craft entity+gap; long + short cùng consume.
- Non-functional: không đổi hành vi sinh (chỉ gom chữ); mỗi surface vẫn giữ constraint riêng (long <60c metadata; short 7-14 từ muted; batch-uniqueness).

## Architecture
- Tạo `prompts/_title_craft.md`: chứa lõi bất biến — entity anchor (cho searchability), information-gap = MIDDLE of scale (inverted-U, giữ payoff), never clickbait past facts, đỏ = 1 phần tử stake.
- `prompt_builder.py`: hàm `load_title_craft()` đọc fragment; chèn vào system prompt long (thay đoạn craft inline ở `script_system.md`) và vào `_SYSTEM` của `short_script_generator.py`.
- Mỗi surface thêm phần *delta* riêng (long: 3 formula + <60c; short: 7-14 từ, 2 dòng, muted-autoplay, partners) — KHÔNG nhét vào fragment chung.
- KISS: nếu chèn runtime làm prompt khó đọc/diff, chấp nhận fragment là "single source" và 2 prompt `include` bằng cách build-time concat trong `prompt_builder` (đã có `PROMPTS_DIR` pattern).

## Related Code Files
- Create: `prompts/_title_craft.md`
- Modify: `prompts/script_system.md` (thay đoạn craft inline bằng tham chiếu/placeholder)
- Modify: `src/ai_operator/content/prompt_builder.py` (`load_title_craft()` + chèn)
- Modify: `src/ai_operator/content/short_script_generator.py` (`_SYSTEM` chèn fragment)

## Implementation Steps
1. Trích lõi craft chung từ `script_system.md:118-167` + rules short #7/#8 (P2) → `_title_craft.md` (chỉ phần bất biến, giữ 1 bản chữ tốt nhất).
2. `prompt_builder.load_title_craft()`; long system prompt chèn fragment (giữ delta 3-formula riêng).
3. `short_script_generator._SYSTEM` chèn fragment (giữ delta 7-14 từ/partners riêng).
4. Regenerate 1 long + 1 short script → so nội dung không lệch chuẩn cũ (không regression chất lượng).

## Success Criteria
- [ ] 1 file craft chung; long + short cùng đọc.
- [ ] Không đoạn craft entity+gap nào còn trùng lặp giữa 2 nơi.
- [ ] Script long + short sinh ra vẫn đạt chuẩn (spot-check 1 mỗi loại).

## Risk Assessment
- **Prompt drift làm giảm chất lượng title** (long đã data-backed, sticky). → Mitigate: chỉ gom, không đổi câu chữ đã verified; diff prompt trước/sau; spot-check output. Nếu chất lượng giảm → revert, giữ delta inline.
- **YAGNI check:** nếu gom làm phức tạp hơn lợi ích, dừng ở "2 prompt tham chiếu cùng 1 danh sách rule" mức tối thiểu — không over-engineer include system.
