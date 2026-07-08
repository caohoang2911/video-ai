# Phase 09 — Validation Run + Kill-Criteria

## Context Links
- Overview: [plan.md](plan.md) · Prev: [phase-08](phase-08-observability-deploy.md)
- Design doc §6 (roadmap + kill-criteria), §7 (cost/profit trung thực).

## Overview
- **Priority:** P0 (đây là mục tiêu cuối của P0 — quyết định sống/chết dự án bằng data)
- **Status:** pending
- **Description:** Chạy pipeline tạo **10-20 video / 2-3 tháng** trên 1 kênh English niche maritime, theo dõi metrics thật, áp **kill-criteria** khách quan; định nghĩa tiêu chí lên P1 (scale EN) và P2 (thêm Spanish).

## Key Insights (từ design doc §7 — trung thực)
- **~91% xác suất = $0**; niche history solo → ~0.3-0.5% đạt $1K+/tháng. Đây là **content business, không phải passive income**. Validate rẻ để cắt lỗ sớm.
- **Kill sớm = tiết kiệm**: dừng ở ~$1K thay vì đốt $5K. Kill-criteria phải khách quan, không cảm tính.
- Metrics quan trọng hơn view tuyệt đối ở giai đoạn đầu: **retention (avg view %) + CTR + xu hướng tăng** — tín hiệu YouTube "đáng đẩy".
- **Analytics latency 48-72h** → chỉ đánh giá video ≥1 tuần tuổi.
- **Template-similarity audit** (mốc 5-10 và 20 video): đo % tương đồng cấu trúc narrative giữa các script. >50% cùng pattern → cảnh báo redesign trước khi YouTube gắn cờ inauthentic/spam (mass-produced) — bảo vệ kênh sớm hơn là chờ bị demonetize.
- **Decision gate xét chất lượng, không chỉ view thô**: kiểm 30s-retention & CTR theo ngưỡng phase 07 — view cao nhưng 30s-retention/CTR thấp = tín hiệu giả, không đủ để PASS.

## Requirements
Functional:
1. Sản xuất 10-20 video qua pipeline (bán tự động, user duyệt từng cái).
2. Thu metrics mỗi tuần (phase 07 analytics) → bảng `analytics`.
3. Report định kỳ (2 tuần/lần) tổng hợp: avg view, retention, CTR, RPM, xu hướng.
4. Áp decision gate ở mốc ~10 video và ~20 video.
Non-functional: quyết định dựa data ghi lại (audit trail), không ad-hoc.

## Architecture — decision flow
```
produce 10-20 videos (cadence ≤3/wk) ─► weekly analytics pull ─► validation_report
                                                                    │
                    template-similarity audit (mốc 5-10) ───────────┤
                          │  >50% cùng narrative pattern → redesign trước khi bị flag
                          │
                          ┌──────────── mốc ~10 video ─────────────┤
                          │  early signal? (≥1 video >5K, retention>30%, 30s-ret & CTR ≥ ngưỡng p07)
                          │     no strong negative → tiếp tục tới 20
                          ▼
                    mốc ~20 video (≈3 tháng)
              ┌───────────────┴────────────────┐
        PASS P0                              KILL P0
  vài video >5-10K view,               view phẳng <2-5K,
  retention >30-40%, 30s-ret+CTR đạt,  không tín hiệu tăng,
  xu hướng tăng, 0 policy strike       retention <30% / CTR thấp
        │                                     │
        ▼                                     ▼
   → P1 (scale EN, Pro, YPP)          dừng / đổi niche (mất ~$1K)
```

## Related Code Files
- Create: `src/ai_operator/validation/validation_report.py` (tổng hợp analytics → report markdown/telegram), `src/ai_operator/validation/kill_criteria.py` (đánh giá pass/kill theo ngưỡng), `docs/validation-log.md` (nhật ký quyết định, cập nhật tay + auto).
- Modify: `cli.py` (`validation-report`, `check-kill`).
- Delete: none.

## Implementation Steps
1. `kill_criteria.py`: hằng số ngưỡng (từ design doc): `MIN_VIDEOS_DECISION=20`, `FLAT_VIEW_MAX=5000`, `RETENTION_MIN_PCT=30`, `PASS_VIEW_HITS=1 (>5000)`; thêm ngưỡng chất lượng `RETENTION_30S_MIN_PCT`, `CTR_MIN_PCT` (đồng bộ giá trị định ở phase 07 — hardcode 1 chỗ, không tự chọn số mới). Hàm `evaluate(analytics_rows) -> {'decision': 'continue'|'pass'|'kill', 'reasons': [...]}` — PASS yêu cầu view hit VÀ 30s-retention & CTR đạt ngưỡng (chặn view giả).
2. `validation_report.py`: query `analytics` + `uploads` → tính avg view, median retention, **30s-retention & CTR**, RPM, xu hướng (slope view theo thời gian đăng); render report → gửi Telegram + ghi `docs/validation-log.md`.
3. `template_similarity.py`: đọc script/narrative của các video đã sản xuất → tính % tương đồng cấu trúc (ví dụ so khớp beat/section sequence hoặc embedding cosine); trả `max_pairwise_pct` + cụm trùng. Lý do: script rập khuôn dễ bị YouTube xếp mass-produced/inauthentic → demonetize.
4. Vận hành: sản xuất video theo cadence; user duyệt; mỗi thứ Hai chạy `validation-report`.
5. Mốc ~5-10 video: chạy template-similarity audit — nếu >50% cùng narrative pattern → cảnh báo redesign template (đa dạng hook/cấu trúc) TRƯỚC khi lên tiếp; tránh nhân bản lỗi ở quy mô.
6. Mốc ~10 video: chạy `check-kill` — nếu có tín hiệu âm mạnh (0 video >2K, retention <20%, 30s-ret/CTR dưới ngưỡng) → cảnh báo cân nhắc pivot niche sớm.
7. Mốc ~20 video / 3 tháng: chạy `check-kill` → PASS/KILL theo ngưỡng (gồm 30s-retention & CTR); chạy lại template-similarity audit; ghi quyết định + lý do vào `validation-log.md`.
8. Nếu PASS → mở phase P1 (scale): tăng cadence, lên Pro, tối ưu retention/SEO/thumbnail A/B, mục tiêu YPP (1K subs + 4K giờ).
9. Nếu KILL → dừng hoặc đổi sub-niche (Business Collapse — CPM cao hơn, cùng pipeline, DRY reuse); tái validate 1 vòng ngắn.

## Todo List
- [ ] kill_criteria.py (ngưỡng + evaluate — gồm 30s-retention & CTR đồng bộ phase 07)
- [ ] validation_report.py (tổng hợp + 30s-ret/CTR + Telegram + log)
- [ ] template_similarity.py (% tương đồng narrative + cảnh báo >50%)
- [ ] docs/validation-log.md (audit trail quyết định)
- [ ] cli validation-report / check-kill / template-audit
- [ ] sản xuất 10-20 video (vận hành)
- [ ] template-similarity audit mốc 5-10 + mốc 20 ghi lại
- [ ] decision gate mốc 10 + mốc 20 ghi lại

## Success Criteria (của phase — không phải của business)
- 10-20 video published thật (public sau API audit) trong 2-3 tháng, ≤3/tuần, 0 policy strike.
- `validation-report` chạy weekly, số liệu khớp YouTube Studio (spot-check).
- `check-kill` ở mốc 20 trả quyết định rõ ràng + lý do, ghi vào `validation-log.md`.
- Quyết định P1/P2/kill dựa data ghi lại, không cảm tính.

## Kill / Pass Criteria (chốt từ design doc §6)
- 🛑 **KILL:** sau ~20 video/3 tháng, view TB phẳng <2-5K, retention <30%, không xu hướng tăng → dừng hoặc đổi niche.
- ✅ **PASS → P1:** vài video >5-10K view, retention >30-40%, xu hướng tăng, 0 strike.
- ➡️ **P2 (sau P1 thành công):** clone pipeline sang Spanish (i18n content+voice), shorts funnel; VN chỉ lồng tiếng (CPM thấp, cân nhắc kỹ).

## Risk Assessment
| Risk | L | I | Mitigation |
|---|---|---|---|
| Bám niche quá lâu dù data xấu (sunk cost) | High | High | Kill-criteria khách quan + audit trail; quyết ở mốc cố định. |
| Burnout tháng 4-6 (91% bỏ) | High | High | Lean 1 kênh, cadence vừa, batch, kill sớm nếu xấu. |
| Đánh giá non (chưa đủ tuổi video) | Med | Med | Chỉ tính video ≥1 tuần; latency 72h. |
| Policy strike giữa chừng | Low | High | Review gate + originality + AI label + ≤3/tuần (đã có); strike = tín hiệu kill mạnh. |
| Metrics tốt nhưng RPM chưa có (chưa YPP) | High | Low | Giai đoạn này đánh giá retention/view/xu hướng, không phụ thuộc doanh thu. |
| Script rập khuôn → YouTube gắn cờ mass-produced/inauthentic → demonetize | Med | High | Template-similarity audit mốc 5-10 & 20; >50% cùng pattern → redesign hook/cấu trúc trước khi nhân bản. |
| View cao nhưng chất lượng giả (30s-ret/CTR thấp) đánh lừa PASS | Med | Med | Decision gate xét 30s-retention & CTR theo ngưỡng phase 07, không chỉ view thô. |

## Security Considerations
- `validation-log.md` không chứa số liệu nhạy cảm ngoài phạm vi; không commit doanh thu chi tiết nếu repo public.
- Đảm bảo mọi video published giữ AI disclosure + asset royalty-free (audit `assets` trước mỗi upload — phase 06).

## Next Steps
- PASS → mở nhánh plan P1 (scale EN) mới.
- KILL → plan pivot niche (Business Collapse) hoặc dừng, đóng gói lesson vào `/ck:journal`.

## Unresolved Questions
- Ngưỡng "vài video" = mấy? — đề xuất ≥2 video >5K trong 20 để coi là tín hiệu PASS (điều chỉnh theo baseline niche).
- Có A/B thumbnail ngay trong P0 không? — đề xuất có (native Test&Compare) từ video ~#5 để học sớm CTR.
