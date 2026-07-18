# Phase 01 — Gemini Relevance Scorer + Fail-Loud Gate

**Priority:** P0 (root cause) · **Status:** pending · Đòn lớn nhất — bật relevance thật, không im lặng.

## Context
- Root cause: `thumbnail_generator._relevance_gate` (`:154-170`) gọi `clip_reranker.available()`; torch
  chỉ ở extra `sdxl` (`pyproject.toml:49`), không core → thường `available()==False` → **cho qua hết**.
- Gemini client đã có: `content/llm_client.py:155-184` (`genai.Client(api_key=settings.GEMINI_API_KEY)` →
  `client.models.generate_content(model="gemini-2.5-flash", ...)`), có budget ledger `check_and_reserve`/`record_actual`.

## Key insight
Đổi cơ chế scorer, **giữ nguyên hình dạng gate** (subject + score/path → keep/drop). Tạo abstraction mới
`relevance_scorer` để `thumbnail_generator` không phụ thuộc torch nữa. Gemini vision trả điểm 0..1 (thang
KHÁC CLIP cosine → threshold phải đổi).

## Requirements
- **F:** `relevance_scorer.score(subject: str, image_path: Path) -> float | None` — 0..1, càng cao càng đúng sự kiện.
- **F:** `relevance_scorer.available() -> bool` — True khi `GEMINI_API_KEY` set (không cần torch).
- **F:** Gate **fail-loud**: khi scorer không available → log `WARNING` rõ ("relevance gating DISABLED")
  + tăng 1 counter/metric ops (tái dùng cơ chế ops observability hiện có nếu có), **không** im lặng.
- **NF:** mỗi call hook vào budget ledger (flat reserve như `_complete_gemini`), `thinking_budget=0`, prompt
  yêu cầu trả **chỉ 1 số 0..1** (hoặc JSON `{"score":0.x}`), parse an toàn.
- **NF:** best-effort per-image: 1 ảnh lỗi/None → không đánh rớt cả gate (giữ hành vi cũ, nhưng log).

## Architecture
```
thumbnail_generator._relevance_gate
        │ subject, [paths]
        ▼
media/relevance_scorer.score(subject, path)  ── available()? ──► Gemini vision (llm_client)
        │  0..1 | None                                   └─ not available → WARNING + ops signal
        ▼
keep if score >= THUMB_RELEVANCE_MIN (thang 0..1, ngưỡng mới)
```
- Ảnh gửi Gemini: đọc bytes → `types.Part.from_bytes(data=..., mime_type=...)`, downscale nếu cần (kiểm soát token).
- Prompt: "Does this image depict {subject}? Reply a single number 0.0–1.0 (1=exactly this event/subject, 0=unrelated). No text."

## Related code files
- **Create:** `src/ai_operator/media/relevance_scorer.py` (<200 dòng)
- **Modify:** `src/ai_operator/content/llm_client.py` — thêm `score_image_relevance(subject, image_bytes) -> float|None` (Gemini vision, budget-hooked)
- **Modify:** `src/ai_operator/assembler/thumbnail_generator.py` — `_relevance_gate`: `clip_reranker` → `relevance_scorer`, fail-open → fail-loud
- **Modify:** `src/ai_operator/config.py` — đổi comment `THUMB_RELEVANCE_MIN` sang thang 0..1 (giá trị người dùng chốt)

## Implementation steps
1. Thêm `score_image_relevance()` vào `llm_client.py` (lazy import genai, reserve budget, prompt số đơn, parse float, clamp 0..1, None khi blocked/parse-fail).
2. Tạo `media/relevance_scorer.py`: `available()` (GEMINI_API_KEY), `score(subject, path)` (đọc+downscale bytes → gọi llm_client).
3. Sửa `_relevance_gate`: dùng `relevance_scorer`; khi `not available()` → `log.warning` + ops signal, return `paths` (chưa gate — tạm cho qua, xem Unresolved #2).
4. Cập nhật config comment + giá trị threshold (hỏi người dùng, xem dưới).
5. Compile-check (`python -c "import ..."`).

## Todo
- [ ] `score_image_relevance()` trong llm_client
- [ ] `media/relevance_scorer.py` (`available`/`score`)
- [ ] `_relevance_gate` dùng scorer + fail-loud
- [ ] threshold 0..1 trong config
- [ ] compile-check

## Success criteria
- Có `GEMINI_API_KEY` → gate thật sự chấm điểm từng ảnh archival, log dòng điểm; ảnh sai-sự-kiện rớt.
- Không có key → log WARNING rõ + ops signal, không crash.
- Không import torch ở đường thumbnail.

## Risks
- Latency/cost Gemini per-image (nhỏ; free tier). → downscale ảnh, `thinking_budget=0`.
- Gemini trả text lạ thay vì số → parse phòng thủ, None-safe.
- Rate limit free tier khi nhiều ảnh → giữ số ảnh chấm ở mức ứng viên archival (đã ít).

## Security
- Không log nội dung ảnh; chỉ log tên file + điểm. Không rò `GEMINI_API_KEY`.

## Next steps → Phase 02 (rank theo điểm relevance vừa có).

## ⚠️ Cần người dùng quyết trước khi code
1. **Threshold mới** (thang Gemini 0..1): đề xuất **0.5**. Giữ/đổi?
2. **Fallback khi Gemini không available/lỗi:** (a) cho qua best-frame + log ops [mặc định, luôn có thumbnail],
   hay (b) chặn/đánh dấu để không publish ảnh nghi sai? → mặc định (a).
