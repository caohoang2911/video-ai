---
phase: 3
title: "Cost / budget / docs"
status: completed
priority: P2
effort: "1.5h"
dependencies: [2]
---

# Phase 3: Cost, budget guard, docs

## Overview
Generator giờ tốn tiền mỗi ảnh (trước SDXL free). Đảm bảo budget_guard/estimator phản ánh đúng và docs cập nhật.

## Requirements
- Functional: mỗi ảnh fal đi qua `check_and_reserve`/`record_actual` (đã có trong `cloud_flux`); tổng/video + /tháng nằm trong `MONTHLY_BUDGET`.
- Non-functional: docs mô tả tier generator = fal FLUX (chính) + SDXL (fallback offline); note license + cost/ảnh.

## Architecture
- `constants.py`: `FAL_FLUX_USD_PER_IMAGE = 0.025` đã có → xác nhận khớp giá dev ($0.025/MP, ảnh ~1MP). Nếu dùng flux-pro đổi hằng.
- Cân nhắc cảnh báo: khi `force_generate` (mọi beat = fal), 1 video ~30 ảnh = $0.75 → log ước tính trước khi chạy để tránh bất ngờ.
- Docs: `system-architecture.md` (tier), `.env`/README (FAL_KEY bắt buộc khi backend=fal_flux; note output fal thương mại OK), `project-changelog.md`.

## Related Code Files
- Read/verify: `src/ai_operator/cost/estimator.py`, `src/ai_operator/constants.py`, `cost/budget_guard.py`
- Modify: `docs/system-architecture.md`, `docs/project-changelog.md`, `.env` note / README

## Implementation Steps
1. Verify `estimate_step("fal", images=n)` khớp thực tế; giá 0.025 đúng.
2. (Tuỳ chọn) thêm 1 dòng log ước tính chi phí ở đầu `acquire` khi `force_generate` + backend=fal.
3. Docs tier + license + cost.
4. Changelog entry (đổi generator sang fal FLUX).

## Success Criteria
- [ ] Chi phí mỗi render ghi nhận đúng qua ledger; không vượt `MONTHLY_BUDGET` bất ngờ.
- [ ] Docs đọc là hiểu: fal chính, SDXL fallback, FAL_KEY bắt buộc, ~$0.025/ảnh, output thương mại OK.

## Risk Assessment
- **Budget nổ trong force_generate hàng loạt:** log ước tính trước; budget_guard chặn khi vượt (đã có).
