---
title: "Cải tiến từ verify — AI-Operator faceless YouTube (P0)"
description: "Tổng hợp verdict + cải tiến sau red-team/verify pass ngày 2026-07-08"
date: 2026-07-08
source: verify pass
---

# Cải tiến từ verify (260708)

## Verdict tổng thể
**Plan nền vững.** Kiến trúc pipeline module-hoá + state machine + review gate là hướng đúng cho bài toán faceless bán tự động. Không cần đại tu; chỉ bổ sung/siết một số điểm để chống rủi ro policy YouTube và tránh over-engineering. 3 vấn đề CRITICAL bên dưới **phải xử lý** trước khi chạy validate; ~13 mục P0 nên đưa vào các phase tương ứng; 10 mục DEFER-P1; 10 mục REJECTED vì over-engineering.

---

## 3 vấn đề CRITICAL (bắt buộc xử lý)

| # | Vấn đề | Rủi ro nếu bỏ qua | Xử lý ở phase |
|---|---|---|---|
| C1 | **Nhãn AI đã có sẵn** — bật `containsSyntheticMedia=true` khi upload + disclosure trong mô tả | YouTube gỡ/hạ reach video AI không khai báo → strike policy | 01 (config mặc định), 06 (upload flag) |
| C2 | **Review 2-tầng** — người duyệt xem cả script (trước render) và video final (trước publish), không chỉ 1 cổng | Lỗi nội dung lọt tới final → tốn công render lại / publish nhầm | 05 (bot 2 bước approve) |
| C3 | **Analytics thresholds cụ thể** — số hoá kill/pass (view, retention%, CTR) thay vì mô tả chung | Không có mốc rõ → không biết khi nào kill/scale, trôi chi phí | 07 (đọc metric), 09 (kill-criteria) |

---

## ~13 cải tiến P0 (map theo phase)

| # | Cải tiến | Phase |
|---|---|---|
| P0-1 | Config bật sẵn `containsSyntheticMedia=true` + template disclosure trong description | 01 |
| P0-2 | State machine thêm trạng thái `rejected` + đường quay lại `draft`/`scripted` (rework loop) | 01 |
| P0-3 | Lưu `idempotency key` mỗi video để retry upload không tạo trùng | 01 / 06 |
| P0-4 | Script engine: kiểm tra độ dài/đọc ước lượng khớp target 8–15' trước khi render | 02 |
| P0-5 | Originality layer: chèn góc nhìn/nguồn riêng, tránh copy nguyên văn Wikipedia | 02 |
| P0-6 | TTS: cache audio theo hash script để không tốn quota ElevenLabs khi re-run | 03 |
| P0-7 | Visual: fallback stock (Pexels/Pixabay) khi SDXL local fail, giữ pipeline không đứng | 03 |
| P0-8 | Assembler: chuẩn hoá loudness (-14 LUFS) + safe-area caption cho mobile | 04 |
| P0-9 | Review gate: 2 bước (script → video) + nút Reject kèm lý do ghi vào DB | 05 |
| P0-10 | Publisher: bật `containsSyntheticMedia`, set `madeForKids=false`, retry/backoff quota | 06 |
| P0-11 | Publisher: dry-run/private-first upload để verify trước khi public | 06 |
| P0-12 | Operator/analytics: pull view+retention+CTR qua YouTube Analytics API, ghi bảng metric | 07 |
| P0-13 | Kill-criteria số hoá: view TB, retention%, CTR, cửa sổ 20 video/3 tháng, 0 strike | 09 |

---

## 10 mục DEFER-P1 (hoãn, không làm ở P0)

| # | Mục | Lý do hoãn |
|---|---|---|
| D1 | Always-on scheduler 24/7 (Fly.io/Hetzner) | P0 chạy tay/bán-tay là đủ để validate |
| D2 | A/B test thumbnail tự động | Cần volume dữ liệu lớn, chưa có ở P0 |
| D3 | Auto-optimize SEO theo feedback loop | Thu thập metric trước, tối ưu sau |
| D4 | Multi-voice / voice cloning nâng cao | 1 giọng ổn định đủ cho validate |
| D5 | Shorts funnel | Ngoài scope P0, thuộc P2 |
| D6 | i18n / clone sang Spanish | P2 |
| D7 | Dashboard observability đầy đủ (Grafana) | Log file + bảng metric đủ ở P0 |
| D8 | Music generation / licensed music pipeline | Dùng track royalty-free tĩnh trước |
| D9 | Auto comment/community engagement | Rủi ro policy, chưa cần |
| D10 | Multi-channel orchestration | 1 kênh trước, chứng minh mô hình |

---

## 10 mục REJECTED (over-engineering — không làm)

| # | Mục bị loại | Lý do |
|---|---|---|
| R1 | Microservices / message queue (Kafka/RabbitMQ) | 1 process Python + SQLite/state file là đủ; KISS |
| R2 | Kubernetes / container orchestration | 1 máy M1 Max, không cần scale ngang |
| R3 | Web UI admin panel tự build | Telegram bot đã là review gate; YAGNI |
| R4 | ML model tự train dự đoán viral | Không đủ data, ROI âm; dùng heuristic |
| R5 | Multi-cloud abstraction layer | Chưa deploy cloud ở P0; tránh trừu tượng sớm |
| R6 | Plugin system / abstract provider framework cho TTS/visual | 1–2 provider hard-wire + fallback là đủ; DRY vừa phải |
| R7 | Real-time streaming render pipeline | Batch render đủ cho long-form |
| R8 | GraphQL API nội bộ | Không có client ngoài; gọi hàm trực tiếp |
| R9 | Distributed job queue (Celery + Redis) | Tuần ≤3 video, chạy tuần tự là đủ |
| R10 | Auto-scaling GPU cloud cho SDXL | Local SDXL trên M1 Max đã viable, cloud là chi phí thừa |

---

## Unresolved questions
- Ngưỡng CTR cụ thể để pass (đề xuất mốc ~4–6%, cần user chốt).
- Nguồn music licensed cuối cùng (đang để royalty-free tĩnh).
- Số bước review tối thiểu nếu user muốn giảm tải (2-tầng vs gộp 1).
