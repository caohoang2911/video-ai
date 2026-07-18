# Thumbnail Event-Relevance Gate — Overview

**Vấn đề:** thumbnail chọn ảnh "chưa bám sát sự kiện". Root cause chính: CLIP relevance gate
gần như **luôn tắt** trong env render (torch chỉ nằm trong extra `sdxl`, không phải core dep →
`_relevance_gate` fail-open, cho qua hết) → hero chọn thuần theo thẩm mỹ, không theo đúng sự kiện.
Phụ: người thắng theo thẩm mỹ chứ không relevance; anchor yếu (`title.split(":")`); pool
non-archival không gate; prompt synthetic thiếu entity.

**Quyết định người dùng (đã chốt):**
- Scorer = **Gemini vision** (`google-genai` đã là core dep + free tier; không thêm key/dep; xóa bẫy torch-drift).
- Tiêu chí hero = **relevance-first** (thẩm mỹ chỉ là tie-break).
- Phạm vi = **Full R1–R5**. Opus subscription KHÔNG dùng được cho backend (chỉ pay-per-token); Gemini rẻ hơn.

## Nguyên tắc
YAGNI / KISS / DRY. Không thêm field schema người dùng chưa xác nhận — tái dùng `event_year` +
`Topic.title`. Gate phải **fail-loud + observable**, không im lặng cho qua.

## Phases

| # | Phase | Trạng thái | Mục tiêu |
|---|-------|-----------|----------|
| 01 | [Gemini relevance scorer + fail-loud](phase-01-gemini-relevance-scorer.md) | ✅ done | Module scorer mới (Gemini vision, 0..1), budget-hooked, observable; thay cơ chế gate |
| 02 | [Relevance-first hero selection](phase-02-relevance-first-selection.md) | ✅ done | Chọn hero theo relevance, thẩm mỹ là tie-break (+ giữ dedup near-dup) |
| 03 | [Precise event anchor](phase-03-precise-event-anchor.md) | ✅ done | `extract_entity` đa-delimiter, dùng đồng nhất query/gate/prompt |
| 04 | [Gate non-archival + entity-rich synthetic](phase-04-gate-nonarchival-and-synthetic.md) | ✅ done | Gate others khi archival rỗng; prompt FLUX synthetic entity+year |
| 05 | [Tests + verify](phase-05-tests-and-verify.md) | ✅ done | 479 tests xanh; gate loại ảnh sai-sự-kiện + fail-loud có test |

**Decisions chốt:** threshold=0.5 · fallback=cho qua best-frame + alert ops · scorer=Gemini vision.
**Code-review:** DONE_WITH_CONCERNS → 6 findings, 5 fixed + 1 nit accepted. Threshold cần calibrate trên data render thật (chưa làm).

## Key files (touch)
- `src/ai_operator/media/relevance_scorer.py` — **new** (Gemini vision abstraction: `available()`, `score()`)
- `src/ai_operator/content/llm_client.py` — thêm hàm gọi Gemini vision (tái dùng client + budget ledger)
- `src/ai_operator/assembler/thumbnail_generator.py` — `_relevance_gate`, `_gated_pools`, `_pick_hero`, `_hero_prompt`
- `src/ai_operator/media/visual_fetcher.py` — `_archival_anchor` (robustify)
- `src/ai_operator/config.py` — `THUMB_RELEVANCE_MIN` (giữ giá trị, người dùng quyết ở P02)
- `tests/` — test mới cho gate/selection

## Dependencies
P01 → P02 → (P03 ∥ P04) → P05. P03 và P04 độc lập, có thể làm song song sau P02.

## Unresolved (cần người dùng quyết trong lúc làm)
1. **Threshold** `THUMB_RELEVANCE_MIN` hiện `0.22` (thang CLIP cosine). Gemini trả 0..1 → **thang khác**,
   phải chọn ngưỡng mới (đề xuất ~0.5, calibrate ở P05). → hỏi khi tới P01.
2. **Fallback khi Gemini fail:** chặn thumbnail (an toàn "đúng sự kiện") hay cho qua best-frame
   (đảm bảo luôn có thumbnail)? → mặc định fail-loud + cho qua nhưng log ops; xác nhận ở P01.
3. R3 có cần thêm field `event_subject` không, hay reuse `Topic.title`+`event_year` là đủ? → đánh giá ở P03.
