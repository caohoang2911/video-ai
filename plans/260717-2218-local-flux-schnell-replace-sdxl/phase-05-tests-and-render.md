---
phase: 5
title: "(Optional) Thumbnail hero bằng fal FLUX"
status: pending
priority: P3
effort: "3h"
dependencies: [2]
---

# Phase 5 (Optional): Thumbnail hero bằng fal FLUX

## Overview
Surface RIÊNG, không bắt buộc: dùng fal FLUX sinh ẢNH HERO cinematic photoreal cho thumbnail, ghép text-block (POC đã có). Tách khỏi core replace-generator.

## Bối cảnh
- Thumbnail hiện tại = keyframe video + overlay chữ (`thumbnail_generator.py`), 3 variant thumb_a/b/c.
- POC thủ công đã dựng: SDXL hero + ghép chữ PIL (scratchpad `gen_hero_sdxl.py`, `compose_thumbnail.py`; output Desktop `thumbnail-ms-estonia-*.png`).
- fal FLUX cho hero = drama hơn, ít artifact chữ rác (vụ "NIGHT" méo mũi tàu ở SDXL).

## Requirements
- Functional: sinh hero photoreal 16:9 bằng **fal FLUX.1-dev** (bỏ prefix non-photoreal, `image_size=landscape_16_9`), ghép kicker + 2 dòng trắng + 1 dòng đỏ → thumb_a/b/c.
- Non-functional: chi phí 3 ảnh/video ~$0.075; an toàn policy (không gore).

## Architecture
- Thêm nhánh `thumbnail_hero()` trong `cloud_flux.py` hoặc tham số `photoreal=True` bỏ `_GENERIC_ILLUSTRATION_PREFIX` + set 16:9.
- Compositor PIL production từ POC → `assembler/thumbnail_hero.py` (grade tối + scrim trái + Impact + 1 đỏ).
- Sinh 3 hero khớp 3 title_option (đồng bộ A/B thumb_a/b/c).
- Toggle `THUMBNAIL_MODE=keyframe|hero`.

## Related Code Files
- Create: `src/ai_operator/assembler/thumbnail_hero.py` (port từ scratchpad `compose_thumbnail.py`)
- Modify: `src/ai_operator/media/cloud_flux.py` (option photoreal 16:9), `assembler/thumbnail_generator.py` (mode hero)
- Reference (throwaway POC): scratchpad `gen_hero_sdxl.py`, `compose_thumbnail.py`

## Implementation Steps
1. Thêm option photoreal/16:9 cho fal generate.
2. Port compositor POC thành module (font Impact/Arial Black, kicker brass, scrim trái, 1 highlight đỏ).
3. Sinh 3 hero variant khớp title_option.
4. Toggle `THUMBNAIL_MODE`.

## Success Criteria
- [ ] 3 thumbnail hero 1280×720 khớp A/B, chữ sắc nét, 1 điểm đỏ, an toàn policy.

## Risk Assessment
- **Scope creep:** P3 optional — không chặn core. Chỉ làm sau Phase 1-4.
- **Chi phí thêm:** +$0.075/video (không đáng kể).
