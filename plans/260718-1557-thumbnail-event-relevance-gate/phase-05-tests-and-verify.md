# Phase 05 — Tests + Verify

**Priority:** P0 (chốt) · **Status:** pending · Depends: P01–P04.

## Context
Explore không thấy test nào assert gate loại ảnh sai-sự-kiện → coverage đang hở. Phase này đóng hở đó
và verify observability (fail-loud) hoạt động.

## Key insight
Test scorer bằng **fake/stub** (không gọi Gemini thật trong unit test — deterministic, không tốn token/không
cần key). Test hành vi gate/selection, không test chất lượng model.

## Requirements
- **F:** Test `_relevance_gate` loại ảnh có điểm < threshold, giữ ảnh ≥ threshold (inject fake scorer).
- **F:** Test relevance-first: ảnh rel cao/thẩm mỹ thấp thắng ảnh rel thấp/thẩm mỹ cao (P02).
- **F:** Test fail-loud: scorer không available → có log WARNING/ops signal, không crash (P01).
- **F:** Test `extract_entity` trên vài title thật (`:`, em-dash, không delimiter) (P03).
- **F:** Test gate áp cho `others` khi archival rỗng (P04).
- **NF:** Toàn bộ suite hiện có vẫn xanh (không hồi quy). Chạy qua `tester` agent.

## Related code files
- **Create:** `tests/test_thumbnail_relevance_gate.py`
- **Create/Modify:** `tests/test_thumbnail_layout.py` hoặc file thumbnail test hiện có (nếu trùng scope)
- **(Đọc):** cấu trúc fixture ở `tests/` hiện tại để theo convention

## Implementation steps
1. Fake scorer: `available()->True`, `score()` trả điểm định sẵn theo tên/đường dẫn ảnh.
2. Viết test gate keep/drop theo threshold.
3. Viết test relevance-first tie-break.
4. Viết test fail-loud (monkeypatch available=False → assert WARNING captured, gate không raise).
5. Viết test `extract_entity` bảng case.
6. Chạy full suite; fix tới khi xanh.
7. **Calibrate threshold** (Unresolved #1): render/score vài video thật, xem điểm Gemini phân bố → chốt
   `THUMB_RELEVANCE_MIN` với người dùng.

## Todo
- [ ] fake scorer fixture
- [ ] test keep/drop theo threshold
- [ ] test relevance-first tie-break
- [ ] test fail-loud observability
- [ ] test `extract_entity`
- [ ] test gate `others`
- [ ] full suite xanh (qua `tester`)
- [ ] calibrate threshold với người dùng

## Success criteria
- Tất cả test mới pass; suite cũ không hồi quy.
- Có bằng chứng gate loại được ảnh sai-sự-kiện (test đỏ trước fix P01, xanh sau).
- Threshold chốt dựa trên dữ liệu thật, không đoán.

## Risks
- Test phụ thuộc Gemini thật → tránh; luôn inject fake trong unit test.
- Calibrate cần render thật (tốn fal/Gemini) → làm trên 3–5 video mẫu, không hàng loạt.

## Next steps
- `/ck:code-review` trước khi merge; cập nhật `docs/` nếu đổi hành vi thumbnail (Docs impact: minor).
- Cập nhật memory `videoai-thumbnail-hybrid-plan-inflight` sau khi ship.
