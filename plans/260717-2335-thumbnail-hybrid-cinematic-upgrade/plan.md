# Plan: Thumbnail hybrid cinematic upgrade

**Created:** 2026-07-17 · **Updated:** 2026-07-18 (implemented + poster-style refinement + hardening) · **Branch:** feat/ops-observability-validation · **Status:** DONE
**Supersedes:** phase-05 (optional thumbnail hero) của `plans/260717-2218-local-flux-schnell-replace-sdxl/`.

## Status (2026-07-18)
Tất cả 4 phase **đã code + test (407 xanh) + render thật** (Estonia 28 + Lusitania 25).
- Kontext model verified live: `fal-ai/flux-pro/kontext` (~19s, ~1MP, giữ chủ thể, ~$0.044/ảnh).
- **Đổi hướng typography theo brief mới (user reference)**: từ lower-third centered → **movie-poster block**: kicker `SUBJECT · YEAR` brass + gạch chân, headline Impact trái, **1 dòng payoff đỏ** (số → cụm số; lẻ dòng chỉ đỏ cụm số/last word, không đỏ cả dòng). Scrim gradient 1 hướng, đậm-nhạt theo độ sáng vùng. Layout = block ≤55% (không full-width band) chọn theo negative-space; chủ thể không bị chôn.
- Hardening qua workflow đa-agent (10 agent): sửa **grade flag bị đảo (hero double-grade)**, null thumbnail_text, per-variant never-empty, kontext temp leak, gradient-scrim clip, kicker ăn hết chiều cao, fallback_headline `\b`, needs_bar tách khỏi bias, cost-mischarge khi download fail.
- **Giới hạn đã biết**: CLIP không phân biệt livery (ảnh MS Estonia thời Viking/Silja vẫn qua cổng — HERO variant a dùng đúng livery Estline cuối; b/c có thể lấy livery cũ). Kicker year chỉ có khi title chứa năm (Estonia title không có → "MS ESTONIA" không ·1994).

## Goal
Nâng thumbnail lên chuẩn **cinematic documentary, CTR-tối-ưu** theo brief người dùng:
- **KHÔNG đè chữ lên chủ thể** — headline chỉ ở **vùng trống (negative space)**; chủ thể luôn hiện đủ, là focal point.
- **Enhance, giữ chủ thể + bố cục gốc**: brightness/contrast/sharpness/cinematic lighting + atmosphere nhẹ (fog/light rays) mà vẫn tự nhiên, thật.
- **Typography** đậm, sạch, đọc rõ trên mobile; layout cân, 1 focal point; 16:9.

**KHÔNG xây mới** — tinh chỉnh hệ sẵn (`thumbnail_generator.py` đã archival-first + `thumbnail_style.py` + `thumbnail_frame_score.py` + A/B 3 variant).

## Decisions (user-confirmed 2026-07-17)
- **Enhance engine — Hybrid Kontext nhẹ:** hero chính (variant a) qua **FLUX Kontext (fal)** — giữ nguyên chủ thể/bố cục, chỉ relight+grade+atmosphere nhẹ, **KHÔNG thêm/bớt vật thể**. 2 variant còn lại **PIL grade**. ~$0.04/video. Toggle tắt → PIL-only.
- **Subject lấp đầy khung (no negative space):** dùng **letterbox bar cinematic** (thanh gradient trên/dưới làm vùng chữ) — subject vẫn hiện đủ, chữ không đè. KHÔNG zoom-out đổi bố cục.
- **A/B variants:** **3 ảnh khác nhau**, mỗi ảnh ghép 1 title_option (hero Kontext + 2 frame PIL) → test cả ảnh lẫn title. Khớp pipeline hiện tại.
- **Backfill:** **CHỈ video mới**; 10 video đã đăng giữ thumbnail cũ (backfill sau, thủ công, cần approval từng cái — guardrail no-publish-without-approval).

## Why (research + demo)
- Best-practice 2026: **1 chủ thể trội, ≤3 từ, 1 điểm đỏ, curiosity gap, KHÔNG che subject**; collage underperform (report `plans/reports/research-260717-2218-...`).
- Demo lộ: archival Estonia bị **sai livery + thiếu drama** → cần **cổng relevance** + **enhance/hero fallback**. Triết lý: *"thật khi ĐỦ TỐT (+enhance nhẹ), vẽ khi phải"*.
- POC đã dựng (Desktop `thumbnail-estonia-{FLUX,ARCHIVAL}-demo.png`) — nhưng **cả 2 đè chữ lên tàu**; brief mới sửa đúng lỗi này (chữ vào vùng trống).

## Key constraints (scout)
- `thumbnail_style.draw_title` hiện đặt chữ **canh giữa lower-third → ĐÈ chủ thể**. Phải đổi sang **negative-space aware**.
- `thumbnail_generator._thumbnail_sources` đã archival-first; `thumbnail_frame_score` chỉ chấm image-quality (contrast/detail), không relevance.
- Asset lưu `license`, **KHÔNG có `artist`** → attribution qua **description image_credits** (đã có). Kontext-edit CC BY-SA = derivative → giữ ShareAlike + attribution (description credit đủ; "không bịa vật thể" giữ tính defensible).
- `clip_reranker`: có `rank()`, cần thêm `score()`. CLIP model cached ~600MB.
- fal FLUX **Kontext** (image-editing, preserve-subject) — verify model id ở impl (`fal-ai/flux-pro/kontext` / `fal-ai/flux/kontext`). fal FLUX **dev** (đã tích hợp `cloud_flux.py`) cho synthetic hero.

## Phases
| # | Phase | Priority | Depends | Status |
|---|-------|----------|---------|--------|
| 1 | [Subject-preserving template (negative-space text + typography + grade)](phase-01-cinematic-template.md) | P1 | — | ✅ done (poster-block variant) |
| 2 | [Archival relevance gate (CLIP)](phase-02-archival-relevance-gate.md) | P1 | — | ✅ done (min 0.22 calibrated) |
| 3 | [fal image layer: Kontext enhance + synthetic hero](phase-03-flux-hero-fallback.md) | P2 | 1,2 | ✅ done (`fal-ai/flux-pro/kontext`) |
| 4 | [Tests + render + docs](phase-04-tests-render-docs.md) | P1 | 1,2,3 | ✅ done (407 tests, 2 real renders) |

## Non-goals (YAGNI v1)
- Backfill thumbnail cho 10 video đã đăng (chỉ video mới; backfill thủ công sau nếu cần).
- Collage/montage; before-after split; khoanh-đỏ curiosity device (defer v2).
- AI-edit mạnh/thêm vật thể lên ảnh thật (user chọn "nhẹ, không bịa").
- Kontext cả 3 variant (chỉ hero a; b/c PIL grade — cost + A/B đa dạng).
- Burn attribution lên ảnh (Asset thiếu artist; description đủ).
- Colorize B&W archival (defer).

## Success criteria (toàn plan)
- [ ] Chữ KHÔNG đè chủ thể — nằm ở vùng trống; chủ thể hiện đủ, rõ ở mobile.
- [ ] Hero a: real archival (qua cổng) → Kontext enhance nhẹ; hoặc synthetic FLUX hero khi archival rớt.
- [ ] Typography đậm/sạch/đọc rõ; grade cinematic tự nhiên; 16:9.
- [ ] Toggle Kontext tắt → PIL-only vẫn ra thumbnail ổn. Tests xanh; render thật 1-2 video hợp lý.
