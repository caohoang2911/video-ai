---
phase: 4
title: "Tests + render end-to-end"
status: completed
priority: P1
effort: "2h"
dependencies: [2]
---

# Phase 4: Tests + render end-to-end

## Overview
Đảm bảo đổi generator không phá pipeline: unit test toggle/thứ tự tier (mock fal+sdxl) + 1 render thật qua fal.

## Requirements
- Functional: test `_generate_visual` chọn đúng generator theo `IMAGE_GEN_BACKEND`, và fallback fal→SDXL khi fal raise.
- Non-functional: 1 render `force_generate` thật qua fal → ảnh hợp lệ, coherence ≥80%, chi phí ghi nhận.

## Architecture
- Unit test: monkeypatch `cloud_flux.generate` + `local_sdxl.generate` trả ảnh giả; assert thứ tự gọi theo toggle + fallback khi fal ném exception. KHÔNG gọi fal thật trong test (mock hết).
- Integration: chạy CLI `force_generate` 1 short/main ngắn với backend=fal_flux (tốn ~$0.2-0.75 thật) → kiểm ảnh + coherence log.

## Related Code Files
- Create: `tests/test_visual_fetcher_backend_toggle.py` (hoặc thêm vào test visual_fetcher hiện có)
- Read: `tests/` (pattern mock), `src/ai_operator/assembler/commands.py` (lệnh force_generate)

## Implementation Steps
1. Grep test visual_fetcher hiện có → theo pattern.
2. Test toggle + fallback (mock cả 2 generator).
3. Chạy full suite (`tester` agent) — xanh.
4. Render thật 1 video `force_generate` backend=fal → mở ảnh, xác nhận chất lượng + coherence ≥80% + ledger cập nhật.

## Success Criteria
- [ ] Test suite xanh (mock chỉ thay call mạng, không giả logic).
- [ ] Render thật: mọi beat có ảnh fal hợp lệ, 0 frame lỗi, coherence ≥80%.
- [ ] Ledger chi phí khớp số ảnh × $0.025.

## Risk Assessment
- **Test gọi fal thật (tốn tiền/chậm/CI fail):** cấm — mock hoàn toàn ở unit; render thật chỉ chạy local thủ công.
- **Coherence tụt:** fal FLUX thường coherent hơn SDXL; nếu vẫn tụt, cố định seed/prefix thay vì nới threshold.
