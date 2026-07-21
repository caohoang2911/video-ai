# Phase 02 — Comment poster + scheduler scan

**Priority:** P0 | **Status:** ⬜ chưa làm | **Depends on:** phase 01

## Overview

Một module mới `publisher/first_comment.py` chứa toàn bộ: kiểm tra video đã live chưa,
gọi `commentThreads.insert`, phân loại lỗi, và một hàm quét các upload đến hạn. Wire vào
APScheduler như một interval job. Không có job-queue command mới, không có bảng mới.

## Key insights

- **Không dùng APScheduler `date` job** bắn đúng `publish_at`: jobstore là in-memory
  (`build_scheduler()` không cấu hình jobstore), laptop sleep/restart là mất job vĩnh viễn,
  và misfire bị drop chứ không retry. Dùng **level-triggered DB scan** — trạng thái nằm
  trong DB, tick nào cũng tự phục hồi.
- **Không dùng `job_queue.enqueue`**: `drain_jobs` chạy mỗi 20s, sẽ thực thi trước go-live
  hàng giờ. Và thêm command mới bắt buộc sửa lockstep `JOB_COMMANDS` ↔ `DISPATCH` (có test
  ép), tăng bề mặt cho một feature 5 post/tuần.
- **`publish_at` đã qua là *dự đoán* go-live, không phải sự thật.** Operator có thể kéo
  video về private trong Studio, hoặc YouTube flip trễ. Nên trước mỗi insert phải gọi
  `videos.list(part="status", id=...)` (1 quota unit) và chỉ post khi
  `privacyStatus in {"public", "unlisted"}`. Đây là lỗ hổng đúng nghĩa nếu bỏ qua.
- **Phân loại lỗi theo `error["errors"][0]["reason"]`, không theo HTTP 403.** 403 gộp cả
  `quotaExceeded` (retry sau khi quota reset), `insufficientPermissions` (chưa re-auth),
  và `forbidden` (terminal). Doc lỗi của YouTube **không đầy đủ** — reason lạ phải coi là
  **retry được** + alert "unclassified", không được im lặng tắt feature vĩnh viễn.
- Ghi `checkpoint` ngay khi API trả 200, **trước** khi commit DB — đúng pattern đã dùng ở
  `publish.py:139`. Đây là thứ chặn double-post khi crash giữa API-200 và DB-commit.
- Không có cột `comment_attempts`. Thay bằng: transient thì để yên cho tick sau; nếu quá
  `publish_at + 2h` mà vẫn chưa có `comment_id` → **một** alert. Im lặng mới là failure mode,
  không phải thiếu bộ đếm.

### ⚠️ Bẫy 1 — `publish_at` đọc từ SQLite là NAIVE

`Upload.publish_at` khai `DateTime(timezone=True)` (`models.py:90`) và `publish.py:199` ghi
giá trị **aware**, nhưng `DB_URL` là SQLite (`config.py:96`) và dialect SQLite **vứt offset**.
Đã repro trong repo này:

```
ghi AWARE -> đọc lại tzinfo = None
row.publish_at + timedelta(hours=2) < datetime.now(timezone.utc)
  -> TypeError: can't compare offset-naive and offset-aware datetimes
```

Vì `comment_job` bọc try/except-log, tick đầu tiên gặp dòng đến hạn sẽ **không post gì, im
lặng, mãi mãi**. Quy tắc bắt buộc:

> **Không bao giờ làm số học datetime với `publish_at` ở phía Python.** Mọi so sánh phải
> nằm trong mệnh đề WHERE của SQLAlchemy — đúng tiền lệ duy nhất trong repo,
> `scheduler.py:117-126` (`Upload.publish_at > cutoff` với `cutoff` tính sẵn).

Test phải **round-trip qua `SessionLocal`**, không truyền thẳng datetime aware vào hàm —
fixture kiểu đó sẽ pass trong khi production gãy.

### ⚠️ Bẫy 2 — một `video_id` có thể có nhiều dòng `uploads`

`_ensure_upload_row` (`publish.py:181-189`) chỉ tái dùng dòng khi trùng cả
`(video_id, youtube_video_id)`, nên xoá-rồi-publish-lại sinh dòng thứ hai. Repo đã có quy
ước latest-wins ở 4 chỗ (`publish.py:53`, `publish.py:83`, `ab_variants.py:31`,
`routes_videos.py:236`). **Mọi** điểm truy cập mới (scan + 3 route phase 03) phải dùng đúng
một biểu thức:

```python
select(Upload).where(Upload.video_id == vid).order_by(Upload.id.desc()).limit(1)
```

Không nêu rõ thì route lưu sẽ ghi vào dòng **cũ** (thứ tự mặc định) trong khi trang chi tiết
đọc dòng mới → text biến mất và scan post lên `youtube_video_id` đã chết.

### ⚠️ Bẫy 3 — read-then-act không chặn được double-post

`max_instances=1` chỉ tuần tự hoá job comment **với chính nó**. Scheduler chạy trong tiến
trình `run-scheduler` (`ops/commands.py:21`), còn route "Đăng ngay" chạy trong tiến trình
uvicorn riêng (`web/commands.py:27`), và handler sync của FastAPI chạy trên threadpool. Hai
lần double-click trong lúc `commentThreads.insert` đang block 3-6s là race thật.

Guard phải là **claim nguyên tử**, không phải đọc-rồi-kiểm-tra:

```python
UPDATE uploads SET comment_posted_at = :now
 WHERE id = :id AND comment_posted_at IS NULL
```

`rowcount == 0` → bỏ cuộc ngay. Điền `comment_id` sau khi insert trả về; xoá lại
`comment_posted_at` nếu thất bại kiểu defer được. Nếu không: hai comment giống hệt xuất
hiện, và lần ghi thứ hai đè `comment_id`, bỏ rơi comment thứ nhất vĩnh viễn — mà plan cấm
viết path `comments.delete`.

## Related code files

**Create**
- `src/ai_operator/publisher/first_comment.py` (~130 dòng)
- `tests/test_first_comment.py`

**Modify**
- `src/ai_operator/ops/scheduler.py` — thêm `comment_job` + `sched.add_job(...)`

## Architecture

```
scheduler (interval 15m, max_instances=1, coalesce)
   └─ comment_job()                     # try/except-log như analytics_job
        ├─ first_comment.sweep_stale()          # LUÔN chạy, KHÔNG nằm sau kill switch
        └─ first_comment.post_due_comments()
             ├─ if not settings.SHORTS_COMMENT_AUTOPOST: return 0     # kill switch
             ├─ _due_rows(now) -> SELECT ... (xem dưới)
             └─ for each: first_comment.post_comment(video_id)

_due_rows(now)  # mọi so sánh thời gian nằm TRONG WHERE, không ở Python (Bẫy 1)
   SELECT uploads JOIN videos WHERE
       videos.kind = 'short'
       AND uploads.youtube_video_id IS NOT NULL
       AND uploads.comment_text     IS NOT NULL
       AND uploads.comment_id       IS NULL
       AND uploads.comment_posted_at IS NULL      # claim marker (Bẫy 3)
       AND uploads.comment_error    IS NULL
       AND uploads.publish_at <= :now_minus_2min
       AND uploads.publish_at >= :now_minus_max_age    # trần tuổi, xem bên dưới
     ORDER BY uploads.publish_at   LIMIT _MAX_PER_TICK (2)

post_comment(video_id) -> str | None      # cũng là handler cho nút "Đăng ngay"
   ├─ row = latest uploads row của video_id            # Bẫy 2
   ├─ guard: comment_id đã có -> return (idempotent, đường tuần tự)
   ├─ guard: comment_text rỗng -> raise
   ├─ checkpoint.artifacts_of(video_id, "yt_comment") -> nếu có, adopt & ghi DB
   ├─ CLAIM nguyên tử: UPDATE ... SET comment_posted_at=now WHERE comment_posted_at IS NULL
   │     rowcount == 0 -> return (ai đó đang post)     # Bẫy 3
   ├─ _is_live(service, yt_id)   # videos.list(part=status)
   │     -> reserve(YT_COST_VIDEO_LIST) NGAY SAU lời gọi, kể cả khi defer
   │     -> False: nhả claim (comment_posted_at=NULL), return; KHÔNG phải lỗi
   ├─ service.commentThreads().insert(part="snippet", body={...textOriginal: text})
   │     -> reserve(YT_COST_COMMENT) sau khi gọi
   ├─ checkpoint.write(video_id, "yt_comment", {"comment_id": ...})   # NGAY khi 200
   └─ DB: comment_id (comment_posted_at đã set ở bước claim); alert Telegram kèm deep link
```

**Quota phải `reserve` SAU lời gọi, không phải trước.** `quota_throttle.reserve()` là
sổ sách thuần (`quota_throttle.py:77-103`) — đặt nó chỉ trên nhánh insert thành công làm
các tick defer tiêu unit mà không ghi sổ, và `health` sẽ báo quota sai. Mỗi lời gọi API
thật đều `reserve` phần của nó.

**Trần tuổi.** Scan từ chối tự post dòng quá `SHORTS_COMMENT_MAX_AGE_H` (đề xuất 24h) và
alert "quá cũ — đăng tay hoặc bỏ qua". Copy trong playbook viết theo khung "vừa lên sóng";
post trễ 3 ngày là sai ngữ cảnh, không chỉ là muộn.

**Bất biến bắt buộc có test:** text lên wire **byte-for-byte** bằng `comment_text` operator
đã lưu. Không append CTA, không append link, không append hashtag. Đây vừa là yêu cầu
consent của policy, vừa là thứ giữ copy khỏi biến thành template lặp.

## Implementation steps

1. `first_comment.py`: docstring nêu **tại sao** không post trong `publish()` (video private,
   YouTube cấm comment trên private) và **tại sao** dùng level-triggered scan (jobstore
   in-memory). Không nhắc phase/plan.
2. `_TERMINAL_REASONS = {"forbidden", "ineligibleAccount", "videoNotFound", "channelNotFound",
   "commentTextTooLong", "commentTextRequired"}` → ghi `comment_error`, alert, dừng.
   `insufficientPermissions` → alert nêu **nguyên văn câu lệnh re-auth**, ghi `comment_error`.
   `quotaExceeded` → defer im lặng (tick sau). Reason khác → defer + alert "unclassified".
3. `_is_live(service, yt_id)` — `videos.list(part="status", id=yt_id)`, trả `True` khi
   `privacyStatus` thuộc `{"public", "unlisted"}`. Không tìm thấy item → coi như chưa live.
4. `post_comment(video_id)` theo sơ đồ trên. Dùng `build_service()` từ `oauth_headless`.
5. `post_due_comments(now=None)` — query + cap 2/tick + gọi `post_comment`, bắt exception
   từng dòng để một video hỏng không chặn video còn lại (pattern giống `analytics_puller`).
6. `sweep_stale()` — **hàm riêng, gọi TRƯỚC kill switch**, nên tắt autopost vẫn còn cảnh báo.
   Đây là chế độ mặc định đã chốt (`SHORTS_COMMENT_AUTOPOST=False`), nên nếu alert nằm sau
   early-return thì ở cấu hình mặc định **không có tín hiệu nào cả** — đúng thứ feature này
   cần nhất.

   Level-triggered, dedupe **một lần duy nhất** bằng checkpoint key `yt_comment_stale`:
   quét short đã live quá 2h mà `comment_id IS NULL` (kể cả `comment_text IS NULL` — nghĩa là
   operator chưa viết gì), gửi một alert, ghi checkpoint. Không dùng cửa sổ "2h–3h": nó
   edge-triggered theo giờ tường, bỏ lọt mọi sự cố dài hơn 3h (chính là dạng hỏng phổ biến
   nhất — laptop ngủ), đồng thời bắn 4-5 push giống hệt nhau vào đúng chat Telegram đang
   gánh review gate.
7. `scheduler.py`: thêm `comment_job()` bọc try/except-log, và
   `sched.add_job(comment_job, "interval", minutes=15, id="comments", max_instances=1, coalesce=True)`.

## Tests (`tests/test_first_comment.py`)

- `test_scan_skips_when_autopost_disabled`
- `test_stale_sweep_still_runs_when_autopost_disabled` — mặc định là tắt, nên đây là
  đường chạy thật, không phải trường hợp biên
- `test_two_concurrent_posts_insert_once` — hai lời gọi `post_comment` song song trên cùng
  một dòng → đúng một `commentThreads.insert` (test tuần tự bên dưới KHÔNG phủ ca này)
- `test_due_query_roundtrips_publish_at_through_session` — ghi `publish_at` **aware** qua
  `SessionLocal` rồi mới gọi hàm; fixture truyền thẳng datetime aware sẽ pass giả
- `test_scan_refuses_rows_older_than_max_age`
- `test_uses_latest_uploads_row_when_video_has_two`
- `test_scan_selects_only_live_shorts_with_approved_text` — main video, `comment_text` NULL,
  `comment_id` đã set, `comment_error` đã set, `publish_at` tương lai → đều bị loại
- `test_post_is_idempotent_when_comment_id_present` — không gọi API lần hai
- `test_checkpoint_adopted_when_db_write_lost` — checkpoint có id, DB chưa → adopt, không post lại
- `test_defers_when_video_not_yet_public` — `_is_live` False → không insert, không ghi error
- `test_terminal_reason_sets_error_and_alerts`
- `test_unknown_reason_is_retryable_not_terminal`
- `test_insufficient_permissions_alert_names_reauth_command`
- `test_posted_text_is_byte_identical_to_approved_text`

## Success criteria

- Chạy scan trên DB có 1 short đã live + text đã duyệt → đúng 1 `commentThreads.insert`,
  `comment_id` + `comment_posted_at` được ghi, alert gửi kèm deep link.
- Chạy lại scan ngay sau → 0 lời gọi API.
- Toàn bộ test suite pass.

## Security considerations

- Không bao giờ log `comment_text` đầy đủ ở mức INFO (nhiễu), nhưng **phải** lưu nguyên văn
  trong DB — đó là bằng chứng consent.
- Không viết bất kỳ path nào gọi `comments.delete` hay `setModerationStatus`, dù scope cho phép.
- Không có fallback browser-automation khi API lỗi — vi phạm ToS. Lỗi thì fail loud.

## Next steps

Phase 03 — form duyệt + nút "Đăng ngay" + hand-off ghim.
