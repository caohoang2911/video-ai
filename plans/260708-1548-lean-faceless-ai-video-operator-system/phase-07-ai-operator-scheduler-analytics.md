# Phase 07 — AI-Operator Scheduler + Analytics Loop

## Context Links
- Overview: [plan.md](plan.md) · Prev: [phase-06](phase-06-youtube-publisher.md)
- Research brief: "Autonomous Scheduler + YouTube Analytics Optimization Loop".

## Overview
- **Priority:** P1 (P0 chạy tay từng bước được; đây là lớp tự động hoá "AI-operator")
- **Status:** pending
- **Description:** APScheduler ghép chuỗi pipeline theo cadence ≤3/tuần qua state machine; cron keep-alive refresh token; vòng tối ưu analytics (YouTube Analytics API → xếp hạng topic/title/thumbnail thắng → feed topic selector). A/B test dùng native YouTube Test & Compare (manual Studio).

## Key Insights (từ brief)
- **APScheduler 3.11 + SQLAlchemyJobStore(SQLite)** = đủ cho 2-3 video/tuần (không cần Celery/RQ). `ThreadPoolExecutor(max_workers=3)`, `coalesce=True`, `max_instances=1` (tránh chạy trùng sau restart).
- **State machine driven:** mỗi tick, scheduler quét video theo state, đẩy sang bước kế: `draft→script→media→assemble→notify_review→(chờ user)→publish→analyze`. Idempotent + log lỗi mỗi bước.
- **Analytics latency 48-72h** → query dữ liệu ≥3 ngày trước (chạy thứ Hai cho video thứ Sáu). Batch 5 metrics/query = 1 unit (tiết kiệm 10k/ngày quota).
- **A/B test KHÔNG có API** (tính đến 2025-12): dùng YouTube Studio Test & Compare thủ công (3 title/thumb, 2 tuần, xếp theo watch time). Lưu metadata test vào DB, đọc kết quả sau 2 tuần.
- **Keep-alive token: cron tháng POST oauth token endpoint** (chỉ cách reset 6-tháng timer).
- **Single-writer:** scheduler + bot cùng SQLite → giữ transaction ngắn, WAL; hoặc chạy 2 process nhưng chỉ scheduler ghi state pipeline, bot ghi review state (phân vùng cột).
- **Metrics schema per-video (bảng `analytics`):** lưu rõ từng cột — `ctr` (impressions CTR, target 4-6%), `retention_25/50/75` (mốc % xem tới 25/50/75% video), `retention_30s` (% còn xem ở giây 30 — proxy hook), `watch_time_min` (estimatedMinutesWatched), `avg_view_pct`, `subs_gained` (subscribersGained/video), `rpm` (estimatedRevenue/1K views). Đủ để chẩn đoán hook vs pacing vs packaging riêng biệt.
- **Decision rules ngưỡng cứng (topic_optimizer):** `retention_30s <60%` → **hook fail**, KHÔNG lặp lại topic đó, đổi hook style vòng sau; `ctr <3%` → regenerate thumbnail (title/thumb packaging yếu, không phải nội dung); `avg_view_pct <30%` HOẶC retention drop mạnh ở phút 3-5 → **lỗi pacing**, skip topic đó 2 tuần; `rpm <$5/1K` → niche/topic bão hoà (ad-value thấp) → hạ boost score. Mỗi rule ghi rõ WHY để tránh sửa nhầm tầng (hook↔packaging↔pacing).
- **Rolling 3-video average:** quyết định KHÔNG dựa 1 video (nhiễu) — mỗi lần rank lấy trung bình trượt 3 video gần nhất cùng nhóm; log lại `decision_trail` (rule nào kích hoạt, số liệu, hành động) để feed recommendation minh bạch + audit được.
- **Feedback packaging từ review (phase 05):** đọc winning title/thumbnail variant + `reject_reason` codes (lý do user từ chối bản nháp) → tổng hợp thành constraint/prompt hint feed ngược `script_generator`/thumbnail-gen (phase 02) vòng sau (WHY: khép vòng học từ cả tín hiệu người duyệt lẫn khán giả).
- **Weekly approval report (rubber-stamp detection):** báo cáo tuần gửi Telegram — tỉ lệ approve/reject, thời gian trung bình từ notify→approve, cờ cảnh báo nếu user approve quá nhanh/100% (dấu hiệu "rubber-stamp" duyệt lấy lệ → chất lượng gate suy giảm).

## Requirements
Functional:
1. `pipeline_runner`: hàm mỗi bước (`step_script`, `step_media`, `step_assemble`, `step_notify`, `step_publish`, `step_analyze`) nhận `video_id`, tiến state, log.
2. `scheduler_setup`: APScheduler jobs — (a) `tick_pipeline` interval (vd mỗi 30' quét state đẩy tiếp), (b) `weekly_topic_seed` (đảm bảo backlog đủ), (c) `publish_cadence` (rải ≤3/tuần), (d) `monthly_token_keepalive`, (e) `weekly_analytics_pull`.
3. `analytics_client`: query Analytics API → ghi bảng `analytics` → `topic_optimizer` xếp hạng RPM/CTR/retention → gợi ý topic/title cho content-engine.
4. `token_keepalive`: POST refresh.
Non-functional: crash-safe (job store persist); `max_instances=1`; log mỗi transition; single video/process cho render (memory).

## Architecture — control loop
```
APScheduler (SQLite jobstore)
 ├ tick_pipeline (30m): for v in videos by state → advance one step (idempotent)
 │     draft→step_script→scripted→step_media→voiced→step_assemble→rendered
 │     →step_notify→pending_review─(user approve via phase05)→approved
 │     →publish_cadence picks ≤3/wk→step_publish→published
 ├ weekly_analytics_pull (Mon): analytics_client.query(safe_date=-3d) → analytics table
 │     → topic_optimizer.rank(rolling_avg=3) → apply decision rules (hook/packaging/pacing/rpm)
 │     → write recommended topics/titles + log decision_trail → content-engine
 │     → merge winning title/thumb variant + reject_reason (phase05) into prompt hints → phase02
 ├ weekly_approval_report (Mon): approve/reject ratio + notify→approve latency
 │     → rubber-stamp flag → Telegram
 ├ monthly_token_keepalive: POST oauth2 token (reset 6-mo timer)
 └ weekly_topic_seed: ensure backlog ≥ N via topic_backlog.suggest()
```

## Related Code Files
- Create: `src/ai_operator/scheduler/scheduler_setup.py` (APScheduler config + job registration), `src/ai_operator/scheduler/pipeline_runner.py` (step_* functions ghép engine phase 02-06), `src/ai_operator/scheduler/token_keepalive.py`, `src/ai_operator/analytics/analytics_client.py` (Analytics API query), `src/ai_operator/analytics/topic_optimizer.py` (rank + recommend), `src/ai_operator/analytics/ab_test_tracker.py` (lưu/đọc metadata Test & Compare thủ công), `src/ai_operator/analytics/approval_report.py` (weekly approve/reject + rubber-stamp detection → Telegram).
- Modify: `cli.py` (`run-operator` chạy scheduler foreground), `db/state_machine.py` (dùng transitions), `content/topic_backlog.py` (nhận recommendation).
- Delete: none.

## Implementation Steps
1. `pipeline_runner.py`: mỗi `step_x(video_id)` gọi module engine tương ứng (import từ content/media/assembler/publisher), bọc try/except → log + set state hoặc `failed`. Idempotent (kiểm state hiện tại trước khi chạy).
2. `scheduler_setup.py`: `BackgroundScheduler(jobstores={'default': SQLAlchemyJobStore(url=settings.DB_URL)}, executors={'default': ThreadPoolExecutor(3)}, job_defaults={'coalesce':True,'max_instances':1})`. `add_job(tick_pipeline, 'interval', minutes=30)`, `add_job(weekly_analytics_pull,'cron',day_of_week='mon',hour=9)`, `add_job(token_keepalive,'cron',day=1)`, `add_job(publish_cadence,'cron', ...)`. Pass **video_id (không object)** vào job args (pickle-safe).
3. `token_keepalive.py`: POST `https://oauth2.googleapis.com/token` body `grant_type=refresh_token,...` → verify 200. Log.
4. `analytics_client.py`: build service (yt-analytics.readonly); `reports().query(ids=f'channel=={CHANNEL_ID}', startDate=today-90, endDate=today-3, metrics='views,estimatedMinutesWatched,averageViewPercentage,estimatedRevenue,subscribersGained', dimensions='video')`; query riêng CTR (`card...`/`impressions,cardClickRate` hoặc `annotationImpressions`; nếu Analytics API không trả impressionsCTR → đọc thủ công/estimated). Query retention curve dùng `elapsedVideoTimeRatio` dimension để lấy mốc 25/50/75% + giây 30. Batch metrics 1 query. Upsert **schema cụ thể**: `ctr, retention_25, retention_50, retention_75, retention_30s, watch_time_min, avg_view_pct, subs_gained, rpm`.
5. `topic_optimizer.py`: `rank()` đọc analytics theo **rolling 3-video average** cùng nhóm topic → áp decision rules ngưỡng cứng: `retention_30s<60%`→hook fail (mark topic no-repeat, đổi hook style); `ctr<3%`→cờ regenerate thumbnail; `avg_view_pct<30%` hoặc drop phút 3-5→pacing fail (skip topic 2 tuần); `rpm<$5/1K`→hạ boost (bão hoà). Ghi `decision_trail` (rule, số liệu, action) mỗi lần. Trích topic category + title pattern thắng → ghi `topics` (boost score) / gợi ý title cho `script_generator`. Comment giải thích WHY từng ngưỡng (chẩn đoán đúng tầng), không tham chiếu phase.
6. `ab_test_tracker.py` (**module A/B DUY NHẤT** — phase-06 `ab_variants.py` chỉ ghi variants vào `uploads`): đọc variants từ `uploads`; sau 2 tuần đọc analytics/manual để chọn winner (không API → user nhập hoặc suy từ analytics). Xuất winning title/thumb variant + đọc `reject_reason` codes từ review (phase 05) → tổng hợp thành prompt hints feed ngược content/thumbnail-gen (phase 02).
6b. `approval_report.py` + job `weekly_approval_report` (cron Mon): tính approve/reject ratio, notify→approve latency trung bình; nếu approve≈100% hoặc latency quá thấp → set rubber-stamp flag; gửi Telegram (WHY: gate chất lượng suy giảm nếu duyệt lấy lệ).
7. `publish_cadence`: chọn video `approved` cũ nhất, set `publishAt` rải đều (vd Thứ 3/5/7), gọi `step_publish`.
8. `cli.py`: `operator run-operator` (scheduler + bot cùng process hoặc 2 process — quyết định deploy phase 08).
9. Test: mô phỏng 1 video chạy tự động qua các state (mock user approve); verify analytics query trả số; keepalive 200.

## Todo List
- [ ] pipeline_runner step_* idempotent + failed handling
- [ ] scheduler_setup (jobstore SQLite, coalesce, max_instances=1, video_id args)
- [ ] token_keepalive monthly cron
- [ ] analytics_client (batch query, safe -3d; schema: ctr/retention_25-50-75/retention_30s/watch_time/subs/rpm)
- [ ] topic_optimizer rank (rolling 3-video avg) + decision rules ngưỡng cứng + decision_trail log
- [ ] ab_test_tracker (manual Test&Compare metadata) + feed winning variant + reject_reason → prompt hints phase02
- [ ] approval_report + weekly rubber-stamp detection → Telegram
- [ ] publish_cadence rải ≤3/tuần
- [ ] cli run-operator; test loop end-to-end (mock approve)

## Success Criteria
- Scheduler tự đẩy 1 video từ `draft` → `pending_review` không cần lệnh tay; sau approve tự `published` theo cadence.
- `analytics` bảng có dữ liệu sau chạy weekly pull (video ≥3 ngày tuổi).
- `topic_optimizer` sinh ≥1 recommended topic/title từ dữ liệu thật.
- `token_keepalive` trả 200; job store persist qua restart (job không mất).
- KHÔNG chạy trùng (max_instances=1), KHÔNG upload quá 3/tuần.

## Risk Assessment
| Risk | L | I | Mitigation |
|---|---|---|---|
| Analytics 48-72h latency → tối ưu sai | Med | Med | Query ≥3 ngày trước; chạy weekly Mon. |
| Job pickling lỗi (object args) | Med | Med | Chỉ truyền video_id; reconstruct trong job. |
| Callback không idempotent → double publish | Med | High | Check state trước; idempotent uploads (phase 06). |
| SQLite write-lock scheduler↔bot | Med | Med | WAL; transaction ngắn; cân nhắc Postgres P1. |
| Data ít → optimizer nhiễu | High | Low | P0 chỉ 10-20 video → optimizer chỉ gợi ý, human quyết; full loop P1. Rolling 3-video avg giảm nhiễu 1 video. |
| Sửa nhầm tầng (đổi title khi lỗi thực là hook/pacing) | Med | Med | Decision rules tách ngưỡng riêng: retention_30s→hook, ctr→packaging, avg_view_pct/drop m3-5→pacing, rpm→bão hoà. |
| CTR/retention-curve không có sẵn từ Analytics API | Med | Med | Query `elapsedVideoTimeRatio` cho retention; CTR fallback thủ công/estimated nếu API không trả impressionsCTR. |
| Rubber-stamp: user duyệt lấy lệ → gate vô nghĩa | Med | Med | Weekly approval report cờ approve≈100%/latency thấp → Telegram cảnh báo. |

## Security Considerations
- Analytics dùng user-scope OAuth (không service account). Token qua env.
- Keep-alive log không in token. Cron chạy đúng project tránh nhầm channel.

## Next Steps
→ Phase 08 deploy always-on (scheduler + bot) + observability. Phase 09 dùng analytics áp kill-criteria.

## Unresolved Questions
- Scheduler + bot chung 1 process (asyncio + APScheduler) hay 2 process? — đề xuất P0/P1: 2 process (bot polling riêng, scheduler riêng) để tránh 409 và cô lập crash; phân vùng cột ghi DB.
- Full auto-optimize (đổi title/thumb tự động) hay chỉ gợi ý? — P0/P1 chỉ gợi ý + human; auto là P2.
