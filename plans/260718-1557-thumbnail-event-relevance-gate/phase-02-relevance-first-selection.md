# Phase 02 — Relevance-First Hero Selection

**Priority:** P0 · **Status:** pending · Depends: P01.

## Context
Hiện `_gated_pools` (`thumbnail_generator.py:173-183`) gate archival rồi xếp bằng
`thumbnail_frame_score.rank()` (**thẩm mỹ**: contrast/edge). `_pick_hero` (`:197-211`) lấy
`archival_ranked[0]`. → ảnh *ít liên quan nhưng tương phản cao* thắng ảnh *đúng sự kiện nhưng phẳng*.
Người dùng chốt: **relevance-first, thẩm mỹ là tie-break**.

## Key insight
Gate hiện là pass/fail rồi vứt điểm relevance đi. Giữ lại điểm relevance từ P01 và dùng nó làm khóa
xếp hạng chính; frame-score chỉ phá hòa.

## Requirements
- **F:** Trong đám ảnh **qua gate**, hero = ảnh **relevance cao nhất**; nếu chênh lệch relevance ≤ epsilon
  thì mới xét frame-score (thẩm mỹ) để chọn.
- **F:** `_relevance_gate`/`_gated_pools` trả kèm điểm (không chỉ list path) để P02 xếp — hoặc scorer cache điểm.
- **NF:** DRY — không gọi Gemini 2 lần/ảnh (gate + rank). Chấm 1 lần, giữ điểm.

## Architecture
```
score each archival → [(path, rel)]           (1 lần, từ P01)
keep rel >= THRESHOLD
sort key = (-rel, -frame_score)  # relevance chính, thẩm mỹ tie-break
hero = sorted[0]
```
- `epsilon` nhỏ (vd 0.05) để 2 ảnh "gần bằng relevance" thì ưu tiên ảnh đẹp hơn — tránh thắng do noise 0.01.

## Related code files
- **Modify:** `src/ai_operator/assembler/thumbnail_generator.py` — `_relevance_gate` (trả điểm), `_gated_pools`, `_pick_hero`, `_thumbnail_sources`
- **(Có thể) Modify:** `src/ai_operator/assembler/thumbnail_frame_score.py` — nếu cần expose điểm thô để blend/tie-break

## Implementation steps
1. Cho `_relevance_gate` trả `list[tuple[Path, float]]` (đã lọc theo threshold).
2. `_gated_pools`: xếp archival theo `(-rel, -frame_score)`; `others` giữ frame-score (chưa có relevance ở P02, sẽ gate ở P04).
3. `_pick_hero`: lấy phần tử đầu (đã relevance-first).
4. Đảm bảo `_thumbnail_sources` (variant a/b/c) dùng cùng thứ tự.
5. Compile-check.

## Todo
- [ ] gate trả kèm điểm
- [ ] sort `(-rel, -frame_score)` + epsilon tie-break
- [ ] `_pick_hero` dùng thứ tự mới
- [ ] không double-call Gemini
- [ ] compile-check

## Success criteria
- Cho 2 ảnh: A đúng sự kiện/phẳng (rel .8, frame .3) vs B sai/nét (rel .3, frame .9) → hero = A.
- 2 ảnh cùng đúng sự kiện → chọn ảnh nét hơn.

## Risks
- Điểm relevance thô (Gemini) có thể "bằng nhau" nhiều ảnh → epsilon + frame-score tie-break xử lý.

## Next steps → P03 (anchor chính xác) ∥ P04 (gate non-archival).
