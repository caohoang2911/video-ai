---
phase: 1
title: "Subject-preserving template (negative-space text + typography + grade)"
status: pending
priority: P1
effort: "4-5h"
dependencies: []
---

# Phase 1: Subject-preserving cinematic template

## Overview
Đặt headline vào **vùng trống**, KHÔNG đè chủ thể; typography đậm/sạch/mobile-readable; PIL cinematic grade (brightness/contrast/sharpness/vignette). Đây là thay đổi cốt lõi từ brief.

## Requirements
- Functional:
  - **Negative-space placement**: dò vùng "ít chi tiết" (trời/nước) → đặt kicker + block chữ ở đó; chủ thể (vùng nhiều chi tiết) KHÔNG bị đè. Không có vùng trống đủ → **letterbox bar cinematic** (thanh gradient trên HOẶC dưới làm vùng chữ riêng, subject vẫn hiện đủ) — KHÔNG zoom-out đổi bố cục, KHÔNG phủ giữa.
  - **Typography**: ≤3 từ/dòng, font đậm (Impact/Anton), stroke đen mạnh, letter-spacing kicker, **1 highlight đỏ** (số/năm auto-derive).
  - **Grade**: brightness/contrast/sharpen (UnsharpMask) + vignette; scrim tối CHỈ sau vùng chữ (không phủ chủ thể).
- Non-functional: giữ signature để `thumbnail_generator` gọi tối thiểu-đổi; deterministic (không mạng ở phase này).

## Architecture
- **Vùng trống**: tái dùng gradient/luminance của `thumbnail_frame_score` → "busyness map" trên lưới (vd 3×3 hoặc 4×2). Chọn cụm ô liền kề ít-bận nhất, đủ rộng cho block chữ. Ưu tiên cạnh (trái/phải/trên) hơn giữa.
- `draw_title` mới nhận thêm vị trí vùng trống; đặt kicker+block+red ở đó (port POC `scratchpad/compose_thumbnail.py`, nhưng vị trí ĐỘNG thay vì cố định trái).
- Kicker subject·year từ `video.title` (subject trước `:` + năm regex). Degrade sạch khi thiếu.
- Palette: brass kicker + trắng + đỏ (214,34,34) + stroke đen. Bỏ vàng cũ.

## Related Code Files
- Modify: `src/ai_operator/assembler/thumbnail_style.py` (draw_title → negative-space + typography; helper busyness-map, kicker, accent)
- Modify: `src/ai_operator/assembler/thumbnail_generator.py` (`_overlay_text` truyền title; nhận vùng trống)
- Reference: `src/ai_operator/assembler/thumbnail_frame_score.py` (gradient logic tái dùng), POC `scratchpad/compose_thumbnail.py`

## Implementation Steps
1. `_negative_space_box(img)` → bbox vùng ít-bận nhất đủ cho chữ (numpy gradient trên lưới).
2. `draw_title(img, text, title, box)`: đặt kicker+block+1-đỏ trong `box`; scrim cục bộ sau chữ; auto-fit font.
3. `_kicker_from_title` + `_split_accent` (đỏ số/năm).
4. `_overlay_text` truyền `video.title` + gọi negative-space.
5. Giữ 3-variant flow + `stylize()` (chỉ chỉnh scrim thành cục bộ).

## Success Criteria
- [ ] Chữ nằm ở vùng trống, chủ thể hiện đủ (không bị chữ đè) trên cả ảnh ngang/dọc chủ thể.
- [ ] Đọc rõ ở ~320px (mobile): stroke + contrast + spacing đủ.
- [ ] Không số → đỏ từ cuối; title thiếu năm → kicker degrade; không crash/"None".

## Risk Assessment
- **Chủ thể lấp đầy khung (không có vùng trống)**: fallback = **letterbox bar** (thanh gradient trên/dưới) làm vùng chữ; subject không bị đè, không đổi bố cục.
- **Busyness-map chọn nhầm vùng** (nền rối, chủ thể phẳng): test nhiều mẫu; ngưỡng ở hằng số chỉnh được. Không dùng ML nặng (giữ KISS/nhanh).
