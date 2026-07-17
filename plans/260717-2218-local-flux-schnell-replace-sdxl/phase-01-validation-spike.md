---
phase: 1
title: "FAL_KEY + smoke test & quality gate"
status: completed
priority: P1
effort: "30-45m"
dependencies: []

# RESULT (2026-07-17): GO
# - FAL_KEY thật hoạt động (len 69). 3/3 ảnh sinh OK: 2.8–5.5s/ảnh (SDXL local 90–300s).
# - Chất lượng > SDXL rõ trên cả 3 loại beat (diagram/illustration/reenactment), bám prompt, prefix non-photoreal áp đúng.
# - budget_guard ghi 3 dòng visual_fal @ $0.0275 (0.025×buffer1.1). Ledger chuẩn.
# - Ảnh mẫu: scratchpad smoke_{diagram,illustration,reenactment}.jpg
---

# Phase 1: FAL_KEY + smoke test & quality gate

## Overview
Điền FAL_KEY thật, xác nhận `cloud_flux.generate` chạy được và ảnh FLUX.1-dev đẹp hơn SDXL trên prompt tương đương. Cửa GO/NO-GO rẻ (không tải model, không đụng đĩa).

## Requirements
- Functional: 1 call `cloud_flux.generate(prompt, is_diagram=...)` thành công, trả ảnh local.
- Non-functional: xác nhận budget_guard reserve/record đúng (không nổ MONTHLY_BUDGET); đo latency/ảnh.

## Architecture
- FAL_KEY: lấy tại https://fal.ai/dashboard/keys → `.env` `FAL_KEY=<key>` (thay placeholder `# opti...`).
- Smoke test: gọi trực tiếp `cloud_flux.generate` với 3-4 prompt thật (lấy `image_prompt` từ script.json cũ: 1 map/diagram, 1 period illustration, 1 reenactment).
- So sánh: đặt cạnh ảnh SDXL tương ứng (có sẵn trong assets cũ / hoặc regen nhanh) — đánh giá chi tiết, bám prompt.

## Related Code Files
- Modify: `.env` (FAL_KEY)
- Read: `src/ai_operator/media/cloud_flux.py` (đã có `generate()`), `cost/budget_guard.py` (reserve/record)
- Create: scratchpad smoke script (throwaway)

## Implementation Steps
1. Điền FAL_KEY thật vào `.env`; verify `settings.FAL_KEY` không còn bắt đầu bằng `#`.
2. Chạy `cloud_flux.generate("editorial illustration, a 1917 harbor explosion aftermath", is_diagram=True)` → mở ảnh.
3. Lặp 3-4 prompt đại diện; đặt cạnh SDXL.
4. Kiểm log budget_guard: reserve → record actual, ledger cập nhật.
5. Chốt GO (fal đẹp hơn + key ok) / NO-GO (chất lượng không hơn → cân nhắc FLUX1.1-pro hoặc dừng).

## Success Criteria
- [ ] `settings.FAL_KEY` hợp lệ, call fal thành công (không `Authentication required`).
- [ ] FLUX ≥ SDXL trên ≥3/4 ảnh (bám prompt, chi tiết, ít artifact).
- [ ] budget_guard ghi nhận chi phí đúng (~$0.025/ảnh).

## Risk Assessment
- **Key sai/hết credit:** báo lỗi rõ; user nạp credit fal.
- **Chất lượng không hơn kỳ vọng:** thử `fal-ai/flux-pro/v1.1` (đổi FAL_MODEL) trước khi bỏ hướng.
