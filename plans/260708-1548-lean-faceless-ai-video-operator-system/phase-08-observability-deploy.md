# Phase 08 — Observability + Deploy

## Context Links
- Overview: [plan.md](plan.md) · Prev: [phase-07](phase-07-ai-operator-scheduler-analytics.md)

## Overview
- **Priority:** P1 (P0 chạy local trên Mac M1 Max được; always-on là để scale)
- **Status:** pending
- **Description:** Logging/alerting, dashboard nhẹ (trạng thái pipeline + metrics), deploy always-on, quản lý secrets/cron, backup DB.

## Key Insights
- **P0 chạy trên Mac M1 Max local** (render SDXL + libx264 tại chỗ, free). Deploy cloud chỉ khi cần always-on 24/7 hoặc render nặng — nhưng cloud CPU render chậm/đắt; **có thể giữ render trên Mac, chỉ deploy bot+scheduler+publisher lên VPS nhẹ** (kiến trúc tách).
- **Alert kênh có sẵn: Telegram** (đã có bot) → gửi cảnh báo lỗi/quota vào cùng chat. Không cần Sentry/Grafana ở P0/P1 (YAGNI).
- **Backup SQLite**: copy file + WAL checkpoint định kỳ (cron) → cloud storage (R2). Nhỏ, rẻ.
- **Secrets trên VPS**: env vars / `.env` mode 600, không commit. systemd EnvironmentFile hoặc Fly secrets.

## Requirements
Functional:
1. `alerting`: gửi Telegram message khi step `failed`, quota <2000, quota exceeded, token refresh fail, ElevenLabs quota >80%.
2. `dashboard`: xem nhanh trạng thái — số video mỗi state, upload tuần này, quota còn, lỗi gần nhất. P0: CLI `operator status` (bảng text). P1: trang web nhẹ (FastAPI + 1 template) đọc DB.
3. `deploy`: process manager giữ scheduler + bot always-on; restart on crash.
4. `backup`: cron copy DB → R2 hàng ngày.
Non-functional: minimal deps; log rotate; secrets an toàn; file <200 dòng.

## Architecture — deploy topology (đề xuất tách)
```
[ Mac M1 Max — render node (P0/P1) ]        [ VPS nhẹ / Fly.io — always-on (P1) ]
 SDXL + FFmpeg + MoviePy render            telegram bot (polling) + APScheduler
 (chạy khi có job media/assemble)          + youtube publisher + analytics
        │ output/*.mp4 ─► R2 host ─────────────► review_notifier gửi preview
 SQLite (chung? → P1 chuyển Postgres để 2 node chia sẻ an toàn)
```
P0 đơn giản nhất: **tất cả chạy trên Mac** (foreground/launchd), 1 DB SQLite. P1 tách + Postgres nếu cần 24/7.

## Related Code Files
- Create: `src/ai_operator/obs/alerting.py` (Telegram alert helper — DRY reuse bot), `src/ai_operator/obs/dashboard_cli.py` (status table), `src/ai_operator/obs/dashboard_web.py` (P1 FastAPI, optional), `src/ai_operator/obs/backup_db.py` (WAL checkpoint + copy R2), `deploy/operator.service` (systemd) + `deploy/fly.toml` (nếu Fly) + `deploy/README-deploy.md`, `deploy/com.operator.scheduler.plist` (launchd cho Mac P0).
- Modify: `cli.py` (`status`, `backup`), `logging_setup.py` (rotate + level từ env).
- Delete: none.

## Implementation Steps
1. `alerting.py`: `alert(msg, level)` → `bot.send_message(TELEGRAM_CHAT_ID, f"⚠️ {level}: {msg}")`. Gọi từ pipeline_runner except blocks, quota_throttle, token_keepalive.
2. `dashboard_cli.py`: `status()` query DB → in bảng (rich/tabulate): counts per state, uploads 7 ngày, quota remaining, last 5 errors từ log.
3. `backup_db.py`: `PRAGMA wal_checkpoint(TRUNCATE)` → copy `data/operator.db` → R2 với timestamp; giữ 7 bản gần nhất. Cron/APScheduler daily.
4. Deploy P0 (Mac): `launchd` plist chạy `operator run-operator` + `operator run-bot` on login, KeepAlive=true (restart on crash). Hoặc đơn giản `tmux`/foreground khi validate.
5. Deploy P1 (VPS/Fly): `operator.service` systemd (Restart=always, EnvironmentFile=/etc/operator.env mode600) hoặc `fly.toml` (secrets qua `fly secrets set`). Render vẫn có thể ở Mac (push job qua DB) hoặc dùng GPU host nếu scale.
6. `dashboard_web.py` (P1 optional): FastAPI `/` render 1 template HTML đọc DB (read-only), bảo vệ bằng token query param.
7. `cli.py`: `operator status`, `operator backup`.
8. Test: kill scheduler → process manager restart; trigger 1 lỗi giả → nhận Telegram alert; chạy backup → verify file trên R2.

## Todo List
- [ ] alerting.py (Telegram) nối vào except/quota/token
- [ ] dashboard_cli status table
- [ ] backup_db (WAL checkpoint + R2, giữ 7 bản)
- [ ] launchd plist (Mac P0) restart-on-crash
- [ ] systemd/fly config (P1) + EnvironmentFile 600
- [ ] logging rotate + level từ env
- [ ] cli status/backup; test restart + alert + backup
- [ ] (P1 optional) dashboard_web FastAPI read-only

## Success Criteria
- Lỗi pipeline / quota thấp → nhận Telegram alert trong <1 phút.
- `operator status` in đúng counts + quota + lỗi gần nhất.
- Process crash → tự restart (launchd/systemd) không mất job (APScheduler jobstore persist).
- Backup DB xuất hiện trên R2 hàng ngày, restore thử được.

## Risk Assessment
| Risk | L | I | Mitigation |
|---|---|---|---|
| Mac ngủ/tắt → không always-on | Med | Med | `caffeinate` / Energy settings; hoặc deploy bot+scheduler lên VPS P1. |
| Cloud CPU render chậm/đắt | Med | Med | Giữ render trên Mac (local free); cloud chỉ bot/scheduler/publisher. |
| SQLite 2 node cùng ghi | Med | High | P0 single node; P1 tách thì chuyển Postgres. |
| Mất DB không backup | Low | High | Daily backup R2 + WAL checkpoint. |
| Secrets lộ trên VPS | Low | High | EnvironmentFile 600 / fly secrets; không commit. |

## Security Considerations
- `.env`/EnvironmentFile mode 600; secrets qua secret manager (fly secrets). Không log giá trị.
- Dashboard web (nếu bật) read-only + token; không expose ghi.
- Backup R2 bucket private; presigned khi cần.

## Next Steps
→ Phase 09 chạy validate thật (10-20 video/2-3 tháng) trên hạ tầng này, thu metrics.

## Unresolved Questions
- Deploy target cuối: Mac always-on (`caffeinate`+launchd) vs Fly.io vs Hetzner? — đề xuất P0: Mac local; P1: tách bot/scheduler lên Fly.io (~$5-10/mo), render giữ Mac.
- Cần Postgres khi nào? — chỉ khi tách 2 node (P1). P0 SQLite đủ.
