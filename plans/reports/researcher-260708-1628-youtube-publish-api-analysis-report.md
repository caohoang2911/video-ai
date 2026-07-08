# Nghiên Cứu Kỹ Thuật: YouTube Data API v3 Auto-Upload

**Ngày:** 2026-07-08  
**Dự án:** video-ai (AI-operator faceless documentary)  
**Scope:** OAuth2 headless, videos.insert, thumbnails.set, scheduling, quota, Python implementation

---

## TÓM TẮT

YouTube Data API v3 cho phép upload video programmatic via OAuth2 + refresh token, hỗ trợ resumable upload (256MB chunks), scheduling via `publishAt`, AI disclosure via `containsSyntheticMedia`, và custom thumbnail. Python: `google-api-python-client`. **Critical gotcha:** Unverified API projects (post-7/28/2020) bị lock videos private-only; refresh token hết hạn nếu không refresh mỗi 6 tháng (chỉ token endpoint reset timer, không API calls); quota default 10,000 units/ngày (~6 uploads). Yêu cầu API Audit + verified account trước production.

---

## KIẾN TRÚC OAUTH2 HEADLESS

### Flow Chuẩn (Server without User Interaction)

```
[1] Initial Setup (Manual, once)
    └─ User approves OAuth2 consent screen
       └─ Receive authorization_code via redirect_uri

[2] Exchange Code (CLI once)
    └─ POST https://oauth2.googleapis.com/token
       ├─ client_id, client_secret, authorization_code
       └─ Response: access_token (1 hour), refresh_token (infinite)
       
[3] Store refresh_token (secure storage)
    └─ Database / env file / secrets manager

[4] Daily Usage (Headless server)
    └─ Load refresh_token from storage
    └─ Use google-api-python-client
       └─ Auto-refresh access_token when expired
       └─ Perform API calls (upload, etc.)

[5] Keep Token Alive (Monthly cron)
    └─ POST /oauth2.googleapis.com/token
       └─ grant_type=refresh_token
       └─ Resets 6-month inactivity timer
       └─ ⚠️ CRITICAL: API calls do NOT reset timer!
```

### Required OAuth2 Scope

```
https://www.googleapis.com/auth/youtube.upload
```

---

## CODE PATTERNS PYTHON

### 1. Thiết Lập Credentials từ Refresh Token

```python
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

def create_youtube_service(refresh_token, client_id, client_secret):
    """Tạo YouTube service từ refresh token"""
    credentials = Credentials(
        token=None,  # Access token sẽ được lấy lại
        refresh_token=refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=client_id,
        client_secret=client_secret
    )
    
    # Refresh access token nếu hết hạn
    if credentials.expired or not credentials.token:
        credentials.refresh(Request())
    
    return build('youtube', 'v3', credentials=credentials)
```

### 2. Upload Video với Resumable Upload (Chunked)

```python
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import time

def upload_video(youtube_service, video_file_path, metadata, max_retries=10):
    """Upload video với exponential backoff retry"""
    
    # Metadata đầy đủ (bao gồm AI label)
    body = {
        'snippet': {
            'title': metadata['title'],
            'description': metadata['description'],
            'tags': metadata.get('tags', []),
            'categoryId': metadata.get('categoryId', '22')  # People & Blogs
        },
        'status': {
            'privacyStatus': 'private',  # MUST để scheduling
            'publishAt': metadata.get('publishAt'),  # ISO 8601: "2026-07-15T15:30:00Z"
            'selfDeclaredMadeForKids': False,
            'containsSyntheticMedia': True  # AI-generated content disclosure
        }
    }
    
    media = MediaFileUpload(
        video_file_path,
        mimetype='video/mp4',
        resumable=True,
        chunksize=256*1024*1024  # 256MB chunks
    )
    
    request = youtube_service.videos().insert(
        part='snippet,status,contentDetails',
        body=body,
        media_body=media,
        notifySubscribers=False
    )
    
    response = None
    retry_count = 0
    
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"Upload progress: {int(status.progress() * 100)}%")
        except HttpError as e:
            if e.resp.status in [500, 502, 503, 504]:  # Retriable errors
                retry_count += 1
                if retry_count > max_retries:
                    raise
                wait_time = min(2 ** retry_count, 60)  # Exponential backoff
                print(f"Retrying in {wait_time}s (attempt {retry_count}/{max_retries})")
                time.sleep(wait_time)
            elif e.resp.status == 404:  # Resume upload từ đầu
                print("Restarting upload (session expired)")
                request = youtube_service.videos().insert(
                    part='snippet,status,contentDetails',
                    body=body,
                    media_body=media
                )
            else:
                raise
    
    return response['id']  # Video ID
```

### 3. Upload Custom Thumbnail (Requires Account Verified)

```python
from googleapiclient.http import MediaFileUpload

def upload_thumbnail(youtube_service, video_id, thumbnail_path):
    """Upload custom thumbnail"""
    
    media = MediaFileUpload(thumbnail_path, mimetype='image/jpeg')
    
    request = youtube_service.thumbnails().set(
        videoId=video_id,
        media_body=media
    )
    
    response = request.execute()
    return response  # {'items': [...]}
```

### 4. Refresh Token Keep-Alive (Monthly)

```python
import requests

def keep_refresh_token_alive(refresh_token, client_id, client_secret):
    """
    Monthly task: Reset 6-month inactivity timer.
    ⚠️ CRITICAL: Only token endpoint resets timer, NOT API calls!
    """
    response = requests.post(
        'https://oauth2.googleapis.com/token',
        data={
            'client_id': client_id,
            'client_secret': client_secret,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        }
    )
    
    if response.status_code == 200:
        new_token = response.json()['access_token']
        print(f"Token refreshed successfully")
        return new_token
    else:
        raise Exception(f"Token refresh failed: {response.text}")
```

---

## API ENDPOINTS & QUOTA

### Main Operations

| **Endpoint** | **Quota Cost** | **Use Case** |
|-----------|-----------|------------|
| `videos.insert` | 1,600 units | Upload video file |
| `videos.update` | 50 units | Update metadata after upload |
| `thumbnails.set` | 50 units | Upload custom thumbnail |
| `videos.list` | 1 unit | Query video info |

### Quota System (2026)

- **Default Quota:** 10,000 units/day per Google Cloud project
- **Reset Time:** Midnight Pacific Time (PT)
- **Upload Calculation:** 10,000 ÷ 1,600 = **~6 videos/day max**
- **Shared Pool:** All API keys in same project share 10,000 units
- **Quota Increase:** Manual request via Google Cloud Console (2-4 weeks), free but requires audit

---

## REQUEST BODY STRUCTURE (videos.insert)

```python
{
  "snippet": {
    "title": str,                      # Required, max 100 chars
    "description": str,                # Max 5,000 chars
    "tags": [str],                     # Max 30 tags, 500 chars total
    "categoryId": str,                 # "22" = People & Blogs, "23" = Comedy
    "defaultLanguage": "en",
    "localizations": {
      "en": {"title": "...", "description": "..."},
      "vi": {"title": "...", "description": "..."}
    }
  },
  "status": {
    "privacyStatus": "private|unlisted|public",
    "publishAt": "2026-07-15T15:30:00Z",    # ISO 8601 format (for scheduling)
    "selfDeclaredMadeForKids": bool,       # MUST explicit!
    "containsSyntheticMedia": bool,        # TRUE for AI-generated/edited
    "embeddable": bool,                    # Allow embedding
    "license": "creativeCommon|youtube",   # Copyright license
    "madeForKids": bool                    # Automatic (read-only for insert)
  },
  "contentDetails": {
    "duration": "PT5M30S",                 # ISO 8601 (auto-detected, optional)
    "projection": "rectangular|360",      # Video projection format
    "hasCustomThumbnail": bool            # Read-only after thumbnails.set
  },
  "fileDetails": {...},                    # Read-only
  "processingDetails": {...}               # Read-only
}
```

---

## GOTCHAS & CRITICAL RISKS

### 🔴 BLOCKER: Unverified API Project (Private-Only Restriction)

**Issue:** All videos uploaded from unverified API projects (created after July 28, 2020) are **permanently locked to private viewing mode**. Cannot set `privacyStatus` to `public` or `unlisted`.

**Why:** Google enforces this after API audit requirement (2020 compliance change).

**Mitigation:**
- Submit API Audit **immediately** via Google Cloud Console
- Provide: use case description, demo video of OAuth flow, ToS agreement
- Timeline: 2-4 weeks for review
- Status: No workaround; audit is non-optional for production

**Code Flag:** This is transparent in API (error: `"Videos from unverified projects cannot be public"` or video silently stays private).

---

### 🔴 BLOCKER: 6-Month Token Expiration (Refresh Token)

**Issue:** Refresh token expires if not "used" within 6 months. Unverified projects limited to 100 test users; production requires audit.

**Critical Detail:** ⚠️ **API calls do NOT count as "using" the token.** Only the token refresh endpoint (`POST /oauth2.googleapis.com/token?grant_type=refresh_token`) resets the 6-month timer.

**Symptoms:** After 6 months of inactivity, `refresh_token` returns `invalid_grant` error; must re-authenticate user manually.

**Mitigation:**
- Schedule **monthly cron job** to refresh token (not optional)
- POST: `https://oauth2.googleapis.com/token` with `grant_type=refresh_token`
- Log each refresh; alert if fails (manual re-auth needed)

**Example Cron:**
```bash
# Every 1st of month at 00:00 UTC
0 0 1 * * python /videos-ai/refresh_token_keepalive.py
```

---

### 🟠 QUOTA: 10,000 Units/Day (6 Uploads Max)

**Issue:** Default quota = 1,600 units per upload ⇒ only 6 uploads/day. Shared pool per project; multiple API keys don't increase quota.

**Error:** `quotaExceeded` (429 or 403)

**Mitigation:**
- Monitor quota usage daily
- Space uploads 2+ hours apart (avoid burst limits)
- Cache/batch thumbnail updates (each 50 units)
- Request quota increase if consistent demand > 6/day:
  - Submit form via Google Cloud Console
  - Provide business justification
  - No self-service increase; manual approval (free)

**Status Check:** Call `youtube.videos().list()` (1 unit) to check current quota; response headers include `X-RateLimit-*`.

---

### 🟠 Custom Thumbnail: Account Verification Required

**Issue:** `thumbnails.set()` endpoint requires verified Google account (phone verification).

**Why:** Prevents abuse/spam.

**Verification:** Phone verification (no subscriber count, view hours, or income requirement).

**Gotcha:** Works on long-form videos; **does NOT work on Shorts** (YouTube auto-assigns).

**Mitigation:** Verify account before production deployment.

---

### 🟡 Resumable Upload Session Expiration

**Issue:** Resumable upload session URI valid for ~7 days. If upload stalls > 7 days, session expires; must restart from chunk 0.

**Error:** `404 Not Found` on `request.next_chunk()`

**Mitigation:**
- Implement exponential backoff (2^retry, capped 60s)
- Max 10 retries
- Restart upload if 404 (reinitialize request object)
- Keep upload < 7 days (videos should encode in hours, not days)

---

### 🟡 Scheduling Requires Privacy=Private

**Issue:** `publishAt` parameter only works with `privacyStatus='private'`. Cannot schedule a public video. YouTube auto-sets public at `publishAt` time.

**Gotcha:** If `privacyStatus='public'`, `publishAt` is ignored silently.

**Mitigation:** Always set:
```python
'status': {
    'privacyStatus': 'private',
    'publishAt': '2026-07-15T15:30:00Z',
    ...
}
```

---

### 🟡 selfDeclaredMadeForKids Default Behavior

**Issue:** If omit `selfDeclaredMadeForKids` parameter, API defaults to channel-level setting (may be wrong). COPPA implications if marked incorrectly.

**Mitigation:** **ALWAYS explicitly set** `selfDeclaredMadeForKids` (True or False) on each `videos.insert`.

---

### 🟡 Chunk Size Alignment

**Issue:** Each chunk (except final) must be multiple of 256 KB (262,144 bytes). Misaligned chunks cause `400 Bad Request`.

**Mitigation:** `MediaFileUpload(chunksize=256*1024*1024)` handles this automatically.

---

## AI DISCLOSURE & COMPLIANCE (2025-2026)

- **Status Field:** `containsSyntheticMedia` (boolean)
- **Behavior:** When set `True`, YouTube automatically adds label: *"Altered or synthetic media"*
- **Required Since:** May 21, 2025 (mandatory disclosure for realistic AI-generated/edited content)
- **Applies To:** Long-form videos, Shorts, livestreams depicting events/people/places misleadingly
- **No Manual Setup:** API handles labeling if flag set; no extra action needed

**Example Scenarios:**
- ✅ Text-to-video (Runway, Domo AI) → set `containsSyntheticMedia=True`
- ✅ AI voice synthesis (ElevenLabs, Eleven) → set `containsSyntheticMedia=True`
- ✅ Deepfake/face-swap → set `containsSyntheticMedia=True`
- ✅ AI upscaling / color correction → typically `containsSyntheticMedia=True` (gray area)

---

## RECOMMENDATIONS FOR VIDEO-AI PROJECT

### 1. Pre-Production (Week 1-2)

- [ ] **Submit API Audit immediately** via [Google Cloud Console](https://console.cloud.google.com)
  - Describe: headless video upload system for documentary channel
  - Attach: OAuth2 consent screen demo, Terms of Service acceptance
  - Expected: 2-4 weeks for approval
- [ ] **Verify Google Account** (phone verification for custom thumbnails)
- [ ] **Create OAuth2 Client ID (Service Account or Desktop App pattern)**
  - Get `client_id`, `client_secret` from Google Cloud Console
  - Set redirect URI (for manual flow) or use headless flow
- [ ] **Test OAuth2 flow locally** with staging credentials
  - Generate and store test `refresh_token`
  - Verify `create_youtube_service()` works

### 2. Architecture

```
/videos-ai/
├── src/
│   ├── youtube_uploader.py         # Main upload module
│   │   ├── create_youtube_service()
│   │   ├── upload_video()
│   │   ├── upload_thumbnail()
│   │   └── keep_refresh_token_alive()
│   ├── config.py                   # Load secrets (client_id, client_secret, refresh_token)
│   └── scheduler.py                # APScheduler for uploads + monthly token refresh
├── credentials/
│   ├── refresh_token.json          # SECURE: .gitignore, env-var, secrets manager
│   └── client_secret.json          # SECURE: same
└── logs/
    └── upload_quota.log            # Track daily usage
```

### 3. Quota Management

- **Monitor daily** via logging
- **Alert threshold:** Remaining quota < 2,000 units (1-2 uploads)
- **Max uploads/day:** 5-6 (conservative buffer for metadata updates)
- **Space uploads:** 2+ hours apart (throttle to avoid burst-limiting)

### 4. Error Handling Priority

| **Error** | **Action** |
|-----------|-----------|
| `quotaExceeded` (429/403) | Wait until tomorrow; alert ops |
| `401 Unauthorized` | Refresh token failed; manual re-auth |
| `404 Not Found` (upload) | Restart upload (session expired) |
| `500/502/503/504` | Exponential backoff + retry |
| `400 Bad Request` | Log full error; likely invalid metadata |

### 5. Cron Schedule (APScheduler)

```python
# scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()

# Upload videos (3x/day, staggered)
scheduler.add_job(upload_pending_video, 'cron', hour='8,14,20')

# Refresh token (1st of month)
scheduler.add_job(keep_refresh_token_alive, 'cron', day=1, hour=0, minute=0)

# Log quota usage (daily)
scheduler.add_job(log_quota_usage, 'cron', hour=23, minute=30)

scheduler.start()
```

### 6. Testing Checklist

- [ ] OAuth2 flow: Get access token from refresh token
- [ ] Upload small test video (~10MB) → verify private-only (if unverified)
- [ ] Update metadata post-upload
- [ ] Upload thumbnail (verify account required)
- [ ] Schedule video (set `publishAt` + `privacyStatus=private`)
- [ ] Verify `containsSyntheticMedia=True` label appears on YouTube Studio
- [ ] Token refresh logic (simulate 6-month expiry)
- [ ] Exponential backoff on 503 error (mock)

---

## UNRESOLVED QUESTIONS

1. **Exact Quota Reset Time (Midnight PT):** Need to verify if 00:00 PT or 23:59 PT boundary.
2. **Retry-After Header Parsing:** Google may return `Retry-After` header; should use instead of fixed exponential backoff?
3. **`onBehalfOfContentOwner` Quota Impact:** Does uploading on behalf of multi-channel partner consume separate quota?
4. **Video File Size Limit:** Docs say "up to 256GB" but practical limits?
5. **Chunked Upload Resume Across Sessions:** Can resume using Location URI if server restarts, or must re-initialize?

---

## SOURCES

- [Upload a Video | YouTube Data API | Google for Developers](https://developers.google.com/youtube/v3/guides/uploading_a_video)
- [Videos: insert | YouTube Data API | Google for Developers](https://developers.google.com/youtube/v3/docs/videos/insert)
- [Resumable Uploads | YouTube Data API | Google for Developers](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol)
- [Media Upload | google-api-python-client](https://googleapis.github.io/google-api-python-client/docs/media.html)
- [How we're helping creators disclose altered or synthetic content - YouTube Blog](https://blog.youtube/news-and-events/disclosing-ai-generated-content/)
- [Thumbnails: set | YouTube Data API | Google for Developers](https://developers.google.com/youtube/v3/docs/thumbnails/set)
- [YouTube API Quota Limits 2026: 10,000 Units, Costs & How to Get More](https://www.getphyllo.com/post/youtube-api-limits-how-to-calculate-api-usage-cost-and-fix-exceeded-api-quota)
- [Using OAuth 2.0 to Access Google APIs | Authorization | Google for Developers](https://developers.google.com/identity/protocols/oauth2)
- [Google OAuth Refresh Token: Expiration, 7-Day Limit & Lifetime Explained (2026) - Unipile](https://www.unipile.com/google-oauth-refresh-token/)
- [Quota and Compliance Audits | YouTube Data API | Google for Developers](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits)
