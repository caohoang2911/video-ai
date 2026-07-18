---
title: Short overlay white/red curiosity-gap headline standard
description: >-
  Replace the short's terse gold top-overlay with a white-setup / red-gap
  curiosity headline, reusing the shipped poster engine; unify title-craft
  across long+short.
status: pending
priority: P2
branch: feat/ops-observability-validation
tags:
  - shorts
  - overlay
  - thumbnail
  - content-generation
blockedBy: []
blocks: []
created: '2026-07-17T20:43:34.968Z'
createdBy: 'ck:plan'
source: skill
---

# Short overlay white/red curiosity-gap headline standard

## Overview

Đổi overlay top của Short từ **≤6-từ gold đơn sắc** (`_pinned_title_fx`) sang **"White-set / Red-gap Headline"**: dòng setup off-white + dòng gap đỏ (số/stake, giữ payoff không giải), 7-14 từ, 2-3 dòng — giống reference @DailyDoseOfHistoryFacts. Tái dùng engine poster đã ship (`thumbnail_style.py`: font Impact, đỏ payoff, `_accent_targets`). Đồng thời đồng bộ *thuật toán* craft (entity + information-gap + inverted-U) giữa long title và short qua 1 fragment prompt dùng chung.

Xây tiếp trên 2 plan đã DONE: `260717-2335-thumbnail-hybrid-cinematic-upgrade` (poster engine) + `260715-1749-shorts-motion-captions-...` (short render/overlay).

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Overlay Render + A/B Case](./phase-01-overlay-render-a-b-case.md) | Completed |
| 2 | [Headline Content Gen](./phase-02-headline-content-gen.md) | Completed |
| 3 | [Shared Craft Fragment](./phase-03-shared-craft-fragment.md) | Deferred (YAGNI) |
| 4 | [Tests + Docs](./phase-04-tests-docs.md) | Completed |

Thứ tự phụ thuộc: P1 (renderer + gate quyết định) → P2 (nội dung, cần interface renderer) → P4 (test+docs). **P3 bỏ** (2026-07-18, user duyệt): P2 đã đồng bộ prompt short theo standard rồi; gom craft chung chỉ là refactor thuần, rủi ro làm trôi chất lượng title long > lợi ích — để sau nếu cần.

## Decisions (user-confirmed)
- **Option 1**: full white/red curiosity-gap headline (bỏ style ≤6-từ). User chọn 2026-07-18.
- **Kiểu chữ = Title Case** (khóa 2026-07-18 sau A/B ảnh thật). Config `SHORTS_HEADLINE_CASE="title"` (default).
- Overlay ≠ metadata title = **partners** (mirror keyword, không trùng nguyên văn).

## Deviations vs plan (implementation)
- Render: dùng **drawtext đa dòng 2 màu** (không bake PNG/`movie` overlay) — hợp `post_fx` contract, không cần sửa `burn_and_mux`.
- **Không extract primitives** từ `thumbnail_style` (giữ nguyên → 0 rủi ro regression thumbnail); logic đỏ line-level tự chứa trong `headline_text.py`.
- Ngoài scope, chưa xử: `_PORTRAIT_SUB_STYLE` (`short_builder.py`+`ass_karaoke_writer.py`) sửa từ phiên trước, chưa commit — cần user kiểm 2 file khớp.

## Why (deep-research backed)
Report: `plans/reports/` (deep-research 2026-07-18, 21 nguồn, 14 confirmed/11 refuted). Primary: *When curiosity gaps backfire* (Nature Sci Rep 2025, PMC11704130).
- **Inverted-U concreteness**: nhồi entity/số tối đa → đóng gap → GIẢM CTR. Giữ middling (1 known anchor + giấu payoff).
- History niche dùng **7-14 từ / 2-3 dòng**; "terse-fragment-only" và "payoff-first" đều bị bác 0-3.
- Nhấn mạnh = 1 phần tử đỏ (scarcity); đổi màu chữ hợp lệ.
- Codebase đã đúng: `script_system.md:147` đã cite inverted-U cho `thumbnail_text` → chỉ mang sang short.

## Render architecture (chốt)
Bake RGBA banner PNG (trắng/đỏ, PIL, tái dùng primitives của `thumbnail_style`) → `_pinned_title_fx` trả filter `movie=banner.png[bn];[vin][bn]overlay=0:Y` (tĩnh trên video pan, giống drawtext sau zoompan). Không đụng zoompan/still.

## Key files
- Modify: `assembler/short_builder.py` (`_pinned_title_fx`), `content/short_schema.py`, `content/short_script_generator.py`, `prompts/script_system.md`
- Create: `assembler/headline_text.py` (primitives dùng chung), `prompts/_title_craft.md` (fragment)
- Config: `config.py` — `SHORTS_HEADLINE_CASE` (title|upper)

## Success criteria (plan-level)
- [ ] Short render overlay trắng/đỏ, đọc rõ ở phone trong top band, né UI zone.
- [ ] User khóa kiểu chữ sau A/B.
- [ ] Headline sinh tự động đúng standard (7-14 từ, gap giữ, partner với title).
- [ ] Craft entity+gap DRY (1 nguồn cho long+short).
- [ ] Tests xanh (renderer + schema + thumbnail regression).

## Dependencies
Không blocking chéo (2 plan nền đã DONE). Chỉ đọc/tái dùng, không sửa contract của chúng ngoài việc extract primitives ở P3/P1 (có test regression thumbnail ở P4).
