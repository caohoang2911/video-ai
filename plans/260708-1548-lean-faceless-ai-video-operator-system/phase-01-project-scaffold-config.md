# Phase 01 — Project Scaffold + Config + DB Schema

## Context Links
- Overview: [plan.md](plan.md) · Prev: [phase-00](phase-00-prerequisites-user-setup.md)
- Feeds: mọi phase (config, DB, logging là nền tảng chung — DRY).

## Overview
- **Priority:** P0
- **Status:** in-progress (foundation đã có code: config/db/state_machine/cost/checkpoint/dedup — verify vs success criteria)
- **Description:** Dựng khung repo, quản lý secrets, dependencies (pin version), SQLite schema (state machine + bảng dữ liệu), logging + settings loader. Nền chung để các engine cắm vào.

## Key Insights
- **Pin version cứng** để tránh gãy: `Pillow==10.2.0` (Pillow 11/12 gãy MoviePy 2.x TextClip), MoviePy 2.x (`moviepy>=2.1`), `faster-whisper`, `python-telegram-bot>=21.8`, `APScheduler>=3.11,<4`, `google-api-python-client`. Import `from moviepy` (KHÔNG `moviepy.editor`).
- **Python 3.11** target (máy có 3.14 — quá mới cho vài lib). Dùng `uv` hoặc `pyenv` tạo venv 3.11.
- **SQLite P0 → Postgres P1:** dùng SQLAlchemy Core/ORM ngay để P1 đổi engine chỉ sửa URL. Bật `PRAGMA journal_mode=WAL` giảm write-lock (APScheduler + app cùng ghi).
- **State machine là xương sống:** mọi phase đọc/ghi `videos.state`. Định nghĩa states 1 chỗ (DRY).
- **Cost guardrail là bắt buộc (critical):** mỗi step gọi API tốn tiền (ElevenLabs, Anthropic, fal) → cần cost-estimator TRƯỚC khi gọi + hard-limit theo `MONTHLY_BUDGET` (mặc định $500). Ước ElevenLabs theo số ký tự script (±10%), Anthropic theo token in/out. Nếu `estimated_cost > budget_remaining` → reject + alert Telegram. WHY: 1 vòng lặp lỗi có thể đốt hết ngân sách trong vài phút.
- **Idempotency chống charge/upload trùng:** mỗi video có `idempotency_key`; sau MỖI step ghi `output/checkpoints/{video_id}.checkpoint.json` (step cuối hoàn tất + artifact paths). Khi khởi động lại, resume-from-last-step thay vì chạy lại từ đầu. WHY: crash/restart giữa chừng không được upload YouTube hay gọi TTS lần 2 (mất tiền + trùng nội dung).
- **Topic dedup ngữ nghĩa:** bảng `topic_history` lưu embedding (`all-MiniLM-L6-v2`, 384-dim) của topic đã tạo; trước khi tạo video mới, tính cosine với lịch sử — nếu `≥0.85` → reject (trùng ý dù khác chữ). WHY: tránh làm lại nội dung na ná nhau → kênh bị đánh trùng lặp.

## Requirements
Functional: config loader từ `.env`; DB schema + migrations tối thiểu; logging chuẩn; CLI entrypoint để chạy từng bước tay (P0).
Non-functional: file <200 dòng; secrets không lộ; SQLite WAL; timezone-aware (UTC lưu, convert khi hiển thị).

## Architecture — cấu trúc repo
```
video-ai/
├── pyproject.toml            # deps + pin version (uv/pip)
├── .env.example             # template keys (KHÔNG chứa giá trị thật)
├── .gitignore               # + client_secret.json, token.json, *.key, data/, output/
├── src/ai_operator/
│   ├── __init__.py
│   ├── config.py            # Settings (pydantic-settings) load .env
│   ├── logging_setup.py     # logging dict config → stdout + file rotativo
│   ├── db/
│   │   ├── engine.py        # create_engine, WAL pragma, session factory
│   │   ├── models.py        # SQLAlchemy models (bảng dưới)
│   │   └── state_machine.py # enum VideoState + transitions hợp lệ (DRY)
│   ├── cost/
│   │   ├── estimator.py     # ước cost per-step (ký tự→ElevenLabs, token→Anthropic)
│   │   └── budget_guard.py  # cộng dồn cost tháng + hard-limit vs MONTHLY_BUDGET
│   ├── checkpoint.py        # ghi/đọc output/checkpoints/{video_id}.checkpoint.json (resume)
│   ├── dedup/
│   │   └── topic_dedup.py   # embed topic (all-MiniLM-L6-v2) + cosine ≥0.85 reject
│   └── cli.py               # typer/argparse: run-step <name> --video-id
├── data/                    # sqlite db (gitignored)
├── output/
│   └── checkpoints/         # {video_id}.checkpoint.json (resume-from-last-step)
│                            # render mp4/audio/img (gitignored)
└── tests/
```

## DB Schema (SQLite, SQLAlchemy)
- **topics**: `id, slug, title, angle (góc riêng), source_notes, status(backlog|used|rejected), created_at`.
- **videos**: `id, topic_id(FK), state, idempotency_key(unique), script_path, audio_path, video_path, thumb_path, title, description, tags(JSON), duration_sec, created_at, updated_at` (`idempotency_key` chặn tạo/charge trùng cho cùng 1 đơn vị công việc).
- **assets**: `id, video_id(FK), kind(stock|gen|music), source(pexels|pixabay|sdxl|fal), url_or_path, license, md5, created_at` (audit royalty-free + de-dup).
- **uploads**: `id, video_id(FK), youtube_video_id, publish_at, privacy, status(pending|scheduled|published|failed), error, created_at`.
- **analytics**: `id, youtube_video_id, as_of_date, views, watch_time_min, avg_view_pct, ctr, rpm, est_revenue, raw(JSON)`.
- **app_state**: `key, value` (KV: quota dùng hôm nay, last_publish_at, weekly_count…).
- **cost_ledger**: `id, video_id(FK, nullable), step, provider(elevenlabs|anthropic|fal|…), units(ký tự/token), estimated_cost, actual_cost, ym(YYYY-MM), created_at` (cộng dồn chi phí; query `SUM(actual_cost) WHERE ym=?` để tính budget_remaining tháng).
- **topic_history**: `id, topic_name, embedding(BLOB 384-dim all-MiniLM-L6-v2), created_at` (check trùng ngữ nghĩa cosine ≥0.85 trước khi tạo topic mới).

VideoState enum (state_machine.py): `draft → scripted → voiced → rendered → pending_review → policy_ok → approved → published → analyzed`; nhánh phụ `rejected`, `editing`, `rerun_queued`, `failed` (khớp phase-05 review 2-tầng). Hàm `can_transition(cur, next) -> bool` + `assert_transition()`. **(đã implement — verify vs success criteria).**

## Related Code Files
- Create: `pyproject.toml`, `.env.example`, `src/ai_operator/config.py`, `logging_setup.py`, `db/engine.py`, `db/models.py`, `db/state_machine.py`, `cli.py`, `src/ai_operator/__init__.py`.
- Modify: `.gitignore` (thêm `client_secret.json`, `token.json`, `*.key`, `data/`, `output/`, `token/`).
- Delete: none.

## Implementation Steps
1. `uv venv --python 3.11` (hoặc pyenv) → tạo venv. `uv init` sinh `pyproject.toml`.
2. Thêm deps pin: `moviepy>=2.1`, `Pillow==10.2.0`, `faster-whisper`, `elevenlabs`, `anthropic`, `google-genai` (tuỳ chọn), `pexels`/`requests`, `requests-cache`, `requests-ratelimiter`, `google-api-python-client`, `google-auth-oauthlib`, `python-telegram-bot>=21.8`, `APScheduler>=3.11,<4`, `python-statemachine>=3.2` (hoặc enum tự viết — KISS), `SQLAlchemy>=2`, `pydantic-settings`, `typer`, `edge-tts`, `sentence-transformers` (topic dedup — model `all-MiniLM-L6-v2`, ~90MB, chạy CPU), `numpy` (cosine), `diffusers`/`torch` (SDXL — cài riêng vì nặng).
3. `config.py`: class `Settings(BaseSettings)` map mọi env key; `settings = Settings()`.
4. `.env.example`: liệt kê mọi key (không giá trị): `ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ANTHROPIC_API_KEY, GEMINI_API_KEY, PEXELS_API_KEY, PIXABAY_API_KEY, FAL_KEY, YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN, YT_CHANNEL_ID, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DB_URL=sqlite:///data/operator.db, MONTHLY_BUDGET=500`.
5. `db/engine.py`: `create_engine(settings.DB_URL)`, event listener set `PRAGMA journal_mode=WAL` + `foreign_keys=ON`; `SessionLocal`.
6. `db/models.py`: 8 bảng trên (giữ <200 dòng; nếu tràn tách `models_analytics.py` / `models_ops.py` cho `cost_ledger`+`topic_history`).
7. `db/state_machine.py`: enum + transition map + assert helper.
8. `logging_setup.py`: RotatingFileHandler `output/logs/operator.log` + stream stdout; format có timestamp, level, module.
9. `cost/estimator.py`: `estimate_step(step, provider, units) -> float` (ElevenLabs: ký tự × giá/ký tự, buffer +10%; Anthropic: token in/out × giá model). `cost/budget_guard.py`: `budget_remaining()` = `MONTHLY_BUDGET - SUM(actual_cost WHERE ym=current)`; `check_and_reserve(est)` → raise `BudgetExceeded` + alert Telegram nếu `est > remaining`; sau khi gọi API ghi `actual_cost` vào `cost_ledger`.
10. `checkpoint.py`: `write(video_id, step, artifacts)` → JSON atomic (write tmp + rename); `read(video_id)` → last step; `resume(video_id)` cho CLI/scheduler bỏ qua step đã xong. Tạo/tra `idempotency_key` để không khởi tạo video trùng.
11. `dedup/topic_dedup.py`: load `all-MiniLM-L6-v2` (lazy, cache model); `is_duplicate(topic_name) -> bool` = max cosine với `topic_history.embedding` ≥ 0.85; `record(topic_name)` lưu embedding sau khi accept.
12. `cli.py`: lệnh `init-db` (create_all), `run-step <name>` (gọi `budget_guard.check_and_reserve` + `checkpoint.resume` trước khi chạy), `status` (in budget_remaining tháng), `costs` (bảng cộng dồn theo provider).
13. Chạy `uv run operator init-db` → verify DB tạo bảng. Compile check: `python -m compileall src`.

## Todo List
- [ ] venv 3.11 + pyproject deps pin (+ sentence-transformers, numpy)
- [ ] config.py (+ MONTHLY_BUDGET) + .env.example
- [ ] .gitignore hardening
- [ ] db engine (WAL) + models 8 bảng (+ cost_ledger, topic_history; videos.idempotency_key)
- [ ] state_machine enum + transitions
- [ ] logging_setup
- [ ] cost estimator + budget_guard (hard-limit vs MONTHLY_BUDGET + alert)
- [ ] checkpoint.py (write/read/resume) + idempotency_key
- [ ] topic_dedup (all-MiniLM-L6-v2, cosine ≥0.85)
- [ ] cli init-db / status / costs
- [ ] `operator init-db` chạy OK, compileall pass

## Success Criteria
- `uv run operator init-db` tạo `data/operator.db` với 8 bảng (verify `sqlite3 .tables`).
- `Settings()` load `.env` không lỗi; thiếu key báo rõ; `MONTHLY_BUDGET` default 500 khi vắng.
- `budget_guard.check_and_reserve(est)` raise `BudgetExceeded` khi `est > remaining` (test với ledger giả cận ngân sách).
- Ghi rồi restart → `checkpoint.resume(video_id)` trả đúng step cuối, không chạy lại step đã xong.
- `topic_dedup.is_duplicate` trả `True` cho 2 topic diễn đạt khác nhưng cùng ý (cosine ≥0.85).
- `python -m compileall src` không lỗi.

## Risk Assessment
| Risk | L | I | Mitigation |
|---|---|---|---|
| Python 3.14 vô tình dùng → lib gãy | Med | High | Ép venv 3.11; ghi trong README; CI check version. |
| Pillow version drift gãy TextClip | Med | High | Pin `==10.2.0`; lock file commit. |
| SQLite write-lock giữa app + scheduler | Med | Med | WAL mode; transaction ngắn; single-writer pattern (phase 07). |
| Vòng lặp lỗi đốt hết ngân sách API | Med | High | Cost-estimator + hard-limit `MONTHLY_BUDGET`; reject khi `est > remaining` + alert Telegram; ghi `cost_ledger` cộng dồn. |
| Ước cost lệch thực tế (giá provider đổi) | Med | Med | Buffer +10% khi ước; ghi `actual_cost` sau mỗi call để đối chiếu; giá provider để trong config, cập nhật 1 chỗ. |
| Crash/restart → upload YouTube / TTS gọi lần 2 (mất tiền, trùng) | Med | High | `idempotency_key` unique + `checkpoint.json` sau mỗi step; resume-from-last-step, không rerun step đã xong. |
| Topic trùng ý nhau → kênh bị đánh trùng lặp | Med | Med | `topic_history` embedding + cosine ≥0.85 reject trước khi tạo. |
| Model embedding tải chậm/nặng lần đầu | Low | Low | `all-MiniLM-L6-v2` ~90MB chạy CPU; lazy-load + cache; tải sẵn trong phase 00. |

## Security Considerations
- `.gitignore` phủ `.env*`, `client_secret.json`, `token.json`, `*.key`. Verify `git status` không thấy secrets trước commit.
- `config.py` không log giá trị key (chỉ log tên key thiếu).

## Next Steps
→ Phase 02 (content engine) dùng `config`, `db`, `state_machine`.

## Unresolved Questions
- Dùng `python-statemachine` lib hay enum + dict tự viết? — đề xuất enum tự viết (KISS, ít deps). Lib chỉ khi cần persistence/callback phức tạp (P1).
