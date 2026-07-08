# Chi phí & Lợi nhuận: Hệ thống Video AI Faceless Bán tự động (3 kênh)

## Tóm tắt Executive

Hệ thống video AI 3 kênh (English, Spanish, Vietnamese) faceless, long-form 8–15 phút, 8–12 video/tháng/kênh (steady-state 2–3 video/tuần) có chi phí operating **~$121–122/tháng** khi tất cả 3 kênh active. Người dùng solo dành ~1–1.5 giờ/tuần duyệt & approve. Setup một lần ~$2,500–4,000 (founder time không bill). **Margin cao** nếu monetize via ads/affiliate; breakeven ~1,000–2,000 views/tháng/kênh @ $1–3 CPM.

---

## 1. Chi phí Fixed Monthly (Dịch vụ Subscription)

| Item | Cost | Note |
|------|------|------|
| **ElevenLabs Pro** | $99/tháng | 600k chars/tháng (V2 model) hoặc 1M chars (V2.5 Flash). Dùng cho English + Spanish; Vietnamese dùng XTTS free |
| **Claude API (Script Gen)** | $5/tháng | Haiku $1/$5 per 1M tokens. ~500k tokens/tháng @ ~$5. Hoặc Gemini 3.5 Flash rẻ hơn (~$1.50/1M) |
| **Fly.io (Hosting)** | $15/tháng | Pay-as-you-go compute + bandwidth. Video pipeline, API proxy, worker tasks. Small app típ $8–25/tháng |
| **YouTube Data API** | $0/tháng | Free quota (10k units/day mới là separate buckets cho search.list & videos.insert) |
| **XTTS/Whisper (Local)** | $0/tháng | Whisper local (free, open-source) hoặc OpenAI Whisper API $0.003–0.006/phút = ~$0.05–0.09/video (tính riêng per-video) |
| **Total Fixed** | **$119/tháng** | Cơ bản, 3 kênh steady-state |

---

## 2. Chi phí Per-Video (Biến)

| Item | Cost | Calculation |
|------|------|-------------|
| **Script Generation (Claude Haiku)** | $0.008 | ~1,000 tokens input + 500 output = 1,500 tokens @ $1/$5 = $0.008 per script |
| **Text-to-Speech (TTS)** | Included | ElevenLabs Pro covers ~100 videos (600k chars ÷ 6k chars/video). Overage $0.24/1k chars = ~$0.0015/video if exceed |
| **Captions (Whisper API)** | $0.05–0.09 | $0.003/min × 10–15 min = $0.03–0.045 per video. Dùng GPT-4o Mini ($0.003/min) cheaper |
| **Video Generation (Stock/SDXL/Kling)** | $0–0.50 | Free (Pexels/Pixabay stock) + local SDXL (~$0.001 electricity per image). Nếu dùng Kling Pro (~$37/tháng) = ~$0.25/video (37 ÷ 150 videos) |
| **Editing & Upload (FFmpeg/MoviePy)** | $0 | Local, free |
| **Hosting Video (CDN/YouTube)** | $0 | YouTube hosts free. Cross-post (TikTok/Reels) via free APIs |
| **Total Per-Video** | **$0.07–0.12** | Base: $0.06–0.09 (script + captions), +$0–0.50 if premium video gen |

**Scenario A: Free stock + local SDXL** → $0.07/video
**Scenario B: Kling Pro included** → $0.12/video

---

## 3. One-Time Setup & Infrastructure

| Item | Cost | Detail |
|------|------|--------|
| **GPU Hardware** | $250–1,500 | RTX 3060 used ($250) or RTX 4070 ($500–600). Hoặc lease cloud GPU $89–150/tháng thay vì buy. Không tính nếu có sẵn |
| **Dev Time (Pipeline)** | $2,000–3,000 | 40–60 giờ setup script→TTS→video→upload automation. @ $50/hr. Hoặc founder không bill |
| **Channel Setup** | $250–500 | YouTube channel branding (banner, description, playlists), TikTok/Reels setup, thumbnails. 5–10 giờ @ $50/hr |
| **Testing & QA** | $250–500 | Generate 5–10 test videos, quality check, optimize pipeline. 5–10 giờ @ $50/hr |
| **Subtitles/Captions Setup** | $100–200 | Whisper API key setup, caption styling (SRT templates), testing |
| **Custom XTTS Voice Training** (optional) | $0–300 | Clone voice nếu muốn narration riêng. Mất thêm ~5 giờ |
| **Total One-Time** | **$2,850–5,500** | Điển hình $3,000 (founder time không bill). Nếu lease GPU thay buy: -$250–1,500 |

---

## 4. Scenarios: Chi phí Hàng tháng theo Volume

### Scenario 1: Ramp-up (Tháng 1–2, English only)

- **Volume:** 8–12 video/tháng
- **Fixed:** ElevenLabs Free/$10 Creator tier (nếu ít dùng) + Claude $5 + Fly.io $15 = **$30–40/tháng**
- **Per-video:** 10 × $0.075 = **$0.75**
- **Total:** **$31–41/tháng**
- **Cost/Video:** $3.10–4.10

**Hoặc jump luôn Pro:** Fixed $119 + (10 × $0.075) = **$120/tháng** (chênh lệch $80–90, nhưng avoid switching overhead)

---

### Scenario 2: Mid Growth (Tháng 3–4, English + Spanish starting)

- **Volume:** 16–20 video/tháng (8 English + 8–12 Spanish)
- **Fixed:** $99 (ElevenLabs Pro) + $5 (Claude) + $15 (Fly.io) = **$119/tháng**
- **Per-video:** 18 × $0.075 = **$1.35**
- **Total:** **$120/tháng**
- **Cost/Video:** $6.67

---

### Scenario 3: Steady-State (Tháng 5+, tất cả 3 kênh)

#### Scenario 3A: 24 video/tháng (8/kênh, 2/tuần/kênh)
- **Fixed:** $119
- **Per-video:** 24 × $0.075 = $1.80
- **Total:** **$121/tháng**
- **Cost/Video:** $5.04
- **Annual:** $1,452

#### Scenario 3B: 36 video/tháng (12/kênh, 3/tuần/kênh)
- **Fixed:** $119
- **Per-video:** 36 × $0.075 = $2.70
- **Total:** **$122/tháng**
- **Cost/Video:** $3.39
- **Annual:** $1,464

#### Scenario 3C: Premium (Kling Pro for B-roll)
- **Fixed:** $99 (ElevenLabs) + $5 (Claude) + $15 (Fly.io) + $37 (Kling Pro) = **$156/tháng**
- **Per-video:** 24 × ($0.075 - $0.25 stock cost + $0.25 Kling) = 24 × $0.10 = $2.40
- **Total:** **$158/tháng** (24 video/tháng)
- **Cost/Video:** $6.58
- **Rationale:** Kling Pro giảm gen time, tăng quality, nhưng cost cao hơn stock+SDXL

---

## 5. Breakdown Chi phí: Realistic Case (3 kênh, 24–36 video/tháng)

| Service | Monthly | Note |
|---------|---------|------|
| **TTS (ElevenLabs Pro)** | $99 | Fixed 600k chars; within budget cho 3 kênh |
| **LLM API (Script)** | $5 | Claude Haiku, 500k tokens/tháng |
| **Hosting (Fly.io)** | $15 | Compute + bandwidth (video processing, API) |
| **Captions (Whisper)** | $1.50–2.25 | 24–36 video × $0.06–0.09 per video; hoặc local free |
| **Video Gen (Free)** | $0 | Pexels/Pixabay + local SDXL electricity (~$20/tháng, không bill separate) |
| **YouTube API** | $0 | Free (chỉ quota limit) |
| **XTTS (Free)** | $0 | Local, no cost |
| **Infrastructure electricity** | $20–30 | RTX 3060 ~ 8 hrs/day ~$0.50–1.00/day = $15–30/tháng |
| **ISP/Broadband** | (existing) | Already paying, không count |
| | | |
| **Monthly Total** | **$120–152** | Base $120 (free stock+SDXL), +$32 if Kling Pro |
| **Cost per Video** | **$3.33–6.33** | 24 vs 36 video/tháng, free vs premium gen |

---

## 6. Time Cost: Solo Operator Burden

| Task | Time/Video | Volume (24/mo) | Volume (36/mo) |
|------|-----------|---|---|
| Review script AI-generated | 5 min | 2 hrs | 3 hrs |
| Watch video preview | 3 min | 1.2 hrs | 1.8 hrs |
| Approve & upload | 2 min | 0.8 hrs | 1.2 hrs |
| Adjust/fix issues (avg 10% videos) | 15 min/video | 0.4 hrs | 0.6 hrs |
| **Total per month** | 10 min/video | **~4.4 hrs** | **~6.6 hrs** |
| **per week** | | **~1 hr** | **~1.5 hrs** |

**Cost attribution (if founder bills self @ $50/hr):**
- 24 video/mo: 4.4 × $50 = $220/mo (~$9.17/video)
- 36 video/mo: 6.6 × $50 = $330/mo (~$9.17/video)

**Reality:** Solo founder unlikely to bill own time. **Burden: 1–1.5 hrs/week review + approval.**

---

## 7. Revenue Estimate & Breakeven

Assuming YouTube monetization (AdSense) + affiliate links in description.

### CPM Assumptions (Documentary/History content)
- **US/UK/CA/AU** (English): $2–5 CPM (advertiser-friendly, higher tier)
- **Spain/LatAm** (Spanish): $0.50–2 CPM (lower-tier markets)
- **Vietnam**: $0.20–0.80 CPM (developing market, low CPM)

### Typical View Volumes (Long-form, faceless, niche history)
- New channel: 500–2,000 views/month/video (ramp-up)
- Established (6–12 months): 5,000–20,000 views/month/video
- Mature (1+ years): 20,000–100,000 views/month/video

### Breakeven Analysis

**Conservative Scenario (1,000 views/video/month, all 3 channels mature):**
- English: 1,000 views × $3 CPM = $3/video = $24/month (8 videos)
- Spanish: 1,000 views × $1 CPM = $1/video = $8/month (8 videos)
- Vietnamese: 1,000 views × $0.50 CPM = $0.50/video = $4/month (8 videos)
- **Total revenue:** $36/month

**Actual breakeven:** 24 videos × $0.50/CPM * (24,000 views) = $288/month (breakeven $120/mo cost)
= ~**1,200–2,400 views/month/video** at blended $1.50 CPM

**Moderate Scenario (5,000 views/video/month, 3 kênh):**
- Blended: 5,000 views × $1.50 CPM × 24 videos = **$180/month** (profitable)

**High-Growth Scenario (20,000 views/video/month):**
- Blended: 20,000 views × $1.50 CPM × 24 videos = **$720/month** (excellent)

---

## 8. Cost Optimization Strategies

| Strategy | Savings | Trade-off |
|----------|---------|-----------|
| **Use Gemini 3.5 Flash instead of Claude** | $3–4/mo | Slightly lower quality scripts; faster |
| **Local Whisper (free) vs OpenAI API** | $1.50–2.25/mo | Requires GPU; setup overhead |
| **Skip captions** | $1.50–2.25/mo | Lose accessibility, lower engagement, YT demotion |
| **Reduce ElevenLabs tiers if low volume** | $70–90/mo (ramp-up) | Quality voice still solid on Creator tier; slower scaling |
| **Batch video generation (off-peak)** | $0–5/mo | Longer pipeline time; script-to-upload ~2–3 days vs overnight |
| **Free stock only (no Kling/video-gen)** | $37/mo (if using Kling) | Limited dynamic b-roll; relies on static stock; slower editing |
| **Single channel launch first** | $40/mo (skip Spanish/VN initially) | Longer ramp-up; sequential revenue (3–6 mo delay per channel) |

**Recommended:** Launch English only ($120/mo, 8 video/mo) → add Spanish in month 3 (no cost, same ElevenLabs quota) → add Vietnamese month 5 (add XTTS free). **Phased ramp = same setup cost but spread over time.**

---

## 9. Financial Highlights & Sensitivity

### Break-Even
- **Monthly:** 1,200–2,400 total views/month across all videos @ blended $1.50 CPM
- **Setup ROI:** $3,000 cost ÷ ~$20/month profit = **150 months (12.5 years)** if only $20/mo profit
  - **But:** If 5,000+ views/video/month → $180–300/month profit = **10–15 months ROI**

### Sensitivity (3-channel, steady-state 24–36 video/mo)

| View/Video/Mo | Blended CPM | Revenue/Mo | Profit/Mo | Margin |
|---|---|---|---|---|
| 500 | $1.50 | $36 | -$84 | Negative |
| 1,000 | $1.50 | $72 | -$48 | Negative |
| 2,000 | $1.50 | $144 | $23 | 16% |
| 5,000 | $1.50 | $360 | $240 | 67% |
| 10,000 | $1.50 | $720 | $600 | 83% |
| 20,000 | $1.50 | $1,440 | $1,320 | 92% |

**Key:** Profitable if **2,000+ views/video/month**. Excellent margin at **5,000+ views/video/month**.

---

## 10. Verified Pricing Sources (2026)

| Service | Link | Note |
|---------|------|------|
| **ElevenLabs Pro** | https://elevenlabs.io/pricing | $99/mo, 600k chars (V2) or 1M chars (V2.5 Flash) |
| **Claude API** | https://platform.claude.com/docs/en/about-claude/pricing | Haiku $1/$5 per 1M tokens (input/output) |
| **Gemini API** | https://ai.google.dev/gemini-api/docs/pricing | Gemini 3.5 Flash $1.50/$9.00 per 1M tokens |
| **OpenAI Whisper** | https://openai.com/api/pricing | $0.006/min (or $0.003 with GPT-4o Mini) |
| **Kling AI** | https://fluxnote.io/guides/ai-video-model-pricing-comparison-2026 | ~$0.07/sec generated video; Pro $37/mo |
| **Fly.io** | https://fly.io/pricing | Pay-as-you-go, típ $8–25/mo for small apps |
| **YouTube API** | https://cloud.google.com/youtube/docs/quota-overview | Free (quota-based, no per-call cost) |
| **SDXL Local** | https://medium.com/@velinxs/running-stable-diffusion-at-scale-without-going-broke-2dccf6ab7519 | RTX 3060 ($250 used) + electricity $15–30/mo |

---

## 11. Recommendations

1. **Start single-channel (English)** with Scenario 1 ($30–120/mo depending on Pro commitment). Validate product-market fit before multi-channel.

2. **Lock ElevenLabs Pro** ($99/mo) from day 1 if planning 3 channels within 6 months. Avoids cost creep; covers English + Spanish easily.

3. **Use Claude Haiku** for script gen (cheap, good quality for faceless video). Batch API (50% off) only if >100 scripts/month.

4. **Lean on free stock + local SDXL** for video gen early. **Kling Pro only if video quality becomes bottleneck** (month 6+, if 5k+ views/video).

5. **Self-host Whisper locally** once pipeline stable (avoid per-minute API cost; one-time setup).

6. **Target 2,000+ views/video by month 6–9** to hit breakeven on ad revenue. Requires SEO, keyword research, series structure. **Affiliate links** accelerate breakeven (10–20% boost to revenue).

7. **Monthly budget (steady-state):** $120–150 ≈ cheap moat. **Reinvest profit into growth** (Kling, paid thumbnails, etc.) or pocket as passive income.

---

## Unresolved Questions

1. **Revenue mix:** Assumed pure AdSense. What % affiliate vs sponsorship vs Patreon? (Affects breakeven timeline)
2. **Video quality threshold:** At what view volume does Kling ($37/mo premium) payoff vs free stock? (Likely 5k+ views/video)
3. **Scalability cap:** Does one person maintaining 3 kênh @ 3 video/week peak out? Or sustainable indefinitely? (Likely 3–4 videos/week max before burnout)
4. **Market saturation:** History/documentary faceless is crowded. Will 2,000 views/video be achievable in year 2? (Depends on niche differentiation, SEO, audience quality)
5. **GPU deprecation:** RTX 3060 ($250) depreciates; new NVIDIA gen could offer better ROI. Should model hardware refresh cycle? (Typically 3–5 years)

---

## Appendix: Cost Formula (Spreadsheet Ready)

```
Fixed_Monthly = 99 (ElevenLabs) + 5 (Claude) + 15 (Fly.io) + 0 (YouTube API) + 0 (XTTS)
Per_Video = 0.008 (Script) + 0.067 (Captions) + 0 (Stock+SDXL)
              = 0.075 per video

Monthly_Cost = Fixed_Monthly + (Video_Count × Per_Video)
             = 99 + 5 + 15 + (N × 0.075)

Revenue = (Views_per_Video × CPM / 1000) × Video_Count
Profit = Revenue - Monthly_Cost

Breakeven_Views = (Monthly_Cost × 1000) / (CPM × Video_Count)
```

**Example:** 24 video/mo, $1.50 blended CPM
- Cost: $119 + (24 × $0.075) = $120.80/mo
- Breakeven views: ($120.80 × 1000) / ($1.50 × 24) = 3,356 views/video/month
