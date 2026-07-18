# Phase 04 — Gate Non-Archival Pool + Entity-Rich Synthetic

**Priority:** P1 · **Status:** pending · Depends: P02 (độc lập với P03; cần anchor của P03 cho prompt).

## Context
- `_gated_pools` chỉ gate `archival` (`thumbnail_generator.py:178`). Khi không archival nào đạt và
  `FAL_KEY` unset → hero fallback `pool[0]` từ `others` (stock/video/gen) — **không hề gate**, mà những
  ảnh này lấy bằng query keyword-thuần, không neo sự kiện (`visual_fetcher.py:215,227`) → generic.
- `_hero_prompt` (`:234-242`) = `subject` + mood chung chung, **không entity/năm** → frame mờ ảo vô nghĩa;
  subject rỗng tụt về `settings.NICHE`.

## Key insight
Mọi ứng viên **được đưa lên làm hero** phải qua cùng cửa relevance, không chỉ archival. Prompt synthetic
phải mang entity thật (từ anchor P03) để FLUX vẽ đúng chủ thể.

## Requirements
- **F:** Gate cả `others` bằng relevance_scorer trước khi được chọn làm hero fallback (dùng chung threshold/thang P01).
- **F:** `_hero_prompt` chèn entity + `event_year` (anchor P03) vào prompt, không chỉ mood chung.
- **NF:** Ảnh generic không đạt relevance → thà đi synthetic (nếu FAL_KEY) còn hơn phủ ảnh sai sự kiện;
  nếu cả hai fail → fallback cuối + log (không để publish ảnh rõ ràng sai mà không cảnh báo).

## Architecture
```
archival gated (P01/P02) ─┐
                          ├─► nếu rỗng → others GATED (mới) ─┐
                          │                                  ├─► nếu rỗng → synthetic (entity-rich prompt)
                          │                                  │           └─► nếu rỗng → best-frame + log ops
hero = ứng viên relevance cao nhất trong nhánh chọn được
```

## Related code files
- **Modify:** `src/ai_operator/assembler/thumbnail_generator.py` — `_gated_pools` (gate `others`), `_pick_hero` (thứ tự ưu tiên), `_hero_prompt` (entity+year)

## Implementation steps
1. `_gated_pools`: áp `_relevance_gate` cho `others` (chấm relevance, lọc threshold, xếp relevance-first).
2. `_pick_hero`: thứ tự archival-gated → others-gated → synthetic → best-frame(+log).
3. `_hero_prompt`: build từ anchor P03 (`extract_entity`+`event_year`) → prompt kèm entity/năm + mood.
4. Compile-check.

## Todo
- [ ] gate `others` bằng relevance_scorer
- [ ] `_pick_hero` thứ tự mới có log ở fallback cuối
- [ ] `_hero_prompt` entity-rich
- [ ] compile-check

## Success criteria
- Không archival đạt + có clip biển hiện đại generic → clip đó **không** thành hero (rớt gate) → đi synthetic đúng entity.
- Prompt synthetic chứa tên sự kiện/năm, không phải chỉ "Forgotten Disasters of History".

## Risks
- Gate `others` tăng số Gemini call → chỉ chấm khi cần fallback (archival rỗng), không chấm thừa.
- Cost synthetic (FLUX) khi archival hay rớt → theo dõi; threshold P01 không nên quá gắt (calibrate P05).

## Next steps → P05.
