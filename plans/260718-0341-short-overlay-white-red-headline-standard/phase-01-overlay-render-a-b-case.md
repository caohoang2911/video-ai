---
phase: 1
title: Overlay Render + A/B Case
status: completed
priority: P1
effort: 1d
dependencies: []
---

# Phase 1: Overlay Render + A/B Case

## Overview
Dựng renderer overlay top **trắng/đỏ** cho Short (tái dùng engine poster), rồi render **2 mẫu (Title Case vs UPPERCASE)** để user so ảnh và **khóa kiểu chữ**. Đây là gate quyết định của cả plan — nội dung headline giai đoạn này *hand-fed/derived từ parent title* để không chờ P2.

## Requirements
- Functional: `_pinned_title_fx` render headline 2-3 dòng, dòng setup off-white + dòng gap đỏ, tĩnh trên video pan, trong top blur band, né UI zone Shorts.
- Functional: render được 2 case (title/upper) qua config để xuất 2 mẫu so sánh.
- Non-functional: KISS/DRY — tái dùng `thumbnail_style` primitives (font Impact, `ACCENT_COLOR`/`BASE_COLOR`, `_accent_targets`, stroke dày), không viết lại logic đỏ; không đụng zoompan/still pipeline.

## Architecture
- **Bake banner PNG (PIL, RGBA trong suốt):** hàm mới `render_headline_banner(text, size=(1080, BAND_H), case) -> Path`. Dùng lại primitives: `_fit_box` (auto-size), `_wrap`, `_accent_targets` (đỏ = dòng chứa số, else dòng cuối/từ cuối), `_draw_line` (word đỏ/trắng), `_load_font`, `BASE_COLOR`/`ACCENT_COLOR`/`STROKE_COLOR`. Nền trong suốt (KHÔNG scrim/dim toàn khung như thumbnail — top band vốn đã là blur pad tối).
- **Overlay tĩnh:** `_pinned_title_fx` trả filter `movie={banner}[bn];[vin][bn]overlay=0:{Y}` thay cho drawtext. Chạy trong `post_fx` của `burn_and_mux` (sau captions, sau zoompan → tĩnh). `Y` đặt khối trong top band (~y≥130px, dưới icon search/3-chấm).
- **Geometry:** `SHORT_SIZE=(1080,1920)`, top band ≈ (1920 − 608)/2 ≈ 656px. BAND_H ~ 520px (chừa mép ảnh ≥40px). Dòng ≤ ~2 dòng, tối đa 3.
- **DRY primitives:** để dùng ở cả short + thumbnail, import từ `thumbnail_style` (chấp nhận underscore trong cùng package) HOẶC extract sang `assembler/headline_text.py` ngay. **Chọn**: extract nhẹ sang `headline_text.py` (giảm size `thumbnail_style` >312 dòng, phục vụ DRY P3) — có test regression thumbnail ở P4.
- **A/B:** config `SHORTS_HEADLINE_CASE`; hàm CLI/one-off render 2 short mẫu (1 topic có số như "General Slocum, 1904 / 1,021 died", 1 không số) cho cả 2 case → xuất frame/clip.

## Related Code Files
- Create: `src/ai_operator/assembler/headline_text.py` (primitives dùng chung: font, colors, `fit_box`, `wrap`, `accent_targets`, `draw_line`)
- Modify: `src/ai_operator/assembler/short_builder.py` (`_pinned_title_fx` → bake banner + `movie` overlay; drop drawtext-18-wrap gold path)
- Modify: `src/ai_operator/assembler/thumbnail_style.py` (import primitives từ `headline_text` thay bản private — giữ hành vi y hệt)
- Modify: `src/ai_operator/config.py` (`SHORTS_HEADLINE_CASE: str = "title"`)

## Implementation Steps
1. Tạo `headline_text.py`: chuyển `_fit_box`, `_wrap`, `_accent_targets`, `_draw_line`, `_load_font`, `_text_w`, các hằng màu/`MAX_LINES`/`_MAX_FONT`/`_MIN_FONT`/`_THUMB_FONTS` sang đây (public tên gọn). Giữ chữ ký y hệt.
2. `thumbnail_style.py`: import lại từ `headline_text`, xóa bản trùng. Chạy test thumbnail hiện có → phải xanh y cũ (regression gate — P4 khóa).
3. Viết `render_headline_banner(text, case, size, out) -> Path` trong `headline_text.py` (hoặc `short_builder`): RGBA trong suốt, `text` có `\n` = ngắt dòng thủ công (setup/gap) hoặc auto-wrap nếu 1 chuỗi; apply case; đỏ theo `accent_targets`.
4. `short_builder._pinned_title_fx`: nếu có headline → bake banner (cache theo `video_dir/hook_banner.png`), trả `movie=...overlay=0:{Y}`. Rỗng → None. Xóa nhánh gold drawtext + `hook_*.txt`.
5. Thêm `SHORTS_HEADLINE_CASE` vào config; renderer đọc default.
6. One-off render: script nhỏ (hoặc `commands.py` hook) render 2 short mẫu × 2 case = 4 output. Với headline: derive từ `parent title_options[0]` (tách setup/gap ở dấu `—`/`:`) hoặc hard-code 2 câu mẫu để cô lập biến kiểu chữ.
7. Xuất frame đầu (ffmpeg -frames:v 1) của mỗi mẫu cho user so.

## Success Criteria
- [ ] Overlay render trắng/đỏ, đỏ đúng 1 dòng/cụm (số → dòng số), Impact stroke dày, đọc rõ ở 1080w.
- [ ] Overlay tĩnh khi ảnh pan (không dính zoompan).
- [ ] Khối text trong top band, né top UI (~y≥130) và mép ảnh.
- [ ] 4 ảnh mẫu (2 topic × 2 case) xuất được cho user.
- [ ] Test thumbnail cũ vẫn xanh sau khi extract primitives (không regression).
- [ ] **User khóa kiểu chữ** → set `SHORTS_HEADLINE_CASE` default.

## Risk Assessment
- **Extract primitives làm vỡ thumbnail (đã ship, DONE plan).** → Mitigate: chỉ *di chuyển* (không đổi logic), chạy full test thumbnail ngay bước 2; nếu rủi ro cao, tạm import private thay vì extract, dời extract sang P3.
- **`movie` filter + path tương đối:** `burn_and_mux` chạy `cwd=video_dir` → banner tham chiếu theo basename (giống `hook_*.txt` cũ). Verify escaping path trong filter graph.
- **Banner PNG cache stale** giữa các lần render → ghi đè theo `video_dir`, xóa khi rỗng.
