# Phase 03 — Precise Event Anchor

**Priority:** P1 · **Status:** pending · Depends: P02 (độc lập với P04).

## Context
`_archival_anchor` (`visual_fetcher.py:165-187`) = `title.split(":")[0]`. Phụ thuộc dấu `:`; title
không có delimiter → anchor = cả câu hook nhiễu → **cả query Commons lẫn subject của gate** đều sai.
Đã có sẵn: `Topic.title` (event title sạch, anchor đã ưu tiên nó), `ScriptOutput.event_year`
(`schema.py:102`).

## Key insight
Anchor tốt lên → cả tìm ảnh (Commons) lẫn chấm điểm (gate) lẫn prompt synthetic đều chính xác hơn.
Dùng **một nguồn anchor duy nhất** cho cả 3 (DRY). KHÔNG thêm field schema mới trừ khi cần
(YAGNI) — reuse `Topic.title` + `event_year`.

## Requirements
- **F:** Anchor robust: tách entity theo **nhiều delimiter** (`:`, `—`, `–`, `--`, `|`), fallback chain,
  bỏ tiền tố hook nếu có; kèm `event_year` khi có → `"{entity} {year}"`.
- **F:** Dùng anchor này đồng nhất cho: query Commons (`_fetch_archival`), subject gate
  (`_subject_text`/`_relevance_gate`), và prompt synthetic (`_hero_prompt`, xem P04).
- **NF:** Không đổi hành vi khi `Topic.title` đã sạch (không hồi quy các case đang đúng).

## Architecture
```
Topic.title (ưu tiên) / video.title  ──► extract_entity()  ──► "{entity} {event_year?}"
        │                                                          │
        ├── Commons query (_fetch_archival)                        │  (một hàm dùng chung)
        ├── gate subject (_relevance_gate)                         │
        └── synthetic prompt (_hero_prompt)  ◄────────────────────┘
```

## Related code files
- **Modify:** `src/ai_operator/media/visual_fetcher.py` — `_archival_anchor` (robustify + kèm year)
- **Modify:** `src/ai_operator/assembler/thumbnail_generator.py` — `_subject_text` reuse anchor; `_hero_prompt` dùng entity+year
- **(Đọc):** `src/ai_operator/content/schema.py` (`event_year`), `db/models.py` (`Topic.title`)

## Implementation steps
1. Viết `extract_entity(title)` (nhiều delimiter, bỏ hook prefix, trim); giữ trong `visual_fetcher` hoặc util nhỏ.
2. Lấy `event_year` từ DB/script output cho video (tra cứu 1 lần, an toàn None).
3. `_archival_anchor` trả `"{entity} {year}".strip()`; giữ fallback ""/topic khi thiếu.
4. Xác nhận `_subject_text` (gate) và `_hero_prompt` (synthetic) đều gọi anchor này.
5. Compile-check.

## Todo
- [ ] `extract_entity` đa-delimiter + bỏ hook prefix
- [ ] kèm `event_year`
- [ ] anchor dùng chung cho query/gate/prompt
- [ ] không hồi quy case title sạch
- [ ] compile-check

## Success criteria
- Title "Butter, Cheese, and Ammunition — Lusitania's Manifest, 1915" → anchor ≈ "Lusitania ... 1915" (không phải cả câu).
- Title có `:` vẫn ra entity đúng như cũ.

## Risks
- `event_year` không phải lúc nào cũng có → chỉ append khi có.
- Over-trim làm mất entity → test vài mẫu title thật.

## ⚠️ Đánh giá trong lúc làm (Unresolved #3)
Nếu `extract_entity` + `event_year` vẫn cho anchor nhiễu trên nhiều title → cân nhắc thêm field
`event_subject` (LLM điền entity sạch) vào schema. **Chỉ thêm nếu chứng minh cần** — hỏi người dùng trước khi thêm field.

## Next steps → P05 (test anchor + gate).
