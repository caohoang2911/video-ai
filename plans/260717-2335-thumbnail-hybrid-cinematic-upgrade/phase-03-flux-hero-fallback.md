---
phase: 3
title: "fal image layer: Kontext enhance + synthetic hero"
status: pending
priority: P2
effort: "3-4h"
dependencies: [1, 2]
---

# Phase 3: fal image layer — Kontext enhance + synthetic hero

## Overview
Tầng ảnh fal cho thumbnail: (a) **FLUX Kontext** enhance hero chính (giữ chủ thể/bố cục, relight+grade+atmosphere nhẹ, KHÔNG bịa vật thể); (b) **synthetic FLUX hero** khi không archival nào qua cổng (Phase 2).

## Requirements
- Functional:
  - (a) Kontext enhance ẢNH hero (variant a — real archival HOẶC synthetic), instruction preserve-subject; toggle `THUMBNAIL_KONTEXT_ENHANCE` (default on); fal lỗi/off → PIL grade (Phase 1) thay thế.
  - (b) Archival rớt cổng → `cloud_flux.generate(photoreal=True, 16:9)` sinh hero drama → variant a.
  - variant b/c: **PIL grade only** (không Kontext) — cost + đa dạng A/B.
- Non-functional: chỉ tốn tiền khi cần (~$0.04/video: 1 Kontext, hoặc $0.025 synthetic hero); budget_guard ghi nhận; không để thumbnail trống.

## Architecture
- `cloud_flux`: thêm `photoreal` (bỏ prefix + 16:9) cho synthetic hero; thêm `kontext_edit(image_path, instruction)` gọi fal Kontext (verify model id `fal-ai/flux-pro/kontext`/`fal-ai/flux/kontext`; image→image). Cả 2 qua budget_guard.
- Instruction Kontext (real archival): "enhance cinematic lighting, contrast and depth; add subtle atmospheric haze; preserve the subject, composition and all real details exactly; do NOT add, remove or invent objects; keep photorealistic and natural." (≤ giữ tính defensible cho ảnh lịch sử.)
- `thumbnail_generator` flow: chọn hero (archival qua cổng > synthetic) → nếu toggle on: Kontext enhance → template Phase 1. variant b/c từ frame tốt kế tiếp + PIL grade.
- Prompt synthetic hero: `_hero_prompt(video)` cinematic dark từ title/topic.

## Related Code Files
- Modify: `src/ai_operator/media/cloud_flux.py` (`photoreal` param; `kontext_edit()`)
- Modify: `src/ai_operator/assembler/thumbnail_generator.py` (chọn hero + enhance + b/c PIL)
- Modify: `src/ai_operator/config.py` (`THUMBNAIL_KONTEXT_ENHANCE: bool = True`)

## Implementation Steps
1. Verify fal Kontext model id (1 call thử/ doc). Thêm `kontext_edit()` + `photoreal` vào `cloud_flux` (budget_guard).
2. `_hero_prompt(video)` synthetic hero.
3. Flow thumbnail_generator: hero-pick → Kontext (nếu on) → Phase-1 template; b/c PIL grade.
4. Fallback: Kontext/fal lỗi → PIL grade hero (không trống).

## Success Criteria
- [ ] Estonia (archival rớt) → synthetic hero drama; archival tốt → real photo + Kontext enhance nhẹ (chủ thể giữ nguyên, không bịa).
- [ ] Toggle off → hero PIL grade, không gọi fal.
- [ ] b/c là PIL grade; chi phí/video ~$0.04 log đúng.

## Risk Assessment
- **Kontext đổi chủ thể quá tay (mất "thật")**: instruction preserve mạnh + cường độ thấp; test so ảnh trước/sau; nếu drift → giảm strength hoặc tắt cho real archival.
- **Model id Kontext sai/không có trên fal**: verify sớm (bước 1); nếu không có, degrade sang PIL-only enhance cho real + synthetic hero cho archival-rớt (plan vẫn đứng).
- **Chi phí bất ngờ (Kontext >1MP → 2MP)**: ép ≤1MP khi có thể.
