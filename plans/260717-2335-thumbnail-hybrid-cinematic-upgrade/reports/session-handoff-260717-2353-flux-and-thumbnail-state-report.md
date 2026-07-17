# Session handoff — FLUX primary (done) + Thumbnail hybrid (planned, validated)

_Saved: 2026-07-17 23:53 · branch `feat/ops-observability-validation` · để `/clear` rồi resume._

## TL;DR resume
1. **Việc DONE + committed:** fal FLUX.1-dev = generator ảnh chính (commit `e8032e4`).
2. **Việc ĐANG DỞ:** plan thumbnail hybrid cinematic — **đã viết + validate xong, CHƯA code**. Active plan: `plans/260717-2335-thumbnail-hybrid-cinematic-upgrade/`.
3. **Next action:** `/ck:cook plans/260717-2335-thumbnail-hybrid-cinematic-upgrade` — **làm Phase 1 trước** (template negative-space, $0), duyệt look rồi mới Phase 2-4. HOẶC verify model FLUX Kontext trên fal trước.

## 1. FLUX-primary (DONE)
- Commit `e8032e4` trên branch. fal FLUX.1-dev thay SDXL làm generator chính; SDXL = fallback offline. Toggle `IMAGE_GEN_BACKEND=fal_flux|sdxl` (config.py).
- Files: `config.py`, `media/visual_fetcher.py` (_generate_visual tier order + _run_with_timeout bound-fix), `media/cloud_flux.py`, `.env.example`, `docs/user-setup-checklist.md`, `tests/test_motion_broll_sourcing.py`. 382 tests pass.
- Plan: `plans/260717-2218-local-flux-schnell-replace-sdxl/` (Phase 1-4 done, Phase 5 superseded).
- **FAL_KEY thật đã điền `.env`** (đừng commit .env — đã gitignore). Credit fal còn ~$9.9 (đã tiêu $0.0825 session này cho smoke test).
- Research report: `plans/reports/research-260717-2218-flux1-dev-vs-sdxl-for-thumbnails-report.md`.

## 2. Thumbnail hybrid (PLANNED + VALIDATED, chưa code)
Plan dir: `plans/260717-2335-thumbnail-hybrid-cinematic-upgrade/` (plan.md + phase-01..04).

**Quyết định user đã chốt (trong plan.md → Decisions):**
- Enhance engine = **Hybrid Kontext nhẹ**: hero a qua FLUX Kontext (fal, preserve subject/composition, relight+fog nhẹ, KHÔNG bịa vật thể); variant b/c PIL grade. ~$0.04/video. Toggle `THUMBNAIL_KONTEXT_ENHANCE` tắt → PIL-only.
- Text = **negative-space** (KHÔNG đè chủ thể); subject lấp đầy khung → **letterbox bar cinematic**.
- A/B = **3 ảnh khác nhau** + title riêng mỗi variant.
- Backfill = **chỉ video mới** (10 video cũ giữ nguyên; backfill cần approval từng cái).

**4 phase:** 1) template negative-space+typography+PIL grade · 2) cổng relevance CLIP (`clip_reranker.score()` mới) · 3) tầng fal (Kontext enhance hero + synthetic hero khi archival rớt; `cloud_flux` thêm `photoreal` + `kontext_edit`) · 4) tests+render+docs.

**Scout facts đã biết (đỡ scout lại):**
- `thumbnail_generator.py` ĐÃ archival-first (`_thumbnail_sources`); `thumbnail_frame_score.py` chỉ chấm image-quality, KHÔNG relevance.
- `thumbnail_style.draw_title` đặt chữ canh-giữa lower-third → ĐÈ chủ thể (phải sửa sang negative-space).
- Asset table: có `license`, KHÔNG có `artist` → attribution qua description image_credits.
- `clip_reranker` có `rank()`, cần thêm `score(text,path)->float`. CLIP cached ~600MB.
- fal Kontext: **verify model id** (`fal-ai/flux-pro/kontext`/`fal-ai/flux/kontext`) — Phase 3 bước 1; không có thì degrade sang PIL-enhance.

## 3. Demo/POC artifacts (scratchpad — mất khi clear temp; đã copy Desktop)
- Desktop: `thumbnail-estonia-FLUX-demo.png` (AI hero), `thumbnail-estonia-ARCHIVAL-demo.png` (ảnh thật Viking Sally=Estonia), `thumbnail-ms-estonia-sealed-26-years.png`.
- Scratchpad scripts (tham khảo khi code Phase 1/3): `compose_thumbnail.py` (compositor text template), `demo_archival_thumb.py` (fetch Wikimedia + grade), `smoke_fal_flux.py` (fal gen), `gen_hero_sdxl.py`.
- **Bài học demo:** archival Estonia chỉ có ảnh tàu thời tên cũ "Viking Sally" (sai livery) + thiếu drama → lý do cần cổng relevance + hero fallback.

## 4. Việc còn treo khác (không chặn thumbnail)
- FLUX plan Phase 4: render `force_generate` 1 video thật qua fal để xác nhận coherence end-to-end (tốn ~$0.2-0.75, cần chọn video_id) — chưa làm.
- 11 file uncommitted không liên quan (retention_view, ass_karaoke_writer, routes_videos, video_detail, test_web_read_views…) — của việc khác, để nguyên.
- Phân tích 7 slide YouTube (A/B test, description 2 dòng đầu, ≤5 hashtag, timestamp, tag, SRT upload, end screen) — đã scout dở, chưa ra report. Nhiều cái pipeline đã có (metadata_builder cap 5 hashtag, chapter_builder). Gap chính: **upload SRT riêng** chưa có trong publisher.

## Unresolved questions
- Model id chính xác của FLUX Kontext trên fal (verify khi cook Phase 3).
- Ngưỡng `THUMB_RELEVANCE_MIN` (CLIP) + cường độ Kontext — calibrate bằng render thật.
