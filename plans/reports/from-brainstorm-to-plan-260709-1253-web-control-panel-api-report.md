# Brainstorm Summary — Web Control Panel + API cho AI Operator

- Date: 2026-07-09 12:53 · Branch: `feat/ops-observability-validation`
- Status: **APPROVED** (Approach A) — sẵn sàng cho `/ck:plan`

## Problem statement
Pipeline hiện điều khiển thuần **CLI (typer)** + review qua **Telegram bot**. User muốn **xuất API + UI (control panel)** để *quản lý* (xem + điều khiển) toàn bộ tính năng pipeline từ web.

## Requirements (chốt qua discovery)
1. **Expected output:** 1 web control panel (FastAPI + HTMX/Jinja) + REST/JSON API, chạy local, điều khiển được các tính năng pipeline.
2. **Acceptance:**
   - Xem: counts theo state, budget/quota còn, lỗi gần nhất, validation PASS/KILL, list/detail video, costs, analytics, hàng đợi jobs.
   - Điều khiển: trigger produce/gen-script/gen-audio/gen-visuals/revoice/assemble/publish/pull-analytics (**enqueue**); approve/reject/edit-metadata/set-winner (**gọi thẳng**).
   - Mỗi trang có bản JSON `/api/...` dùng chung handler.
3. **Scope OUT:** auth/multi-user, deploy VPS/token, SPA frontend, thay đổi state machine, sửa business logic pipeline.
4. **Constraints:** Python 3.11, KISS/YAGNI/DRY, mỗi file <200 dòng, free-stack, **local-only bind 127.0.0.1 no-auth**, execution = **chỉ enqueue vào scheduler**.
5. **Touchpoints:** `ops/scheduler.py`, `ops/pipeline_runner.py`, `db/models_ops.py`, `cli.py` (`_PHASE_COMMAND_MODULES`), `review/decision_finalize.py`, `ops/health`, `*/commands.py`.

## Decisions (user-confirmed — do NOT auto-reverse)
| Câu hỏi | Chọn |
|---------|------|
| Scope | **Control panel đầy đủ** (xem + điều khiển) |
| UI stack | **FastAPI + HTMX/Jinja** (KISS, server-rendered, no npm) |
| Auth | **Local-only, không auth** (bind 127.0.0.1) |
| Execution | **Chỉ enqueue vào scheduler** (không chạy trực tiếp trong web) |
| Topology | **A: 3 process + DB job queue** |

## Approaches evaluated
- **A (CHOSEN):** 3 process (`run-web`/`run-scheduler`/`run-bot`) + bảng `jobs` làm queue; web enqueue, scheduler drain. Decoupled, robust khi restart, khớp mô hình hiện tại.
- **B (rejected):** web ôm APScheduler, `add_job(now)`. Ít process nhưng web phải luôn up, khó chạy kèm bot, mất tách executor.
- **C (rejected):** FastAPI BackgroundTasks. Chết theo web process, trái yêu cầu "enqueue vào scheduler".

## Final design (Approach A)
### Nguyên tắc DRY
Web chỉ: (a) đọc DB hiển thị, (b) enqueue job, (c) thao tác nhẹ gọi thẳng `decision_finalize`. Compute nặng vẫn do `pipeline_runner`/commands hiện tại → không nhân đôi logic.

### DB job queue
```
[FastAPI web] --insert--> [jobs table] <--poll/claim-- [scheduler]
 POST /jobs    pending      drain_jobs() ~20s → dispatch → pipeline_runner
```
Bảng `jobs` (thêm `db/models_ops.py`): `id, command, video_id?, topic_id?, params(JSON), status(pending|running|done|failed), error?, idempotency_key, created_at, started_at, finished_at`.
- `POST /jobs`: ghi 1 dòng `pending` (idempotency_key chống double-click) → trả ngay.
- Scheduler: `drain_jobs` interval ~20s, `max_instances=1`, claim atomic 1 job → map `command→hàm` → chạy tuần tự → ghi kết quả.

Phân loại: **nặng → enqueue** (produce, gen-*, revoice, assemble, publish, pull-analytics); **nhẹ → gọi thẳng** (approve/reject/edit/set-winner).

### Module mới (mỗi file <200 dòng)
```
src/ai_operator/web/app.py               # FastAPI factory + Jinja/HTMX, bind 127.0.0.1
src/ai_operator/web/routes_dashboard.py  # / (reuse ops.health + validation)
src/ai_operator/web/routes_videos.py     # /videos list+detail + action → POST /jobs
src/ai_operator/web/routes_topics.py     # /topics backlog + gen-topics + produce
src/ai_operator/web/routes_ops.py        # /costs /analytics /jobs
src/ai_operator/web/templates/*.html     # Jinja + htmx.min.js (static)
src/ai_operator/web/static/              # 1 css + htmx.min.js
src/ai_operator/web/commands.py          # `operator run-web` (uvicorn) — auto-mount
src/ai_operator/ops/job_worker.py        # drain_jobs + dispatch map
```
Sửa tối thiểu: `ops/scheduler.py` (+add drain job), `cli.py` (+`"web.commands"`), `db/models_ops.py` (+Job).

### Trang (HTMX)
`/` dashboard · `/videos` + `/videos/{id}` · `/topics` · `/costs` · `/analytics` · `/jobs`. Mỗi trang kèm `/api/...` JSON.

### Deps thêm
`fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`. HTMX = 1 file static.

### Deploy
3 process local Mac: `run-web` (127.0.0.1:8000) · `run-scheduler` (executor) · `run-bot` (coexist; web+Telegram approve dùng chung `decision_finalize`).

## Risks & mitigations
- **SQLite đa process:** WAL + transaction ngắn + claim job atomic (đã đa-process sẵn).
- **Job tuần tự (1/lần):** render lâu làm job sau chờ → chấp nhận cho solo; `/jobs` show tiến độ.
- **Local no-auth:** bind cứng 127.0.0.1, không expose. VPS/token = scope sau.
- **Nhất quán review web↔Telegram:** bắt buộc reuse `decision_finalize` (không viết lại quyết định).

## Success metrics
- Trigger mọi step nặng từ UI → xuất hiện `pending` ở `/jobs` → scheduler chạy → state chuyển đúng.
- Approve/reject từ web = kết quả giống Telegram (cùng `decision_finalize`).
- Web up/down không mất job đã enqueue (queue nằm ở DB).
- Không sửa/nhân đôi business logic pipeline hiện có.

## Unresolved questions
- Port mặc định `run-web` (đề xuất 8000) — cần chốt khi plan.
- `/jobs` có cần nút cancel/retry job `failed` không (P1?) — mặc định: retry có, cancel để sau.
- Preview video trên `/videos/{id}`: serve file local qua static mount hay chỉ hiện path — đề xuất static mount read-only cho output dir.
