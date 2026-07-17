# Plan: FLUX.1-dev (fal.ai) thay SDXL cho generator ảnh của pipeline

**Created:** 2026-07-17 · **Updated:** 2026-07-17 (pivot: local→fal) · **Branch:** feat/ops-observability-validation · **Status:** pending

> Thư mục giữ tên cũ `...local-flux-schnell...` nhưng hướng đã chốt là **fal cloud** (quyết định 2026-07-17 sau khi spike lộ blocker đĩa 31GB < 34GB cần cho FLUX local). Không đổi tên dir để giữ liên kết report/history.

## Goal
Thay **generator ảnh** trong tier sinh-still: **local SDXL → fal.ai FLUX.1-dev**.
`cloud_flux.py` đã route `fal-ai/flux/dev` sẵn (đang là fallback tier-4) → nâng thành generator CHÍNH.
Giữ local SDXL làm fallback offline (khi mất mạng / fal lỗi). Stock/archival tiers không đụng.

## Why (research + quyết định)
- FLUX > SDXL 1.0 (prompt-following, chi tiết, coherence, ít artifact chữ rác) — report `plans/reports/research-260717-2218-flux1-dev-vs-sdxl-for-thumbnails-report.md`.
- fal cấp **license thương mại** cho output FLUX.1-dev → hợp lệ cho kênh monetize (khác weights dev local = non-commercial).
- **Local bị chặn bởi đĩa**: FLUX-schnell bf16 cần ~34GB, máy còn 31GB; GGUF/ComfyUI thì thêm setup. → fal là đường KISS nhất, code gần như sẵn.
- Chi phí nhỏ, đã có budget_guard: ~**$0.025/ảnh**, ~9 ảnh/main video → **~$0.30/video**, ~**$4/tháng** (cap 3 video/tuần). Số liệu: 10 main → 87 ảnh SDXL (~9/video).

## Key risks
- **FAL_KEY**: hiện `.env` để placeholder `# opti...` → mọi call fal fail. Bước đầu tiên phải điền key thật.
- **Prefix non-photoreal**: `cloud_flux.generate` ép `editorial illustration...` cho b-roll (đúng, giữ). Thumbnail hero (Phase 5, optional) mới cần bỏ prefix + 16:9.
- **Chi phí trôi**: generator giờ tốn tiền mỗi ảnh (trước SDXL free). budget_guard đã reserve/record — verify ngưỡng `MONTHLY_BUDGET` hợp lý; `force_generate` (30 ảnh) = $0.75/video.
- **Phụ thuộc mạng**: giữ SDXL local làm fallback offline để render không chết khi fal/mạng lỗi.

## Phases
| # | Phase | Priority | Depends | Status |
|---|-------|----------|---------|--------|
| 1 | [FAL_KEY + smoke test & quality gate](phase-01-validation-spike.md) | P1 | — | ✅ done (GO) |
| 2 | [fal FLUX làm generator chính (+ toggle)](phase-02-local-flux-module.md) | P1 | 1 | ✅ done |
| 3 | [Cost / budget / docs](phase-03-wire-visual-fetcher.md) | P2 | 2 | ✅ done |
| 4 | [Tests + render end-to-end](phase-04-config-cost-docs.md) | P1 | 2 | ✅ done (unit; full render = manual) |
| 5 | [(Optional) Thumbnail hero bằng fal FLUX](phase-05-tests-and-render.md) | P3 | 2 | ⏭ skipped (optional) |

## Implementation result (2026-07-17)
- fal FLUX.1-dev = generator chính; SDXL fallback offline. Toggle `IMAGE_GEN_BACKEND=fal_flux|sdxl` (rollback).
- Code: `config.py` (+IMAGE_GEN_BACKEND), `visual_fetcher.py` (_generate_visual tier order + _run_with_timeout bound-fix), `.env.example`, `docs/user-setup-checklist.md`.
- Tests: +5 (toggle/fallback/disable/timeout-bound) → **382 passed**.
- code-reviewer: 1 High (H1 `_run_with_timeout` không bound wall-clock — verified empirically) đã fix + regression test; L1 (typo backend → fal-first an toàn) + L2 (docstring cũ) đã sửa.
- Còn lại (manual, tốn tiền/thời gian): render `force_generate` 1 video thật để xác nhận coherence ≥80% end-to-end.

> Tên file phase giữ nguyên (đã tạo trước pivot); TIÊU ĐỀ bên trong là nội dung thật. Phase-06 cũ bỏ.

## Non-goals (YAGNI)
- Không thay stock/archival/motion tiers ("thật khi có thể" giữ nguyên).
- Không xoá `local_sdxl.py` — giữ làm fallback offline (đừng phá đường thoát khi mất mạng).
- Không dùng FLUX.1-dev weights LOCAL (non-commercial + đĩa không đủ).
- Không đổi sang FLUX1.1-pro ngay (dev đủ; pro là tuỳ chọn nâng sau, +60% giá).

## Success criteria (toàn plan)
- [ ] FAL_KEY thật hoạt động; 1 ảnh fal FLUX sinh ra, đẹp hơn SDXL trên prompt tương đương.
- [ ] `IMAGE_GEN_BACKEND=fal_flux` → generator chính là fal; SDXL vẫn là fallback offline.
- [ ] Render `force_generate` 1 video qua fal ok, coherence ≥80%, chi phí log đúng qua budget_guard.
- [ ] Tests xanh; docs + .env note cập nhật (license fal, cost/ảnh).
