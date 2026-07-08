---
name: scheduler-analytics-research
description: Technical research on autonomous scheduler + YouTube Analytics feedback loop for AI video pipeline
type: research
date: 2026-07-08
---

# NGHIÊN CỨU: Scheduler + Analytics Optimization Loop
## AI Video Automation Pipeline — Lịch Tự Động & Vòng Tối Ưu hóa YouTube

**Ngày**: 2026-07-08 | **Bối cảnh**: Hệ thống video YouTube faceless (8-15 phút, Maritime Disasters), Python 3.11, KISS/YAGNI/DRY

---

## TÓM TẮT THỰC TÍNH

**Kết luận**: APScheduler + SQLite + python-statemachine + YouTube Analytics API (v2).  
- **APScheduler**: Best-fit cho greenfield; SQLite-backed persistence; 2-3 video/tuần cadence dễ quản lý.
- **State machine**: Enforce video pipeline constraints (topic→scripted→rendered→pending_review→approved→published).
- **Analytics loop**: Latency 48-72 giờ → query analysis mỗi 3 ngày, feedback topic/title/thumbnail.
- **A/B testing**: Native YouTube "Test & Compare" (thumbnail + title, 2 tuần); không cần API custom A/B.
- **Gotcha #1**: Analytics data 2-3 ngày trễ → scheduler không thể optimize hôm nay cho video hôm qua.
- **Gotcha #2**: 10,000 unit/day quota → batch query, dùng YouTube Reporting API (bulk CSV async).

---

## 1. SCHEDULER: APScheduler vs Alternatives

### 1.1 APScheduler (RECOMMENDED)

**Lựa chọn**: APScheduler 3.11+ cho greenfield.

| Tiêu chí | APScheduler | Celery Beat | RQ | Rocketry |
|----------|-----------|-----------|-----|---------|
| **Setup** | Đơn giản (1 file) | Phức tạp (broker) | Trung bình | Tương đối đơn giản |
| **Persistence** | ✅ SQLite/Postgres | ✅ Redis | ✅ Redis | ✅ SQLite |
| **Greenfield fit** | ⭐⭐⭐ | ⭐ | ⭐⭐ | ⭐⭐ |
| **Job state durability** | ✅ High | ✅ High | ✅ High | ✅ Medium |
| **Python 3.11** | ✅ Native | ✅ Native | ✅ Native | ✅ Native |
| **Approval gate** | Manual poll | Manual poll | Manual poll | Manual poll |

**Rationale**:
- Không cần external broker (Redis/RabbitMQ).
- SQLite job store → video metadata sync'd với cơ sở dữ liệu.
- Trigger types (cron, interval, date) cover 2-3 video/tuần.
- Thích hợp cho single-server VPS.

### 1.2 APScheduler Architecture Cho Video Pipeline

```python
# scheduler.py — APScheduler + SQLite job store

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
import logging

# Job store config
jobstores = {
    'default': SQLAlchemyJobStore(
        url='sqlite:///scheduler_jobs.db',  # Shared với main DB
        engine_options={'pool_size': 10, 'pool_recycle': 3600}
    )
}

# Executors: thread pool (blocking I/O), process pool (CPU-bound)
executors = {
    'default': ThreadPoolExecutor(max_workers=3),
    'video_render': ThreadPoolExecutor(max_workers=2),  # Isolated for FFmpeg
}

# Job defaults: retry + timeout
job_defaults = {
    'coalesce': True,
    'max_instances': 1,
    'misfire_grace_time': 600,  # 10 min grace if missed
}

# Create scheduler
scheduler = BackgroundScheduler(
    jobstores=jobstores,
    executors=executors,
    job_defaults=job_defaults,
    timezone='UTC'
)

# Start scheduler
scheduler.start()
logging.info("Scheduler started with SQLite persistence at scheduler_jobs.db")
```

**Key points**:
- `coalesce=True`: Nếu scheduler tắt 2h, khi restart không chạy missed jobs 2h, chỉ chạy 1 lần.
- `max_instances=1`: Prevent concurrent runs (video topic selection không chạy 2 lần).
- `misfire_grace_time=600`: Job start trong 10 min của scheduled time vẫn chạy.
- Thread pool cho I/O (API calls, file download); job store persist across restart.

### 1.3 Cadence: 2-3 Video/Tuần

```python
# schedule.py — Recurring jobs

from scheduler import scheduler
from pipeline.topic_selector import select_topic_and_brief
from pipeline.script_generator import generate_script
from pipeline.voiceover_engine import generate_voiceover

# Job 1: Topic selection + Script → Wed 2am UTC (auto → manager approval)
scheduler.add_job(
    id='weekly_topic_select_2am',
    func=select_topic_and_brief,
    trigger='cron',
    day_of_week='wed',
    hour=2,
    minute=0,
    timezone='UTC',
    args=[db, telegram_bot],  # db, notification context
    kwargs={'topic_pool_size': 5},  # Generate 5 topic options
)

# Job 2: Scripting → Thurs 4pm UTC (pending user approval)
scheduler.add_job(
    id='weekly_script_render_thu',
    func=generate_script,
    trigger='cron',
    day_of_week='thu',
    hour=16,
    minute=0,
    timezone='UTC',
    args=[db],
    kwargs={'auto_retry': 3},
)

# Job 3: Voiceover + Video render → Sat 10am UTC (pending review)
scheduler.add_job(
    id='weekly_render_sat',
    func=generate_voiceover,
    trigger='cron',
    day_of_week='sat',
    hour=10,
    minute=0,
    timezone='UTC',
    args=[db],
    kwargs={'voice_model': 'elevenlabs_starter', 'quality': 'high'},
)

# Job 4: Analytics check + Feedback → Mon 6am UTC (every 3 days, delayed query)
scheduler.add_job(
    id='analytics_feedback_loop',
    func=run_analytics_feedback_loop,
    trigger='cron',
    day_of_week='mon',
    hour=6,
    minute=0,
    timezone='UTC',
    args=[db, youtube_api_client],
    kwargs={'lookback_days': 7},  # Analyze past 7 days (safely past 72h latency)
)

logging.info("Weekly cadence scheduled: topic→script→render→publish→optimize")
```

**Rationale cadence**:
- Wed 2am: Pick topic (auto-generate 5 options, user approve via Telegram).
- Thu 4pm: Script generate (user review in parallel, auto-retry if LLM fail).
- Sat 10am: Video render (voiceover + FFmpeg on background, pending review).
- Mon 6am: Analytics (query only 3 ngày trước, vượt qua 72h latency).

---

## 2. STATE MACHINE: Video Pipeline FSM

### 2.1 States & Transitions

**States** (7-state model):
1. **`draft`** — Topic + brief only (auto from topic selector).
2. **`scripted`** — Script generated, pending user review.
3. **`voiceover_pending`** — Audio rendering in progress (async job).
4. **`rendered`** — Full video complete, pending manager approval.
5. **`approved`** — Approved for publishing.
6. **`published`** — Live on YouTube.
7. **`archived`** — End-of-life (analytics only, no publish).

**Transitions**:
```
draft
  ↓ [script_generated]
scripted
  ↓ [user_approves_script]
voiceover_pending
  ↓ [voiceover_complete]
rendered
  ↓ [manager_approves]
approved
  ↓ [publish_to_youtube]
published
  ↓ [archive_after_30_days] ← Automation
archived
```

### 2.2 python-statemachine Implementation

```python
# models/video_fsm.py — State machine

from statemachine import State, StateMachine
from statemachine.contrib.sqlite_persistence import SQLitePersistence
from datetime import datetime

class VideoStateMachine(StateMachine):
    """Video lifecycle FSM with SQLite persistence."""
    
    # States
    draft = State("Draft", initial=True)
    scripted = State("Scripted")
    voiceover_pending = State("VoiceoverPending")
    rendered = State("Rendered")
    approved = State("Approved")
    published = State("Published")
    archived = State("Archived")
    
    # Transitions (events)
    script_generated = (
        draft.to(scripted, after="on_scripted")
    )
    user_approves_script = (
        scripted.to(voiceover_pending, after="on_voiceover_start")
    )
    voiceover_complete = (
        voiceover_pending.to(rendered, after="on_voiceover_done")
    )
    manager_approves = (
        rendered.to(approved, after="notify_approval")
    )
    publish_to_youtube = (
        approved.to(published, after="on_published")
    )
    archive_after_ttl = (
        published.to(archived, after="on_archived")
    )
    
    # Callbacks
    def on_scripted(self):
        """Transition: draft → scripted."""
        self.video.script_generated_at = datetime.utcnow()
        self.video.notify_status("Script ready for review")
        
    def on_voiceover_start(self):
        """Transition: scripted → voiceover_pending."""
        self.video.voiceover_start_at = datetime.utcnow()
        # Trigger async ElevenLabs API call
        submit_voiceover_job(self.video.id)
        
    def on_voiceover_done(self):
        """Transition: voiceover_pending → rendered."""
        self.video.voiceover_complete_at = datetime.utcnow()
        self.video.notify_status("Video render complete, awaiting manager review")
        
    def notify_approval(self):
        """Transition: rendered → approved."""
        self.video.approved_at = datetime.utcnow()
        self.video.approved_by = "manager_telegram_id"
        
    def on_published(self):
        """Transition: approved → published."""
        self.video.published_at = datetime.utcnow()
        self.video.youtube_video_id = get_youtube_id()
        self.video.notify_status(f"✅ Published: {self.video.youtube_url}")
        
    def on_archived(self):
        """Transition: published → archived (30 days TTL)."""
        self.video.archived_at = datetime.utcnow()

# Use persistence
class VideoModel:
    def __init__(self, db_session, video_row):
        self.id = video_row.id
        self.topic = video_row.topic
        self.script = video_row.script
        self.video_file = video_row.video_file
        self.youtube_video_id = video_row.youtube_video_id
        
        # Attach FSM with SQLite persistence
        self.fsm = VideoStateMachine(model=self)
        # Load state from SQLite (if restart)
        persister = SQLitePersistence(db_url='sqlite:///video_pipeline.db')
        self.fsm = persister.restore(video_row.id) or self.fsm

# Usage
video = get_video_by_id(db, video_id=42)
video.fsm.script_generated()  # Transition draft → scripted
print(video.fsm.current_state)  # Output: "Scripted"
```

**Gotcha**: `SQLitePersistence` persists FSM state across restarts. Nếu process crash sau `voiceover_complete()` nhưng trước `manager_approves()`, FSM sẽ resume tại `rendered` state.

---

## 3. YOUTUBE ANALYTICS API: Metrics, Latency & Optimization Loop

### 3.1 Metrics Available

**Core metrics** (query from YouTube Analytics API):
- `views`: Total impressions (count).
- `estimatedMinutesWatched`: Total watch time (minutes).
- `averageViewDuration`: Avg watched per view (seconds).
- `estimatedAdRevenue`: Gross ad earnings (USD).
- `estimatedCpm`: Revenue per 1000 impressions.
- `estimatedRpm`: Revenue per 1000 views (RPM = net after YouTube cut).
- `ctr`: Click-through rate (clicks / impressions, %).
- `subscribersGained`: New subscribers.
- `likes`, `comments`, `shares`: Engagement.

**Dimensions** (slice by):
- `video` (videoId).
- `day` (date).
- `country` (geolocation).
- `deviceType` (desktop, mobile, tablet).
- `trafficSource` (suggested videos, search, direct, etc.).

### 3.2 API Latency & Rate Limits

| Constraint | Value | Implication |
|-----------|-------|-------------|
| **Data latency** | 48-72 hours | Query today for data from 3 days ago |
| **Daily quota** | 10,000 units/day | ~20-50 video queries per day |
| **Query cost** | 1 unit per metric | Batch queries to save quota |
| **OAuth scope** | `yt-analytics.readonly` | Read-only analytics |
| **OAuth flow** | User (no service account) | Requires user login annually |

**CRITICAL GOTCHA**: YouTube's default 10,000 unit quota is per **project** (Google Cloud Project), not per channel. If user has 5 channels, queries against all 5 consume same quota pool.

### 3.3 Optimization Loop: Query Pattern

```python
# analytics/optimizer.py — Feedback loop every 3 days

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import sqlite3

class YouTubeAnalyticsOptimizer:
    """Query YouTube Analytics, extract wins, recommend next topics."""
    
    def __init__(self, db_path, youtube_analytics_service):
        self.db_path = db_path
        self.yt_analytics = youtube_analytics_service
        
    def run_feedback_loop(self, channel_id, lookback_days=7):
        """
        Analyze published videos from past 7 days.
        Extract: high CTR, high RPM topics → recommend for next content.
        """
        
        # Step 1: Query Analytics (safe: 3+ days old data)
        end_date = (datetime.utcnow() - timedelta(days=3)).strftime('%Y-%m-%d')
        start_date = (datetime.utcnow() - timedelta(days=3 + lookback_days)).strftime('%Y-%m-%d')
        
        response = self.yt_analytics.reports().query(
            ids=f'channel=={channel_id}',
            start_date=start_date,
            end_date=end_date,
            metrics='views,estimatedAdRevenue,ctr,estimatedMinutesWatched,averageViewDuration',
            dimensions='video,day',
            max_results=100,
            include_historical_data=True,  # Include Shorts
        ).execute()
        
        print(f"[Analytics] Fetched {len(response.get('rows', []))} rows")
        
        # Step 2: Aggregate by video
        video_stats = {}
        for row in response.get('rows', []):
            video_id, day = row[0], row[1]
            views, revenue, ctr, watch_time, avg_duration = row[2:7]
            
            if video_id not in video_stats:
                video_stats[video_id] = {
                    'views': 0, 'revenue': 0, 'ctr': 0, 'watch_time': 0,
                    'avg_duration': 0, 'days': 0,
                }
            video_stats[video_id]['views'] += int(views)
            video_stats[video_id]['revenue'] += float(revenue)
            video_stats[video_id]['watch_time'] += int(watch_time)
            video_stats[video_id]['days'] += 1
        
        # Step 3: Calculate normalized KPIs
        winners = []
        for vid, stats in video_stats.items():
            rpm = (stats['revenue'] / stats['views'] * 1000) if stats['views'] > 0 else 0
            avg_watch_pct = (stats['watch_time'] / (stats['views'] * video_length_sec / 60)) if stats['views'] > 0 else 0
            
            winners.append({
                'video_id': vid,
                'views': stats['views'],
                'rpm': rpm,
                'ctr': stats.get('ctr', 0),
                'retention': avg_watch_pct,
            })
        
        # Step 4: Rank by RPM (revenue), then CTR (discovery)
        winners_sorted = sorted(winners, key=lambda x: (x['rpm'], x['ctr']), reverse=True)
        
        top_5 = winners_sorted[:5]
        print(f"[Analytics] Top 5 performing videos:\n{top_5}")
        
        # Step 5: Extract topic metadata, store feedback
        for i, winner in enumerate(top_5, 1):
            video_record = get_video_by_youtube_id(self.db_path, winner['video_id'])
            if video_record:
                store_analytics_feedback(
                    db_path=self.db_path,
                    video_id=video_record['id'],
                    rank=i,
                    rpm=winner['rpm'],
                    ctr=winner['ctr'],
                    retention=winner['retention'],
                    topic_tag=video_record['topic'],  # Extract topic category
                )
        
        # Step 6: Recommend next topics (top 2 topic_tags)
        recommendations = recommend_topics_by_performance(
            self.db_path, top_n=2
        )
        
        print(f"[Recommendations] Next topics: {recommendations}")
        return recommendations

def recommend_topics_by_performance(db_path, top_n=2):
    """Aggregate topic performance, return top N topics for next batch."""
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Query: topic → avg RPM, avg CTR from feedback
    cur.execute("""
        SELECT v.topic, 
               AVG(af.rpm) as avg_rpm,
               AVG(af.ctr) as avg_ctr,
               COUNT(af.id) as count
        FROM analytics_feedback af
        JOIN videos v ON af.video_id = v.id
        WHERE af.created_at > datetime('now', '-30 days')  -- Last 30 days
        GROUP BY v.topic
        ORDER BY avg_rpm DESC, avg_ctr DESC
        LIMIT ?
    """, (top_n,))
    
    topics = [{'topic': r[0], 'avg_rpm': r[1], 'avg_ctr': r[2]} for r in cur.fetchall()]
    conn.close()
    return topics
```

**Query batching to save quota**:
```python
# Batch 5 metrics + 2 dimensions = 1 query (10 units)
# Instead of 5 separate queries (5 units each)

response = yt_analytics.reports().query(
    ids=f'channel=={channel_id}',
    start_date='2026-07-01',
    end_date='2026-07-07',
    metrics='views,estimatedAdRevenue,ctr,estimatedMinutesWatched,likes',  # 5 metrics
    dimensions='video,day',  # 2 dimensions
    max_results=100,
).execute()

# Cost: 1 query × 10 units = 10 units (vs 5 separate queries × 10 units = 50 units)
```

### 3.4 A/B Testing Strategy

**Native YouTube A/B Testing** (Test & Compare, Dec 2025+):
- Creators can test **up to 3 titles, thumbnails, or combinations** simultaneously.
- Platform shows variants equally for **up to 2 weeks**.
- YouTube auto-analyzes winner by **watch time per impression** (not CTR).
- Result: **Winner, Performed the same, or Inconclusive**.

**Limitations**:
- Desktop only (YouTube Studio).
- No Shorts, Premiere, Made for Kids, private.
- Data latency: 2+ weeks to results.

**Integration approach**:
1. Video render complete → Store 2 alt-thumbnails + 1 alt-title in SQLite.
2. Manager approves → Upload main video + variants to YouTube.
3. Enable "Test & Compare" via YouTube Studio (manual or API if available).
4. After 2 weeks → Query Analytics for test results → feedback to next batch.

**Code pattern**:
```python
# models/video_ab_test.py

class VideoABTest:
    """A/B test metadata for YouTube Test & Compare."""
    
    def __init__(self, video_id):
        self.video_id = video_id
        self.title_main = "..."
        self.title_alt = "..."  # Alternative title
        self.thumbnail_main = "..."  # File path
        self.thumbnail_alt_1 = "..."
        self.thumbnail_alt_2 = "..."
        self.test_start_date = None
        self.test_end_date = None
        self.winner = None  # "title", "thumbnail", "control", or "inconclusive"
    
    def upload_variants_to_youtube(self, youtube_api, video_resource_id):
        """Upload main + alt thumbnails via YouTube API."""
        
        # Upload thumbnail (main)
        youtube_api.thumbnails().set(
            videoId=video_resource_id,
            media_body=self.thumbnail_main,
        ).execute()
        
        # Note: YouTube API doesn't expose "upload alternative thumbnails" for A/B test.
        # Alternatives must be added via YouTube Studio UI → "Test & Compare" button.
        # Automation limitation: A/B testing setup is manual via UI.
        
    def record_test_result(self, winner_metric, db_session):
        """After 2 weeks, query analytics, store winner."""
        
        # Query YouTube Analytics for test video
        # Compare watch_time of each variant
        # Store winner back to DB
        
        self.winner = winner_metric
        db_session.commit()
```

**GOTCHA**: YouTube API **does NOT expose A/B test setup or results programmatically** (as of Dec 2025). Must use YouTube Studio UI manually or build custom tracking (store impression counts, extrapolate winner).

---

## 4. ANALYTICS FEEDBACK LOOP: Complete Example

### 4.1 End-to-End Optimization Cycle

```
Publish Video (Mon)
    ↓
Wait 72h (query safe Thurs)
    ↓
Query Analytics: views, RPM, CTR per video
    ↓
Rank videos by RPM (revenue signal) → Top topic
    ↓
Extract topic category from winner
    ↓
Store recommendation in DB
    ↓
Suggest next topic for Wed topic selector
    ↓
(Repeat weekly)
```

### 4.2 Database Schema

```sql
-- SQLite schema for pipeline + analytics

CREATE TABLE videos (
    id INTEGER PRIMARY KEY,
    topic TEXT,
    title TEXT,
    script TEXT,
    video_file TEXT,
    youtube_video_id TEXT,
    youtube_url TEXT,
    fsm_state TEXT DEFAULT 'draft',
    published_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE analytics_feedback (
    id INTEGER PRIMARY KEY,
    video_id INTEGER NOT NULL,
    rank INTEGER,  -- 1-5 ranking in top performers
    rpm REAL,
    ctr REAL,
    retention_pct REAL,
    topic_tag TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(video_id) REFERENCES videos(id)
);

CREATE TABLE topic_recommendations (
    id INTEGER PRIMARY KEY,
    topic TEXT,
    avg_rpm REAL,
    avg_ctr REAL,
    count_videos INTEGER,
    recommended_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE scheduler_jobs (
    id TEXT PRIMARY KEY,
    func_name TEXT,
    trigger_type TEXT,
    next_run_time TIMESTAMP,
    job_state BLOB  -- Serialized job data
);
```

### 4.3 Orchestration: Scheduler + Analytics + State Machine

```python
# main.py — Integration

from scheduler import scheduler
from analytics.optimizer import YouTubeAnalyticsOptimizer
from telegram_bot import TelegramApprovalBot
from models.video_fsm import VideoModel

def init_pipeline():
    """Initialize scheduler + analytics + FSM."""
    
    # Setup
    db = init_sqlite_db('video_pipeline.db')
    yt_analytics = build_youtube_analytics_client(user_creds)
    telegram_bot = TelegramApprovalBot(token, channel_id)
    optimizer = YouTubeAnalyticsOptimizer(db, yt_analytics)
    
    # Job 1: Topic selector (Wed 2am)
    async def topic_job():
        recommendations = optimizer.run_feedback_loop(
            channel_id=CHANNEL_ID, lookback_days=7
        )
        topics = generate_topics(db, recommendations, n=5)
        await telegram_bot.send_approval_button(
            "Pick topic:", topics
        )
    
    scheduler.add_job(topic_job, trigger='cron', day_of_week='wed', hour=2)
    
    # Job 2: Script generator (Thu 4pm)
    async def script_job():
        active_video = get_active_video_by_state(db, 'draft')
        script = generate_script_llm(active_video)
        active_video.fsm.script_generated()
        db.commit()
        await telegram_bot.send_for_review("Script ready", script)
    
    scheduler.add_job(script_job, trigger='cron', day_of_week='thu', hour=16)
    
    # Job 3: Render (Sat 10am)
    async def render_job():
        active_video = get_active_video_by_state(db, 'voiceover_pending')
        voiceover = generate_voiceover_elevenlabs(active_video.script)
        video = render_video_ffmpeg(
            active_video.script, voiceover, assets_pexels
        )
        active_video.fsm.voiceover_complete()
        db.commit()
        await telegram_bot.send_for_manager_approval("Video ready", video)
    
    scheduler.add_job(render_job, trigger='cron', day_of_week='sat', hour=10)
    
    # Job 4: Analytics (Mon 6am)
    async def analytics_job():
        recommendations = optimizer.run_feedback_loop(
            channel_id=CHANNEL_ID, lookback_days=7
        )
        # Feedback used next Wed topic selector
        logging.info(f"Analytics loop: {recommendations}")
    
    scheduler.add_job(analytics_job, trigger='cron', day_of_week='mon', hour=6)
    
    scheduler.start()
    logging.info("Pipeline initialized: scheduler + analytics + FSM + telegram")

if __name__ == '__main__':
    init_pipeline()
    # Run forever; scheduler handles job execution in background
    import time
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown()
```

---

## 5. GOTCHAS & TRADE-OFFS

### 5.1 Analytics API Gotchas

| Gotcha | Impact | Mitigation |
|--------|--------|-----------|
| **48-72h data latency** | Cannot optimize today for yesterday's video | Query safely 3+ days ago; Monday for Friday publish |
| **10k units/day quota** | ~20 videos/day max queries | Batch metrics (5 metrics = 1 query); use YouTube Reporting API bulk CSV |
| **No service account** | User OAuth required annually | Build refresh token logic; warn user before expiry |
| **A/B test no API** | Cannot automate A/B setup | Manual YouTube Studio; custom impression tracking alternative |
| **Impressions vs views** | CTR = clicks/impressions, not clicks/views | YouTube only exposes impressions via Analytics; CTR in tooltip, not metric |

### 5.2 Scheduler Gotchas

| Gotcha | Impact | Mitigation |
|--------|--------|-----------|
| **Job coalesce** | If scheduler down 2h, missed jobs run 1x not 2x | `coalesce=True` (default); acceptable for weekly |
| **SQLite locking** | Concurrent writes block | Use SQLAlchemy connection pooling; keep transactions short |
| **Job serialization** | Job args must be pickle-able | Pass DB ID, not full objects; reconstruct in job function |
| **Timezone UTC vs local** | Scheduler runs UTC, user expects local time | Schedule jobs in UTC; convert to user tz for display in Telegram |

### 5.3 State Machine Gotchas

| Gotcha | Impact | Mitigation |
|--------|--------|-----------|
| **SQLitePersistence async** | Blocking DB call in transition | Use thread executor; keep transitions short |
| **No rollback on callback fail** | If `on_scripted()` fails halfway, state already changed | Callbacks should be idempotent; log errors; retry strategy |
| **Lost in-flight state** | If process crash in `voiceover_pending`, may retry job twice | Store job ID in FSM; check idempotence of job (no duplicate voiceovers) |

---

## 6. IMPLEMENTATION CHECKLIST

- [ ] **APScheduler**: Install `apscheduler==3.11.x`, configure SQLAlchemy job store.
- [ ] **State machine**: Install `python-statemachine==3.2.x`, define 7-state VideoFSM.
- [ ] **YouTube Analytics**: Setup OAuth 2.0 user credentials, scope `yt-analytics.readonly`.
- [ ] **Telegram approval**: Implement approval buttons (topic, script, manager review).
- [ ] **Analytics loop**: Monthly feedback (topic/RPM/CTR recommendations stored in DB).
- [ ] **A/B testing**: Manual setup in YouTube Studio; track test results in DB post-2-week.
- [ ] **Error handling**: Retry logic for transient failures (LLM timeout, API rate limit); dead-letter queue for permanent failures.
- [ ] **Logging**: CloudWatch / Sentry for production monitoring.
- [ ] **Database migration**: `alembic` for schema versioning.

---

## 7. CODE PATTERNS (Concrete Libs)

| Component | Library | Version | Pattern |
|-----------|---------|---------|---------|
| **Scheduler** | `apscheduler` | 3.11+ | `BackgroundScheduler` + `SQLAlchemyJobStore` |
| **State machine** | `python-statemachine` | 3.2+ | Declarative states + transitions + SQLitePersistence |
| **YouTube Analytics** | `google-api-python-client` | 1.12+ | `build('youtubeAnalytics', 'v2')` |
| **YouTube Data** | `google-api-python-client` | 1.12+ | `build('youtube', 'v3')` |
| **Telegram** | `python-telegram-bot` | 20.x+ | `Application` + handlers |
| **SQLite** | `sqlite3` (builtin) | Python 3.11 | Direct or via `SQLAlchemy` ORM |
| **OAuth** | `google-auth` | 2.x+ | `flow.run_local_server()` for user auth |

---

## 8. UNRESOLVED QUESTIONS

1. **YouTube A/B test results API**: As of Dec 2025, YouTube doesn't expose A/B test results via API. Should we build custom impression tracking via GA4 (if enabled)? Or accept manual check via YouTube Studio every 2 weeks?
   
2. **Topic recommendation cold start**: First 2-3 weeks, no analytics data. Should seed topic recommendations from external trending API (e.g., TrendingTopics, News API) or manual curator input?
   
3. **Quota spillover**: If one user account is monetized + channel has high views, quota consumed fast. Multi-channel strategy or quota request to Google required? (Audit needed.)
   
4. **Approval timeout**: If user doesn't approve script by Fri, does scheduler auto-retry or pause? Define SLA?

---

## SOURCES

- [APScheduler — PyPI](https://pypi.org/project/APScheduler/)
- [APScheduler User Guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html)
- [APScheduler SQLAlchemy Job Store](https://apscheduler.readthedocs.io/en/3.x/modules/jobstores/sqlalchemy.html)
- [YouTube Analytics and Reporting APIs — Google Developers](https://developers.google.com/youtube/analytics)
- [YouTube Analytics Metrics Reference](https://developers.google.com/youtube/analytics/metrics)
- [YouTube Analytics API Rate Limits](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits)
- [A/B Testing Titles and Thumbnails — YouTube Help](https://support.google.com/youtube/answer/16391400?hl=en-GB)
- [python-statemachine — PyPI](https://pypi.org/project/python-statemachine/)
- [python-statemachine Documentation](https://python-statemachine.readthedocs.io/en/latest/)
- [YouTube A/B Testing Expands to Titles](https://www.searchenginejournal.com/youtube-title-a-b-testing-rolls-out-globally-to-creators/562571/)
- [YouTube Algorithm 2025 Guide](https://www.dataslayer.ai/blog/youtube-algorithm-2025-how-to-get-your-videos-recommended)
- [YouTube CTR Optimization 2025](https://www.tubeanalytics.net/blog/youtube-ctr-optimization)

