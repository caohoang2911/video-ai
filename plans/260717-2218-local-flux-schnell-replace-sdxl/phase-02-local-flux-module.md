---
phase: 2
title: "fal FLUX làm generator chính (+ toggle)"
status: completed
priority: P1
effort: "2h"
dependencies: [1]
---

# Phase 2: fal FLUX làm generator chính, SDXL thành fallback offline

## Overview
Đảo thứ tự tier generate: **fal FLUX.1-dev = generator chính**, local SDXL = fallback offline (mất mạng/fal lỗi). Điều khiển qua `IMAGE_GEN_BACKEND`.

## Requirements
- Functional: `_generate_visual` gọi fal TRƯỚC, SDXL sau (khi `IMAGE_GEN_BACKEND=fal_flux`); `sdxl` = giữ hành vi cũ (rollback).
- Non-functional: source label lưu đúng ("fal" vs "sdxl"); timeout fal hợp lý; không phá coherence-batch.

## Architecture
- `config.py`: `IMAGE_GEN_BACKEND: str = "fal_flux"` (giá trị khác: `sdxl`).
- `visual_fetcher._generate_visual` hiện: SDXL → (except) → fal. Đổi thành:
  - `fal_flux`: thử fal (timeout ~30-60s) → except → local SDXL (offline fallback) → except → None.
  - `sdxl`: y như cũ (SDXL → fal).
- `FAL_TIMEOUT_SEC` hiện 30 → cân nhắc nâng 60 (fal queue lúc tải cao). Giữ `LOCAL_GEN_TIMEOUT` cho SDXL fallback.
- Giữ nguyên `is_diagram` + prefix non-photoreal trong `cloud_flux.generate` (b-roll tài liệu, không photoreal).

## Related Code Files
- Modify: `src/ai_operator/config.py` (`IMAGE_GEN_BACKEND`)
- Modify: `src/ai_operator/media/visual_fetcher.py` (`_generate_visual` thứ tự tier, timeout)
- Read: `src/ai_operator/media/cloud_flux.py` (không cần đổi cho b-roll)

## Implementation Steps
1. Thêm `IMAGE_GEN_BACKEND` vào config.
2. Refactor `_generate_visual`: hàm chọn thứ tự `(cloud_flux, local_sdxl)` vs `(local_sdxl, cloud_flux)` theo toggle, loop thử lần lượt, trả `(path, source_label)`.
3. Đổi source label theo generator thực tế trả về (đã có: "fal"/"sdxl").
4. Nâng `FAL_TIMEOUT_SEC` nếu cần; giữ retry/backoff sẵn trong `cloud_flux`.
5. Xác nhận `AI_OPERATOR_DISABLE_SDXL` / disable-image-gen vẫn tắt được toàn bộ generate.

## Success Criteria
- [ ] `IMAGE_GEN_BACKEND=fal_flux` → beat generate dùng fal; fal lỗi → tự rơi xuống SDXL offline.
- [ ] `IMAGE_GEN_BACKEND=sdxl` → hành vi cũ nguyên vẹn (rollback an toàn).
- [ ] asset source lưu đúng nguồn.

## Risk Assessment
- **fal lỗi giữa render:** SDXL fallback giữ render sống (miễn có weights local — vẫn còn 13GB cache).
- **Đổi thứ tự phá test hiện có:** grep test `_generate_visual`/visual_fetcher, cập nhật kỳ vọng.
