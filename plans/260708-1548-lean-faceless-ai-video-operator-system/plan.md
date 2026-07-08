---
title: "AI-Operator — Kênh YouTube faceless documentary bán tự động (P0 Lean Validation)"
description: "Pipeline Python tạo video documentary maritime disasters, người dùng chỉ approve/reject qua Telegram ~5-10 phút/ngày"
status: pending
priority: P1
effort: ~60-80h (P0)
branch: main
tags: [python, youtube, ai-video, faceless, tts, moviepy, telegram, automation]
created: 2026-07-08
---

# AI-Operator — Kênh YouTube faceless documentary bán tự động

## Mục tiêu
Xây hệ thống **bán tự động** nuôi 1 kênh YouTube faceless documentary (English, niche "Forgotten Maritime Disasters", long-form 8-15'). AI + code làm HẾT (ý tưởng → script → giọng → hình → ghép → SEO → lịch → tối ưu analytics); người dùng chỉ **APPROVE/REJECT qua Telegram** ~5-10 phút/ngày. Review gate + lớp originality = sống sót policy AI của YouTube.

## Mô hình vận hành (đã chốt)
Pipeline module hoá, mỗi module <200 dòng (Python snake_case, file kebab-case). State machine điều khiển vòng đời video: `draft → scripted → voiced → rendered → pending_review → policy_ok → approved → published → analyzed` (+ nhánh `rejected`, `editing`, `rerun_queued`, `failed`). Cổng người duyệt là bắt buộc (policy-critical). Throttle **≤3 video/tuần**.

## Môi trường thực tế (đã verify)
- Máy: **Apple M1 Max, 64GB RAM** → local SDXL viable (không cần cloud gen ở P0).
- Python: máy có 3.14.5 nhưng **target 3.11** (MoviePy 2.x / faster-whisper / diffusers ổn định hơn) → cài qua pyenv/uv.
- Repo greenfield, chỉ có `.claude/`, `.gitignore`, `plans/`.

## Danh sách phase

| # | Phase | Priority | Status | Blockers |
|---|---|---|---|---|
| 00 | [Prerequisites — user setup](phase-00-prerequisites-user-setup.md) | P0 | pending | — (chỉ user làm) |
| 01 | [Project scaffold + config + DB schema](phase-01-project-scaffold-config.md) | P0 | ✅ done (verified: 9 tables, budget-cap, state-machine, checkpoint, dedup) | — |
| 02 | [Content engine (topic + script)](phase-02-content-engine.md) | P0 | ✅ code-complete + reviewed (runtime pending keys) | 01 |
| 03 | [Media engine (TTS + visuals)](phase-03-media-engine.md) | P0 | ✅ code-complete + reviewed (runtime pending keys) | 01, 02 |
| 04 | [Video assembler (MoviePy/FFmpeg/Whisper)](phase-04-video-assembler.md) | P0 | ✅ code-complete + reviewed (runtime pending keys) | 03 |
| 05 | [Review gate — Telegram bot](phase-05-review-gate-telegram.md) | P0 | ✅ code-complete + reviewed (runtime pending keys) | 04 |
| 06 | [YouTube publisher](phase-06-youtube-publisher.md) | P0 | ✅ code-complete + reviewed (runtime pending keys) | 00 (API audit), 05 |
| 07 | [AI-operator scheduler + analytics loop](phase-07-ai-operator-scheduler-analytics.md) | P1 | pending | 02-06 |
| 08 | [Observability + deploy](phase-08-observability-deploy.md) | P1 | pending | 07 |
| 09 | [Validation run + kill-criteria](phase-09-validation-run-kill-criteria.md) | P0 | pending | 06 (P0), 07-08 (P1) |

## Dependency graph (rút gọn)
```
00 ─┬─► 01 ─► 02 ─► 03 ─► 04 ─► 05 ─► 06 ─► 09(P0 run)
    │                                  ▲
    └─(API audit, OAuth, verify acct)──┘
02..06 ─► 07 (scheduler ghép chuỗi) ─► 08 (deploy) ─► 09(P1)
```
Đường tới video đầu tiên (critical path): 00 → 01 → 02 → 03 → 04 → 05 → 06. Phase 07/08 (tự động hoá + always-on) là P1 — P0 có thể chạy tay từng bước để lấy 10-20 video validate.

## Roadmap phân kỳ
- **P0 (Tháng 1-3):** phase 00-06 + 09 P0-run. 1 kênh EN, 1 sub-niche, 10-20 video. Chi ~$0-30/tháng (ElevenLabs Starter + free stock + local SDXL). Chạy tay/bán-tay chấp nhận được.
- **P1 (Tháng 3-6):** phase 07-08 full always-on; tối ưu retention/SEO; đạt YPP. ~$120/tháng.
- **P2 (Tháng 6+):** clone pipeline sang Spanish (i18n content-engine + voice), shorts funnel. Ngoài scope plan này.

## Kill-criteria (từ design doc §6)
- 🛑 **Kill P0:** sau ~20 video / 3 tháng, view trung bình phẳng <2-5K, không tín hiệu tăng, retention <30% → **dừng hoặc đổi niche** (chi tiết phase 09).
- ✅ **Pass P0 → P1:** vài video >5-10K view, retention >30-40%, xu hướng tăng, **0 policy strike**.

## Nguyên tắc kỹ thuật (bắt buộc mọi phase)
KISS / YAGNI / DRY · file <200 dòng · kebab-case filename · **KHÔNG** tham chiếu phase/finding trong code comment (giải thích "why", không "per phase-XX") · secrets qua `.env` (đã gitignore) · chỉ asset royalty-free · luôn bật AI disclosure (`containsSyntheticMedia=true`).

## Cải tiến từ verify (260708)
Xem chi tiết: [improvements-from-verify-260708.md](improvements-from-verify-260708.md). Verdict: **plan nền vững**, không cần đại tu. 3 vấn đề CRITICAL đã được xử lý ở các phase: nhãn AI (`containsSyntheticMedia`) ở **phase 01/06**, review 2-tầng (script + video) ở **phase 05**, analytics thresholds số hoá ở **phase 07/09**. File cải tiến còn liệt kê ~13 mục P0 (map theo phase), 10 mục DEFER-P1, 10 mục REJECTED (over-engineering).

## ⚠️ Pending code changes — anti-ban/flag (research 260708-1744)
Nguồn: [researcher-260708-1744-youtube-platform-ban-flag-risk-avoidance-report.md](../reports/researcher-260708-1744-youtube-platform-ban-flag-risk-avoidance-report.md). **Đã cập nhật SPEC trong plan (phase-02/03/05), NHƯNG CHƯA áp vào code** — status "code-complete" của phase 02-06 KHÔNG bao gồm 5 mục dưới. Implement sau qua `/ck:cook` (có test + review từng bước):
1. **P0-1 Voice nhất quán** (phase-03): khoá 1 `ELEVENLABS_VOICE_ID`; 1 video = 1 provider (không trộn); chỉ ElevenLabs được publish; fallback → cột mới `videos.needs_revoice` chặn publish. *(code `tts_narrator` hiện trộn provider/video.)*
2. **P0-2 Motion-first** (phase-03): `visual_fetcher` fetch **video b-roll** (Pexels/Pixabay Video API) ≥50-60% thời lượng; ảnh tĩnh chỉ khi thiếu footage. *(code hiện image-only.)*
3. **Payoff quality gate** (phase-02): `schema.PayoffNode` + `surprise_score` 1-5, reject <3. *(code hiện `payoff_nodes: list[str]` đếm số.)*
4. **Thumbnail_text pairing** (phase-02→04): `schema.TitleOption{title, thumbnail_text}`; thumbnail overlay dùng `thumbnail_text`. *(code hiện `title_options: list[str]`.)*
5. **EDSA checklist** (phase-05): `review/checklist.py` thêm mục EDSA (who/what/when/where/why nói trong narration) + hook/payoff + chặn `needs_revoice`.
- ✅ **Đã đúng trong code** (không cần sửa): Test & Compare thủ công — `publisher/ab_variants.py` (Studio-only, no API); plan-06/07 doc đã sync.

## Quyết định đã chốt (260708, user confirm)
- **Sub-niche kênh EN v1:** Forgotten Maritime Disasters (locked) — evergreen, reusable đa thị trường, cạnh tranh thấp.
- **Voice validate P0:** ElevenLabs Starter ($5/mo) (locked) — retention là thước đo validate nên cần giọng chất; Edge-TTS giữ làm fallback.

## Unresolved questions
Còn mở (KHÔNG chặn phase 01, chốt ở phase tương ứng): (1) music source — default YouTube Audio Library free (phase 04); (2) deploy target P1 — Fly.io vs Hetzner vs Mac always-on (phase 08); (3) CTR threshold pass — đề xuất 4-6% (phase 09); (4) ideation manual-curated vs LLM-from-seed — đề xuất LLM đề xuất rồi người duyệt (phase 02); (5) state machine enum tự viết vs lib — đề xuất enum (phase 01).
