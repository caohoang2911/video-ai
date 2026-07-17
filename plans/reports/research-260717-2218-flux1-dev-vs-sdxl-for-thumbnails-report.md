# Research Report: FLUX.1-dev vs SDXL cho thumbnail/visual của kênh

_Conducted: 2026-07-17 22:18 (Asia/Saigon) · 5 web searches · materials 2025–2026_

## Executive Summary

FLUX **vẽ đẹp hơn SDXL rõ rệt** — prompt-following, chi tiết, ánh sáng, và đặc biệt **render chữ** (chính cái tạo ra vệt "NIGHT" méo trên mũi tàu ở bản SDXL vừa rồi). Nhưng **chạy FLUX.1-dev LOCAL trên máy bạn là lựa chọn tệ** vì 2 rào cản: (1) **License phi-thương-mại** — kênh đang bật kiếm tiền nên dùng weights FLUX.1-dev local để làm thumbnail = vi phạm; (2) **tốc độ/RAM** — FLUX dev fp16 ~24GB, path fp32/MPS kiểu SDXL hiện tại sẽ cực chậm (fp32 pruned ~47 phút/ảnh trên M1 Max 32GB).

**Khuyến nghị (KISS):** đừng self-host FLUX. Repo **đã có sẵn** `src/ai_operator/media/cloud_flux.py` nối tới `fal-ai/flux/dev`. Chỉ cần **điền `FAL_KEY` thật vào `.env`** → có chất lượng FLUX, **license thương mại hợp lệ** (fal cấp), ~**$0.025/megapixel** (1 thumbnail 720p ≈ $0.025), vài giây/ảnh, không đụng tới 64GB. Với ≤3 video/tuần + vài thumbnail, chi phí <$1/tháng.

Nếu bắt buộc 100% free + local + thương mại-an-toàn: dùng **FLUX.1-schnell (Apache-2.0)** qua ComfyUI+GGUF — nhanh (4 step), thương mại OK, đẹp hơn SDXL nhưng dưới FLUX-dev.

---

## Key Findings

### 1. Chất lượng: FLUX > SDXL (đáng kể)
- FLUX thắng SD1.5/SDXL ở prompt-following, tay, **text rendering**, chi tiết mịn; ảnh sạch hơn, bố cục + ánh sáng tốt hơn. SDXL 1.0 (đang xài) "đã già".
- **Text rendering** là khác biệt lớn nhất: FLUX ra chữ đọc được ổn định; SDXL thường méo/sai chữ → đúng với artifact ta gặp. (Ta vẫn ghép chữ bằng PIL nên đây chỉ là bonus: FLUX ít đẻ chữ rác trên chủ thể.)
- Trade-off: FLUX ~**4× chậm hơn** SDXL mỗi ảnh (trên GPU: SDXL 13s vs Flux.dev 57s cho 4 ảnh 1024²).

### 2. Hardware — chạy local FLUX.1-dev trên M1 Max
| Cấu hình | RAM | Tốc độ M1 Max |
|---|---|---|
| FLUX.1-dev fp16 (diffusers/MPS) | ~24GB | rất chậm; fp32 pruned 15.9GB → **~47 phút/ảnh** (32GB, swap nặng) |
| FLUX.1-dev GGUF Q6/Q8 (ComfyUI) | ~12–16GB | **~2–4 phút/ảnh** (64GB, không swap) |
| SDXL fp32 (hiện tại) | ~14GB | ~3.9 phút/ảnh |
→ Local FLUX chỉ hợp lý qua **ComfyUI + GGUF**, KHÔNG qua path diffusers-fp32 kiểu `local_sdxl.py`. Tức phải dựng stack mới (ComfyUI, `--force-fp16`), công sức thật.

### 3. License — điểm chặn quan trọng nhất (kênh monetize)
| Model | Weights license | Thương mại? |
|---|---|---|
| **FLUX.1-dev** | Non-commercial | ❌ Local phải xin **license trả phí** của BFL (bfl.ai/licensing) |
| **FLUX.1-schnell** | Apache-2.0 | ✅ Free, thương mại OK |
| **FLUX.2-dev** (mới 2026) | Non-commercial | ❌ như dev |
| **FLUX qua API (fal/Replicate/BFL)** | — | ✅ Output được cấp quyền thương mại trong giá |
→ Chạy FLUX.1-dev weights local để làm thumbnail cho kênh có bật ads = **commercial use = cần license trả phí**. Đây là lý do repo cố tình chỉ dùng fal cho Flux, còn local để SDXL.

### 4. Chi phí cloud (fal — đã tích hợp sẵn)
| Model | Giá | Ghi chú |
|---|---|---|
| FLUX.1 [dev] | **$0.025 / megapixel** | 720p ≈ 0.92MP → làm tròn 1MP = $0.025; thương mại OK |
| FLUX.1.1 [pro] | $0.04 / MP | cân bằng tốc độ/chất lượng tốt nhất, thương mại OK |
| FLUX.1 [schnell] | rẻ nhất | draft/volume |
→ 50 thumbnail/tháng ở dev ≈ **$1.25**. Không đáng để đánh đổi 47 phút/ảnh + rủi ro license.

### 5. Lineup 2026 (tham khảo, đừng khoá vào model cũ)
BFL đã ra **FLUX.2** (Max/Pro/Flex/Klein) + FLUX1.1 Pro/Ultra + Kontext (editing). FLUX.1-dev nay là tier "budget". Nếu muốn đỉnh nhất qua API: **FLUX1.1 [pro] Ultra** (photoreal 4MP) hoặc **FLUX.2 Pro**. Cho thumbnail, FLUX.1-dev/FLUX1.1-pro qua fal là đủ.

---

## Comparative Analysis — nên chọn gì

| Phương án | Chất lượng | Tốc độ | License | Chi phí | Công sức |
|---|---|---|---|---|---|
| **A. fal FLUX.1-dev (điền FAL_KEY)** ⭐ | Cao | ~vài giây | ✅ | ~$0.025/ảnh | **Gần như 0 (đã code sẵn)** |
| B. fal FLUX1.1-pro | Cao nhất | ~vài giây | ✅ | ~$0.04/ảnh | 0 (đổi 1 dòng model) |
| C. Local FLUX.1-dev (ComfyUI+GGUF) | Cao | 2–4 phút | ❌ phải mua license | "free" nhưng vi phạm | Cao |
| D. Local FLUX.1-schnell (GGUF) | Trung-cao | ~1–2 phút | ✅ Apache | Free | Trung bình (dựng ComfyUI) |
| E. Giữ SDXL local (hiện tại) | Trung bình | ~3.9 phút | ✅ | Free | 0 |

**Chọn A.** B nếu muốn đẹp hơn nữa. D nếu triết lý "phải free + local".

---

## Implementation Recommendations

### Quick start (phương án A — ~2 phút)
1. Lấy key: https://fal.ai/dashboard/keys
2. Sửa `.env`: `FAL_KEY=<key-thật>` (hiện đang là comment placeholder `# opti...` nên fal fail).
3. `cloud_flux.py` đã route `fal-ai/flux/dev`. Với thumbnail nên **bỏ prefix non-photoreal** (`_GENERIC_ILLUSTRATION_PREFIX`) và thêm `image_size: landscape_16_9` cho ảnh hero — hiện hàm `generate()` ép editorial-illustration, hợp b-roll tài liệu chứ không hợp thumbnail cinematic.
4. Giữ SDXL làm fallback offline (đã có sẵn tier).

### Common pitfalls
- **Đừng** tải FLUX.1-dev weights về chạy local cho kênh monetize (license).
- fal Flux **mặc định 1MP**; xuất thẳng 1280×720 rồi mới ghép chữ PIL (pipeline compose đã có).
- fp16 FLUX trên MPS qua diffusers hay OOM/chậm — nếu local thì bắt buộc GGUF+ComfyUI.

## Next Actions
1. Điền `FAL_KEY` → test 1 hero MS Estonia qua fal FLUX.1-dev, so trực tiếp với SDXL seed 77.
2. Nếu ưng: tách 1 nhánh `thumbnail_hero()` trong `cloud_flux.py` (photoreal, 16:9) riêng khỏi b-roll.
3. (Tùy chọn) thử FLUX1.1-pro để so chất lượng/giá cho thumbnail.

## Unresolved Questions
- Giá chính xác **BFL self-hosting commercial license** cho FLUX.1-dev (subscription; chưa xác thực con số) — chỉ cần nếu khăng khăng local dev.
- Budget-guard hiện tính `FAL_FLUX_USD_PER_IMAGE=0.025` cho b-roll; nếu thêm thumbnail hero cần xem có tính vào `MONTHLY_BUDGET` không.
- FLUX.2-Klein có phải Apache-2.0 (thương mại free) như schnell không — chưa xác thực; ảnh hưởng lựa chọn local-free.

## Sources
- [Can I Use FLUX for Commercial Use? — Civitai](https://civitai.com/articles/6625/can-i-use-flux-for-commercial-use)
- [LICENSE-FLUX1-schnell (Apache-2.0) — GitHub](https://github.com/black-forest-labs/flux/blob/main/model_licenses/LICENSE-FLUX1-schnell)
- [LICENSE-FLUX1-dev (non-commercial) — GitHub](https://github.com/black-forest-labs/flux/blob/main/model_licenses/LICENSE-FLUX1-dev)
- [Open Weights Licensing — Black Forest Labs](https://bfl.ai/licensing)
- [Flux + ComfyUI on Apple Silicon 2025 (GGUF, memory) — smartart.live](https://smartart.live/articles/258-flux-comfyui-on-apple-silicon-complete-2026-guide-to-hardware-acceleration-gguf-models-memory-optimization.html)
- [Flux on Apple Silicon M1/M2/M3/M4 Guide — Apatero](https://www.apatero.com/blog/flux-apple-silicon-m1-m2-m3-m4-complete-performance-guide-2025)
- [FLUX.1-schnell on MPS memory issue #80 — GitHub](https://github.com/black-forest-labs/flux/issues/80)
- [SDXL vs Flux1.dev comparison — Stable Diffusion Art](https://stable-diffusion-art.com/sdxl-vs-flux/)
- [Flux vs SDXL 2026: Quality/Speed/Hardware — pxz.ai](https://pxz.ai/blog/flux-vs-sdxl)
- [FLUX.1 [dev] model + pricing — fal](https://fal.ai/models/fal-ai/flux/dev)
- [fal pricing](https://fal.ai/pricing)
- [Best Black Forest Labs Models in 2026 — SiliconFlow](https://www.siliconflow.com/articles/en/the-best-black-forest-labs-models-in-2025)
- [FLUX Models Schnell vs Dev vs Pro vs Max (2026) — Melies](https://melies.co/compare/flux-models)
