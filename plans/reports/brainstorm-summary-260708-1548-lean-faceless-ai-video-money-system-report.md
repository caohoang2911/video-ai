# Brainstorm Summary — Hệ thống video AI faceless bán tự động (Lean, English-first)

> Ngày: 2026-07-08 · Trạng thái: **ĐÃ HỘI TỤ — sẵn sàng /ck:plan**
> Nguồn: 4 research workflow (monetization, policy, tooling, niche, market, cost/profit) — chi tiết cuối file.

---

## 1. Problem statement & mục tiêu

Xây hệ thống **bán tự động** tạo video AI (script → giọng → hình → ghép → duyệt → đăng YouTube) để **kiếm tiền**. Build theo hướng **Hybrid** (code lõi Python + gọi API AI). Codebase greenfield (trống hoàn toàn).

**Ràng buộc chốt (do user quyết):**
- Vận hành: **Semi-auto + cổng người duyệt ~10 phút/video** (không full-auto — lý do ở §3).
- Định dạng: **Long-form 8-15 phút**.
- Ngân sách: Pro (~$50-150/tháng) khả dụng, nhưng **giai đoạn validate đốt tối thiểu**.
- Thị trường v1: **English (US/UK/CA/AU)**, English-only trước.
- Niche: **History / Documentary / kể chuyện**.
- Scope v1: **LEAN** — pipeline lõi + **1 kênh English**, 10-20 video/2-3 tháng, có kill-criteria; mở rộng Spanish (và VN dạng lồng tiếng) sau khi có traction.

---

## 2. Sự thật cốt lõi (nền cho mọi quyết định)

> **"100% tự động + kiếm tiền bền vững" trên YouTube 2026 = KHÔNG khả thi.** YouTube áp policy "inauthentic/mass-produced content" (15/7/2025); tháng 1/2026 xoá 16 kênh AI (4.7 tỷ view, ~$10M/năm). Full-auto "AI slop" → 80-95% bị demonetize trong 2-4 tuần.

⇒ Kiến trúc **bắt buộc** có: (a) **cổng người duyệt**, (b) **lớp originality** (góc nhìn riêng, hook riêng, research thật, thumbnail custom, bật nhãn AI), (c) **throttle 1-3 video/tuần/kênh**, (d) **chỉ dùng asset royalty-free**.

---

## 3. Quyết định & lý do (Q&A trail)

| Quyết định | Chọn | Lý do (data) |
|---|---|---|
| Build approach | Hybrid (Python core + API) | Kiểm soát cao, chi phí thấp, tránh template-signature của SaaS |
| Mức tự động | Semi-auto + review gate | Full-auto → demonetize; review gate = "original value" để sống sót policy |
| Định dạng | Long-form 8-15 phút | RPM $1-25 vs Shorts $0.01-0.07; long-form ăn tiền AdSense mid-roll |
| Thị trường | English (US/UK/CA/AU) | CPM $18-40 (cao nhất) + **user tự QA được** → review gate mới hiệu quả |
| ~~Nhật~~ | **Loại** | QA tiếng Nhật bất khả thi cho solo → review gate vô dụng → rủi ro demonetize cao |
| Niche | History/Documentary | An toàn policy (narrative = original value), retention cao, evergreen, dễ tự động |
| Scope v1 | Lean English-only | EV thật quá thấp + kênh VN lỗ ròng → validate trước khi scale (YAGNI) |

---

## 4. Niche — sub-niche "cửa" nhất (điểm cơ hội)

3 sub-niche ghi điểm cao ở **cả 3 thị trường** → tái dùng research khi mở rộng (DRY):

| Sub-niche | 🇺🇸 EN | 🇪🇸 ES | 🇻🇳 VN | CPM | Kênh tham chiếu |
|---|---|---|---|---|---|
| **Thảm hoạ hàng hải bị lãng quên** ⭐ | 8 | 7 | 8 | $10-15 | Fascinating Horror, Forgotten Disasters |
| **Business Collapse / sụp đổ DN** | **8** | — | — | **$12-20** | TheCollapseCo, The Business Graveyard |
| **Điệp vụ Chiến tranh Lạnh (giải mật)** | 7.5 | 7.5 | 7 | $12-18 | Mark Felton Productions |
| **Lịch sử vật dụng hàng ngày** | 7 | **8** | 7 | $8-12 | Today I Found Out |

**Đề xuất niche kênh English v1:** **Thảm hoạ hàng hải bị lãng quên** (evergreen + tái dùng đa thị trường + cạnh tranh thấp = tốt cho lean + clone sau) — HOẶC **Business Collapse** nếu ưu tiên CPM cao nhất. *(Chốt cuối ở bước /ck:plan.)*

---

## 5. Kiến trúc đề xuất (Lean v1)

**Pipeline module hoá (mỗi module <200 dòng, kebab-case, snake_case cho Python):**

```
[1] topic-backlog     → chọn chủ đề từ danh sách curated (human seed = originality)
[2] script-generator  → Claude viết script 8-15' + góc riêng + hook; step research/nguồn
[3] tts-narrator      → ElevenLabs (Starter khi validate) → audio
[4] visual-fetcher    → Pexels/Pixabay stock + SDXL/Flux local, khớp beat script; Ken Burns
[5] video-assembler   → FFmpeg/MoviePy: ghép narration+visual+caption(Whisper)+nhạc+intro/outro
[6] review-gate       → render preview → NGƯỜI DUYỆT ~10' → approve/edit/reject   ⟵ policy-critical
[7] publisher         → YouTube Data API: upload + SEO metadata + AI-disclosure + schedule
[8] state-tracker     → SQLite: chủ đề đã dùng, trạng thái upload, analytics
```

**Stack:** Python 3.11 · FFmpeg + MoviePy 2.x · faster-whisper (local, free) · ElevenLabs SDK · Anthropic/Gemini SDK · Pexels/Pixabay API · google-api-python-client (YouTube) · SQLite (v1) → Postgres (sau) · orchestration = job-runner đơn giản + cron (KISS — **chưa cần** n8n/Celery/K8s ở v1).

**Học từ open-source (KHÔNG fork thẳng):** MoneyPrinterTurbo (96k⭐), ShortGPT, OpenShorts → tham chiếu kiến trúc; tự viết lớp originality để tránh bị nhận diện template.

**Anti-slop / compliance layer (bắt buộc):** góc video độc nhất · cấu trúc script biến thiên · research/nguồn thật · thumbnail custom · bật nhãn "altered/synthetic content" · chỉ asset royalty-free (Pexels/Pixabay + nhạc licensed) · ≤3 video/tuần.

---

## 6. Roadmap phân kỳ + Kill-criteria

| Phase | Thời gian | Mục tiêu | Chi tiêu |
|---|---|---|---|
| **P0 — Validate** | Tháng 1-3 | Pipeline lõi + 1 kênh EN + 1 sub-niche, **10-20 video** | ~$0-30/tháng (Starter+free stock) + setup |
| **P1 — Scale EN** | Tháng 3-6 | Nếu pass → lên Pro, tăng cadence, tối ưu retention/SEO, đạt YPP | ~$120/tháng |
| **P2 — Mở rộng** | Tháng 6+ | Clone pipeline sang Spanish; shorts funnel; VN chỉ dạng lồng tiếng | ~$120-155/tháng |

**✅ Pass P0 (đi tiếp):** sau ~20 video → view trung bình có xu hướng tăng, vài video >5-10K view, retention >30-40%, không policy strike.
**🛑 Kill P0 (dừng/đổi niche):** sau 20 video/3 tháng view phẳng <2-5K, không tín hiệu tăng → dừng (mất tối đa ~$1K thay vì $5K).

---

## 7. Chi phí & Lợi nhuận (trung thực)

**Chi phí:** cố định **~$120-155/tháng** (steady-state 3 kênh) · biến ~$0.07-0.12/video · setup 1 lần ~$500-3K · thời gian **~2-3h/tuần**. **Chi phí KHÔNG phải rào cản.**

**Lợi nhuận — mô hình (net/tháng, giả định top-15%):** Conservative T24 $2,200 · Base T24 $3,500 · Optimistic T24 $5,000.

**⚠️ Lợi nhuận — SAU phản biện (con số nên tin):**
- ~3% kênh faceless đạt bật tiền; với niche history + solo → **~0.3-0.5% đạt $1K+/tháng**.
- **~91% xác suất = $0** (burnout tháng 4-6 / kênh chết / demonetize).
- **Expected value: ~$40-60/tháng (T12) · ~$130-250/tháng (T24)** — thấp hơn model 8-25×.
- Hoà vốn thực **~tháng 16-20**, xác suất đạt ~**9%**; cần runway **$4-5K**.
- **Kênh VN gần như không hoà vốn** (CPM ~$0.30).
- ROI kể cả thành công ≈ **$1.5/giờ**.

> Không phải passive income — là content business, thất bại 85-90%. Đáng làm chỉ khi có **đam mê history + runway 1-2 năm + chấp nhận rủi ro**.

---

## 8. Rủi ro & Giảm thiểu

| Rủi ro | Giảm thiểu |
|---|---|
| Demonetize (policy AI) | Review gate + lớp originality + AI disclosure + ≤3 video/tuần |
| Content ID / bản quyền | Chỉ Pexels/Pixabay + nhạc licensed; audit asset trước upload |
| Burnout (solo, 91% bỏ cuộc) | Lean 1 kênh, cadence vừa phải, kill-criteria, batch sản xuất |
| Giọng AI bị nhận ra synthetic | ElevenLabs chất lượng cao + narration tự nhiên; A/B test hook 30s đầu |
| Đốt tiền vô ích | Validate rẻ trước; chỉ lên Pro/GPU khi có traction |
| YouTube API quota | Cadence thấp an toàn; verify quota mới (~100 video/ngày 2026) khi build |

---

## 9. Open questions (chốt ở /ck:plan)

1. **Sub-niche kênh English v1:** Thảm hoạ hàng hải (evergreen, reusable) vs Business Collapse (CPM cao nhất)? — *đề xuất: Hàng hải*.
2. **Voice:** ElevenLabs Starter ($10) hay free-tier/Edge cho giai đoạn validate?
3. **Hạ tầng validate:** chạy local hay Fly.io/Railway ngay từ P0?
4. **Ideation:** danh sách chủ đề curated tay hay LLM đề xuất từ seed (rồi người duyệt)?

---

## 10. Next step

→ `/ck:plan` (tạo plan phân phase cho **P0 — Lean validation pipeline + 1 kênh English**). Đề xuất mode: **`/ck:plan --tdd`** không cần (greenfield, chưa có behavior để khoá) → dùng **`/ck:plan` mặc định**.

### Nguồn research (workflow task IDs)
`wutgtjpo8` (monetization/policy/tooling/upload/reference) · `wf9u8t0ur` (market) · `wrnapo4l4` (sub-niche) · `w079pje57` (cost/profit + skeptic). Raw output trong `scratchpad`/tasks.
