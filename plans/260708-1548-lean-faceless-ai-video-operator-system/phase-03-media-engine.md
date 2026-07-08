# Phase 03 — Media Engine (TTS Narrator + Visual Fetcher)

## Context Links
- Overview: [plan.md](plan.md) · Prev: [phase-02](phase-02-content-engine.md)
- Research briefs: ElevenLabs TTS; Visual Acquisition (Pexels/Pixabay + local SDXL + fal.ai).

## Overview
- **Priority:** P0
- **Status:** pending
- **Description:** 2 module song song, cùng nhận `script.json`. (A) **tts-narrator**: ElevenLabs Multilingual v2, chunk + request-stitching giữ prosody, fallback Edge-TTS. (B) **visual-fetcher**: 3-tier Pexels/Pixabay → local SDXL (M1 Max) → fal.ai, cache 24h, tag AI. Output: `narration.mp3` + list ảnh khớp beat.

## Key Insights (từ briefs)
- **ElevenLabs Starter = 30k chars/tháng ≈ ~3 video** → KHÔNG đủ 10-20 video P0. Set alert **70% quota** (sớm hơn để kịp chuyển provider). Concurrency Starter=3 → batch ≤2 tránh 429.
- **TTS fallback CHAIN (critical, multi-provider)**: try ElevenLabs → nếu 429/hết quota → **OpenAI TTS-1** (~$0.90/video) hoặc **Chatterbox** (open-source, free, local) → **Edge-TTS** cuối cùng (free, luôn sẵn). Lý do: 30k chars không cover volume P0 nên cần bậc trung gian rẻ trước khi rơi xuống Edge. Mọi provider đạt AI-label compliance.
- **[CRITICAL — anti-slop/brand] GIỌNG NHẤT QUÁN, chỉ ElevenLabs được PUBLISH.** Nghiên cứu policy 2026: giọng đổi mỗi video / dùng default-voice-ai-cũng-xài = tín hiệu inauthentic + loãng brand. Vì vậy: (a) **khoá 1 `ELEVENLABS_VOICE_ID` cố định** — ưu tiên custom/clone để độc nhất, KHÔNG dùng preset phổ biến; (b) **1 video = 1 provider** (không trộn giữa chừng → không đổi giọng trong video); (c) **chỉ narration bằng giọng thương hiệu (ElevenLabs) mới được publish**. Fallback (OpenAI/Chatterbox/Edge) CHỈ cho **preview nội bộ / khẩn cấp** → set cờ `needs_revoice`, KHÔNG publish giọng lạ; re-voice bằng giọng thương hiệu khi quota reset/top-up. Quản quota bằng cadence ≤3/tuần + top-up credit thay vì hạ giọng.
- **Chunk 500-800 chars/đoạn** = 1-2 câu hoàn chỉnh (~15-30s audio). **LUÔN cắt tại dấu câu tự nhiên** (chấm/hai chấm), TUYỆT ĐỐI không cắt giữa chủ-vị → tránh prosody vỡ. Truyền `previous_text`/`next_text` + `previous_request_id` giữ prosody qua ranh giới. SSML `<break time="1.5s"/>` cho pause kịch tính (Multilingual v2 hỗ trợ). Nối MP3 bằng FFmpeg concat demuxer.
- **Narration <5' → generate 1 lần** (không cần chunk-stitch, tránh seam). **>5' → chunk + overlap 5-10% giữa các đoạn + crossfade** khi concat để giấu seam-click ở mối nối.
- **Visual 3-tier:** Pexels (200 req/hr, 20k/mo) + Pixabay (100 req/60s, **cache 24h BẮT BUỘC theo ToS**) → **local SDXL** (M1 Max 64GB = lý tưởng, MLX nhanh ~40% vs MPS, 10-20s/img) → fal.ai Flux ($0.025/img) chỉ khi local timeout >2 lần/giờ. P0 ưu tiên stock + local (chi ~$0).
- **De-dup** ảnh bằng MD5 (Pexels/Pixabay có thể trùng). Tag "AI-Generated" watermark cho ảnh gen (compliance).
- **Visual consistency (tránh AI slop)**: **stock b-roll thật làm chủ đạo**. SDXL CHỈ dùng cho bản đồ / sơ đồ / cảnh tái dựng — nơi không có stock — với **style prompt hard-code phi-thực** (vd `"hand-drawn historical map, muted 19th-century colors"`) để không giả làm ảnh thật. **Grade theo batch 10 ảnh**: nếu <80% coherent (lệch tông/style) → reject cả batch, regen. Lý do: gen từng ảnh rời rạc gây temporal-drift = AI slop giữa các beat.
- **[CRITICAL — anti-slop] MOTION-FIRST (nghiên cứu policy 2026):** YouTube giết format "slideshow ảnh tĩnh + AI voice". Vì vậy **ưu tiên VIDEO b-roll** (Pexels/Pixabay **Video API**) cho beat establishing/action → chiếm **≥50-60% thời lượng**; ảnh tĩnh + Ken Burns chỉ cho beat detail hoặc khi không có footage. visual-fetcher thử fetch clip video (trim theo beat) TRƯỚC, fallback ảnh. WHY: chuyển động thật giảm "slideshow signature" — yếu tố dễ bị flag nhất với format này.
- **Keyword ngắn** (<50 token) cho cả stock search lẫn SDXL prompt.

## Requirements
Functional:
1. `tts-narrator.synthesize(script) -> narration.mp3` (+ per-chunk wav tạm để Whisper phase 04 nếu cần timing chính xác — nhưng phase 04 chạy Whisper trên mp3 cuối).
2. `visual-fetcher.acquire(shot_list) -> list[AssetRecord]` mỗi beat ≥1 asset (**ưu tiên video clip motion**; ảnh 1920x1080-ish khi không có footage), **≥50-60% thời lượng là motion**, ghi bảng `assets` (source, license, md5, kind=video|image).
3. Update `videos.state = voiced` sau khi cả audio + visuals xong (hoặc tách 2 state phụ; KISS: 1 state `voiced` bao hàm media ready).
Non-functional: cache stock 24h; rate-limit; timeout chain; log source/cost/time; file <200 dòng (tách tier thành helper).

## Architecture — data flow
```
script.json ─┬─ narration text ─► tts-narrator ─(<5' 1-shot / >5' chunk+overlap+crossfade)
             │        ElevenLabs ─(429/quota)→ OpenAI TTS-1 ─(fail)→ Chatterbox ─(fail)→ Edge-TTS
             │                                              └────────► concat → narration.mp3
             └─ shot_list[] ─► visual-fetcher.acquire(beat)  [stock-first, SDXL chỉ map/sơ đồ]
                                  tier1: Pexels ∥ Pixabay (cache24h, ratelimit) ← CHỦ ĐẠO
                                  tier2: local SDXL (style phi-thực hard-code, timeout45s)
                                  tier3: fal.ai Flux (timeout30s, backoff)
                                  → dedup md5 → batch-grade (≥80% coherent) → tag AI
                                  → assets table + output/<id>/img/beat_XX.jpg
```

## Related Code Files
- Create: `src/ai_operator/media/tts_narrator.py`, `src/ai_operator/media/tts_chunker.py` (split câu + stitch context + overlap/crossfade), `src/ai_operator/media/tts_providers.py` (fallback chain: ElevenLabs → OpenAI TTS-1 → Chatterbox → Edge-TTS, mỗi provider 1 hàm `synthesize`), `src/ai_operator/media/visual_fetcher.py`, `src/ai_operator/media/stock_clients.py` (Pexels+Pixabay + cache/ratelimit), `src/ai_operator/media/local_sdxl.py` (MLX hoặc diffusers MPS), `src/ai_operator/media/cloud_flux.py` (fal.ai), `src/ai_operator/media/asset_store.py` (dedup md5 + tag + DB write).
- Modify: `cli.py` (`gen-audio`, `gen-visuals`), `db/models.py` (assets — đã có).
- Delete: none.

## Implementation Steps
1. `stock_clients.py`: `requests_cache.CachedSession(backend='sqlite', expire_after=timedelta(hours=24))` + `requests_ratelimiter.LimiterSession(per_second=3)` Pexels / `per_second=1.5` Pixabay. `search_pexels(kw)`, `search_pixabay(kw)` → trả URL ảnh landscape ≥1920w. Monitor header `X-Ratelimit-Remaining`.
2. `local_sdxl.py`: load SDXL base 1 lần (module-level singleton). Ưu tiên MLX (`mlx` stable-diffusion) nếu cài được; else `diffusers` + `.to("mps")` + `enable_attention_slicing()` + `torch.float16`. `generate(prompt, seed) -> PIL.Image` 1024x1024 (upscale/crop 16:9 sau). **Pre-download model ở setup**, không lúc render. **Chỉ gọi cho beat loại map/sơ đồ/tái dựng**; prepend style prompt phi-thực hard-code (vd `"hand-drawn historical map, muted 19th-century colors"`) để không giả ảnh thật.
3. `cloud_flux.py`: `await fal_client.run_async('fal-ai/flux-dev', {...})` với backoff `[2,4,8]`, cap concurrency 2-3. Chỉ gọi khi bật `FAL_KEY` + local fail.
4. `asset_store.py`: `save(video_id, beat_id, image, source, license)` → tính MD5, skip nếu trùng, ghi file + row `assets`; watermark "AI-Generated" cho ảnh gen (PIL draw).
5. `visual_fetcher.py`: `acquire(shot_list)`: mỗi beat → tier1 stock: **thử Pexels/Pixabay VIDEO trước** cho beat establishing/action (đảm bảo ≥50-60% thời lượng là motion), fallback photo (asyncio.gather Pexels∥Pixabay, timeout 5s) — CHỦ ĐẠO → nếu rỗng HOẶC beat=map/sơ đồ/tái dựng → tier2 local SDXL (timeout 45s) → tier3 fal.ai. Sau khi gom đủ ảnh gen: **batch-grade 10 ảnh, reject+regen nếu <80% coherent** (so tông màu/style). Log source/time. Trả list AssetRecord.
6. `tts_chunker.py`: `split(text, max_chars=800)` theo câu, **luôn cắt tại dấu câu (chấm/hai chấm), không cắt giữa chủ-vị**; `iter_context(chunks)` yield (chunk, prev_text, next_text). Chèn `<break>` tại dấu chấm câu kịch tính (heuristic đơn giản). Nếu narration <5' → trả 1 chunk duy nhất (1-shot); >5' → thêm overlap 5-10% mép đoạn để crossfade khi concat.
7. `tts_providers.py`: fallback chain — mỗi provider hàm `synthesize(text, ...) -> mp3`. ElevenLabs (`text_to_speech.convert(..., model_id="eleven_multilingual_v2", previous_text, next_text, previous_request_id)`) → khi 429/quota bắt exception → OpenAI TTS-1 (`audio.speech.create(model="tts-1", voice=...)`) → Chatterbox (local, free) → Edge-TTS (`edge_tts.Communicate(text, voice).save`). Trả về provider nào chạy để log cost.
8. `tts_narrator.py`: `synthesize(script_text) -> mp3_path`: chunk (bước 6) → gọi `tts_providers` chain **NHƯNG khoá 1 provider cho cả video** (không đổi giữa chừng); mặc định ElevenLabs `ELEVENLABS_VOICE_ID` cố định (giữ `previous_request_id`) → concat FFmpeg (crossfade nếu có overlap) → `narration.mp3`. **Nếu phải fallback (không phải ElevenLabs) → set `videos.needs_revoice=true`, KHÔNG cho publish**; re-voice bằng giọng thương hiệu khi quota reset/top-up.
9. `cli.py`: `operator gen-audio --video-id X`, `operator gen-visuals --video-id X`.
10. Chạy thử: audio ~8-15', visuals đủ beat, assets ghi DB, state=voiced. Verify quota ElevenLabs còn.

## Todo List
- [ ] stock_clients (Pexels+Pixabay, cache24h, ratelimit)
- [ ] local_sdxl (MLX/diffusers MPS) + pre-download model + style prompt phi-thực (chỉ map/sơ đồ)
- [ ] cloud_flux (fal.ai, backoff) — optional bật cờ
- [ ] asset_store (dedup md5 + AI watermark + DB)
- [ ] visual_fetcher 3-tier (stock-first, **video-b-roll-first ≥50-60% motion**) + timeout chain + batch-grade ≥80% coherent
- [ ] tts_chunker (split câu tự nhiên + stitch context + SSML break + overlap/crossfade)
- [ ] tts_providers fallback chain (ElevenLabs → OpenAI TTS-1 → Chatterbox → Edge-TTS) — **khoá 1 voice ID; 1 video 1 provider; ElevenLabs-only publish; fallback → `needs_revoice`** (thêm cột `videos.needs_revoice` bool ở phase-01 models)
- [ ] tts_narrator (chain synth + <5' 1-shot / >5' chunk + concat)
- [ ] cli gen-audio / gen-visuals
- [ ] chạy thử end-to-end media, quota còn

## Success Criteria
- `narration.mp3` dài 8-15', prosody mượt qua ranh giới chunk (nghe không giật/không seam-click), 0 lỗi 429 (hoặc fallback chain kích hoạt sạch, log provider dùng thật).
- **Giọng publish luôn là 1 ElevenLabs voice cố định** (không đổi trong 1 video lẫn giữa các video); nếu fallback provider chạy → `needs_revoice=true`, KHÔNG publish.
- Mỗi beat trong shot_list có ≥1 asset trong `output/<id>/`, row `assets` có license + md5 + kind, không trùng; batch ảnh gen ≥80% coherent; **motion b-roll ≥50-60% thời lượng** (đo tổng thời lượng kind=video / tổng).
- ElevenLabs quota tiêu ≤12k chars/video; alert nếu >70% tháng → chuyển provider rẻ hơn.
- `videos.state = voiced`.

## Risk Assessment
| Risk | L | I | Mitigation |
|---|---|---|---|
| ElevenLabs 30k chars ≈3 video, không đủ P0 volume | **High** | High | Alert **70%**; fallback CHAIN OpenAI TTS-1 (~$0.90/video) → Chatterbox → Edge-TTS; nâng Creator ($22) khi cần chất lượng đồng nhất. |
| Prosody vỡ / seam-click ở ranh giới chunk | Med | Med | Cắt tại dấu câu (không giữa chủ-vị); request-stitching (prev/next + request_id); <5' 1-shot; >5' overlap 5-10% + crossfade; A/B nghe thử. |
| AI slop / temporal-drift giữa ảnh gen | Med | High | Stock-first (b-roll thật chủ đạo); SDXL chỉ map/sơ đồ với style hard-code phi-thực; batch-grade reject <80% coherent. |
| **Giọng đổi giữa video/các video (fallback chain) → inauthentic + loãng brand** | **Med** | **High** | Khoá 1 ElevenLabs voice ID (custom/clone); 1 video 1 provider; chỉ giọng thương hiệu được publish; fallback → `needs_revoice`, re-voice khi quota về. |
| **Slideshow ảnh tĩnh → dễ bị flag "AI slop"** | **Med** | **High** | Motion-first: video b-roll ≥50-60% thời lượng; Ken Burns ảnh tĩnh chỉ khi thiếu footage. |
| SDXL OOM/chậm | Low | Med | M1 Max 64GB dư; float16 + attention slicing; timeout→fal.ai. |
| Pixabay vi phạm cache 24h ToS | Low | High | `expire_after=24h` non-negotiable; test cache hit. |
| Ảnh stock trùng/nghèo nàn | Med | Low | Multi-source + de-dup md5 + local gen bù. |

## Security Considerations
- Keys Pexels/Pixabay/fal.ai/ElevenLabs qua env, không log. `.env.example` có placeholder.
- Chỉ lấy asset CC0/royalty-free (Pexels/Pixabay License); ghi `license` vào `assets` để audit trước upload (phase 06).
- Watermark AI cho ảnh gen phục vụ minh bạch (kết hợp `containsSyntheticMedia` phase 06).

## Next Steps
→ Phase 04 ghép `narration.mp3` + images (Ken Burns) + captions (Whisper) + music.

## Unresolved Questions
- MLX hay diffusers+MPS trên M1 Max? — benchmark 2h ở setup, chọn winner (brief: MLX ~40% nhanh hơn, verify empirically).
- Nhạc nền lấy đâu (ảnh hưởng phase 04)? — YouTube Audio Library free (P0) vs Artlist/Epidemic (P1).
