# Session 2026-07-21 — sửa đường hình ảnh + chuỗi provider

**Branch:** `feat/ops-observability-validation` · **561 tests pass** · 6 commit chưa push (13 commit trong ngày)

---

## Việc lớn nhất: đường archival đã CHẾT, không ai biết

`stock_clients.py` ghép URL preview bằng `full.replace("/1920px-", "/480px-")`. **480 không phải width Wikimedia render** — đo trên file thật:

```
480px → HTTP 400     ← code đang dùng
500px → HTTP 200
640px → HTTP 400
1920px → HTTP 200
```

~60% ứng viên có `/1920px-` trong URL → preview thành URL chết. Chuỗi hậu quả:

1. `_download_thumb` → None → **CLIP rerank thành no-op câm** (chỉ `log.debug`)
2. Sàn khớp-beat (`3ac7c4e`, sáng cùng ngày) không có ảnh để nhìn → `continue` hết vòng → **archival MISS mọi beat**

**Commit `3ac7c4e` biến suy giảm âm thầm thành mất trắng cả tier.** Bằng chứng: log #39 có 10/10 `archival MISS` mà không một dòng `archival beat-match` — hàm chấm chưa từng chạy với dữ liệu thật.

Test đang **khoá lỗi lại**: `assert "/480px-" in out[0]["thumb"]`.

Suốt buổi tối đổ lỗi cho anchor `"Star Dust"`. Anchor có vấn đề thật nhưng **không phải nguyên nhân chính**. Chỉ lộ ra nhờ audit 72 agent.

---

## Đã sửa (theo thứ tự thời gian)

| Commit | Nội dung |
|---|---|
| `90c0fa2` | Gate thumbnail thoát bẫy quota 5 req/phút → `GEMINI_VISION_MODEL=gemini-3.1-flash-lite` + retry + alert nửa pool |
| `3ac7c4e` | Sàn khớp-beat cho tier archival (đo: 16/18 ảnh minh hoạ sai chuyện) |
| `156ade6` | Ledger: giải phóng đặt-chỗ khi Gemini lỗi (16 dòng ma $0.80) + tên provider phục vụ |
| `4da2044` | Phân xử hoà thumbnail theo ảnh tư liệu thời kỳ (giấy phép PD) |
| `3c90f78` | Gate hỏi **thời điểm chụp** thay vì nội dung — 13/13 vs 12/13 |
| `e18c4d7` | Bỏ hẳn watermark AI (là code dự án, không phải fal) |
| `c71a339` | `narration_span` cho `ShortBeat` + neo niên đại |
| `8e340c6` | Neo niên đại bằng **mệnh đề tính từ** — bản trước liệt kê danh từ nên model vẽ xe hơi vào giữa Andes |
| `e22bd58` | **Sửa preview URL** + tách "tải hỏng" khỏi "chấm trượt" + fail-open không trả ảnh vừa bị loại + nấc `anchor + era` |
| `0fd392c` | Loại đồ lưu niệm ở sàn beat + **alert khi provider chết / gate mù** + mốc beat đơn điệu |
| `135c4a6` | **Provider `claude_cli`** — subscription đỡ khi cả hai đường API chết |

---

## Chuỗi provider hiện tại

```
thinking: anthropic → claude_cli → gateway → gemini
rẻ:       gateway → gemini
```

`claude_cli` chạy headless Claude Code CLI. Đo trước khi code:
- system prompt 16.333 ký tự → script 1.268 từ, `shot_list` 13 beat, **JSON hợp lệ, không cắt**
- `maxOutputTokens: 64000` (gấp 4 sàn 16k của API)
- model thật: **`claude-opus-4-8`** (model tự nhận "Sonnet 4.5" — SAI, đừng tin model tự khai)
- 101–171s/call vs 20–30s API

**Hai chi tiết sống còn:** gỡ `ANTHROPIC_API_KEY` khỏi env con (CLI ưu tiên key hơn phiên đăng nhập → key hỏng làm nó chết thay vì dùng subscription); đóng stdin (nếu không phí 3s/call).

### ⚠️ Chi phí ẩn chưa giải quyết

Mỗi call nạp **~34.600 token cache creation** dù đã truyền `--system-prompt`. ~4 call thinking/video = ~140k token/video chỉ để khởi động.

Trên subscription không mất tiền, **nhưng ăn chung hạn mức với phiên tương tác của operator**. Pipeline chạy nền có thể làm operator bị chặn khi đang làm việc.

**Đề xuất chưa được duyệt:** đổi `CLAUDE_CLI_ENABLED` mặc định sang `False`, bật tay khi cần.

---

## Cảnh báo mới (user yêu cầu "báo dùm")

- **Provider tụt hạng** ở bước `thinking` → alert kèm lý do, dedupe theo tiến trình
- **Gate beat mù** (≥nửa số beat không chấm được) → alert, mirror luật gate thumbnail

Đã tự bắt đúng sự cố thật: `anthropic: credit balance too low` + `gateway: Connection error`.

**⚠️ `TELEGRAM_BOT_TOKEN` đang THIẾU** → mọi alert chỉ vào `data/scheduler.log`, không tới tay operator.

---

## Đo xong, kết luận ĐỪNG làm

**Mở tier stock cho beat `illustration`.** Pexels + Pixabay cộng lại: **0/20 ảnh dùng được**. Năm ảnh "qua sàn" là cờ Mỹ trong toà Canada 1917, cầu Istanbul đóng vai eo Halifax, bàn ghế sân vườn đóng vai thành phố bị san phẳng. Quyết định khoá Pixabay của operator là đúng; Pexels không cứu được.

**Tier định danh regex** (`[A-Z]{1,2}-[A-Z]{3,4}` → `G-AGWH`). Độ phủ 1/35 video, và nấc `anchor + era` lấy đúng tấm ảnh đó rẻ hơn. Bẫy: mã license `CC BY-SA`, `PD-US` cũng khớp regex.

---

## Trạng thái video

| | span | ảnh | ghi chú |
|---|---|---|---|
| **#39** | 10/10 | 1 archival (**G-AGWH 'Stardust'** — ảnh thật đầu tiên) + 9 AI | xong |
| **#40** | **0/6** | 6 AI đúng niên đại | **ảnh vẫn trôi khỏi lời kể** |
| **#41** | **0/6** | 6 AI đúng niên đại | như trên |

Short cần `gen-shorts --force` để có `narration_span` — nó **thay** #40/#41 bằng hai short mới.

---

## Còn treo

1. **`_BAND_H = 600` cứng** → headline đè mép ảnh khi zoom tối đa. Audit ghi "sẽ leo hạng ngay" vì ảnh archival gần vuông giờ mới xuất hiện.
2. **Nút `--force` cho panel video chính** — hiện phải chạy script tay; panel bấm là no-op im lặng (checkpoint).
3. **Video chính re-gen không tự prune row asset** (đường short có) — video 3 đã dính row trùng.
4. **`narration_span` vào `shot_list` của short** (`shorts_runner.py:272`).
5. Dọn 5 docstring lỗi thời.
6. **Câu hỏi mở:** `500px` có phải bucket ổn định trên MỌI file Commons không? Đo được API tự snap 480→500 trên 4 file, nhưng chưa xác minh tập bucket đầy đủ.

---

## Bài học phương pháp

**Bốn lần trong ngày tôi đưa ra chỉ số rồi phải tự bác bỏ khi nhìn ảnh:** điểm relevance, điểm niên đại, điểm khớp lời kể, và điểm stock. Mỗi lần đều là "số nói A, mắt nói B, mắt đúng".

**Ba lần tự gây lỗi rồi phải sửa lại:** gate chặn ảnh sai nhưng preview chết nên gate mù; prompt niên đại liệt kê danh từ nên đẻ ra xe hơi; commit sáng biến suy giảm thành mất trắng tier.

Quy tắc rút ra: **chấm điểm không thay được việc nhìn ảnh ghép cuối ở đúng kích thước hiển thị.**

---

## Chưa giải quyết

- `CLAUDE_CLI_ENABLED` nên mặc định `False`? (chờ operator quyết)
- Điều khoản dùng subscription làm backend sản xuất tự động
- `TELEGRAM_BOT_TOKEN` thiếu → alert không tới tay
- Chưa push (6 commit)
