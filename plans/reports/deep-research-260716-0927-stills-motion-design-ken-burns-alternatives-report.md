# Motion Design cho video tư liệu từ ảnh tĩnh — Fix "mất hình / không thấy hết ảnh"

Date: 2026-07-16 | Nguồn: deep-research workflow (18 nguồn, 83 claims, 9 confirmed) + 2 WebSearch bổ sung + đọc code pipeline

## TL;DR

Cảm giác "zoom lớn chạy ngang mất hình" đến từ **3 lỗi cộng dồn**, trong đó lỗi nặng nhất KHÔNG phải zoom mà là **beat quá dài**: video #28 = 454s / 12 beat ≈ **38s/beat**, trong khi editor tài liệu chuyên nghiệp giữ 1 ảnh tĩnh chỉ **3-5s**. Một chuyển động Ken Burns kéo suốt 38s tất yếu trôi cửa sổ nhìn rất xa khỏi điểm gốc → chủ thể ra khỏi khung.

Fix theo thứ tự tác động/chi phí: (1) giảm zoom 1.28→1.10 + đảo pattern "mở rộng trước, đẩy vào sau" — chỉ chỉnh tham số; (2) cắt beat dài thành sub-shot 5-6s từ nhiều khung cắt của CÙNG một ảnh — sửa cấu trúc, đây mới là fix thật; (3) giữ hard cut; (4) BỎ 2.5D parallax.

## Gốc rễ (xác định từ code + research)

| # | Vấn đề | Bằng chứng | Mức |
|---|--------|-----------|-----|
| 1 | **Beat ~38s** — `beat_timing._reconcile` scale tỷ lệ mọi beat, phá vỡ clamp shot-type (1-6s). 12 ảnh phải phủ 454s | `beat_timing.py:62-83`; clamp `establishing (4,6) / detail (2,3) / montage (1,2)` bị nhân ~6-9× | **Cao nhất** |
| 2 | Zoom 1.28 quá mạnh | Editor tài liệu thực chiến: chuẩn **+10% (1.0→1.10)**, KHÔNG phải 1.3 (confirmed 3-0, gboy/Medium) | Cao |
| 3 | Pan giữ zoom cố định → cửa sổ nhìn luôn < ảnh | Pan ở zoom 1.28 chỉ thấy ~78% phần đã cover-crop | Cao |
| 4 | Neo tâm (đã fix một phần) | "dead center hiếm khi là nội dung chính" → zoom tâm trôi khỏi chủ thể (confirmed 2-0) | Trung bình |

## Số liệu chuẩn ngành (đã verify / nguồn uy tín)

- **Zoom amplitude**: +10% mỗi shot (1.0→1.10) là baseline editor thực chiến — **confirmed 3-0**. Canonical ffmpeg tutorial: 20% (1.0→1.2) qua 4s (mko.re, unverified do session limit nhưng nguồn kỹ thuật rõ).
- **Thời lượng giữ ảnh tĩnh**: **3-5s** cho ảnh thuần, tối thiểu 3-4s để mắt kịp đăng ký (yttalk). Making a Murderer trailer: 12 ảnh/30s ≈ **2.5s/ảnh**, 7/12 có motion (Shutterstock).
- **Pattern giữ trọn bố cục** (premiumbeat, confirmed practice): **tạo nhiều shot từ MỘT ảnh bằng cách cắt khung khác nhau** — wide establishing → cut → detail crop. Đây chính là cách documentary cho người xem thấy hết ảnh mà vẫn có nhịp.
- **Chuyển động phải chậm, có chủ đích**; xong quá nhanh đọc thành giật (backstage).

## Khuyến nghị xếp hạng

### A. Chỉ chỉnh tham số (làm ngay, rủi ro thấp) — `kenburns_ffmpeg.py`

1. **Giảm zoom target**: main `TARGET_ZOOM` 1.28 → **1.10**; shorts `TARGET_ZOOM_PORTRAIT` 1.38 → **1.18** (phone cần mạnh hơn chút vì màn nhỏ, nhưng không tới 1.38).
2. **Pattern "reveal-first"**: `zoom_in` để frame ĐẦU hiện **toàn bộ** ảnh cover-crop (zoom 1.0), rồi đẩy vào chậm → người xem luôn thấy trọn bố cục ở giây đầu. Đây là fix trực tiếp cho "không thấy hết hình".
3. **Giảm biên độ pan**: ở zoom 1.10 vùng ẩn chỉ ~9% → pan gần như tĩnh, tự khắc hết "chạy ngang mất hình". Cân nhắc bỏ hẳn 2 variant `pan_lr/pan_rl`, giữ zoom_in/zoom_out biên độ nhỏ.

→ Ước tính: xử lý ~80% cảm giác khó chịu. Không đổi cấu trúc, chỉ sửa hằng số + biểu thức.

### B. Cắt sub-shot (sửa cấu trúc — fix THẬT cho beat dài)

Beat 30-38s là bất thường; ngành cắt 3-5s. Hai hướng:

- **B1 (rẻ, khuyến nghị)**: giữ 12 ảnh/video, nhưng render mỗi beat dài thành **N sub-shot 5-6s**, mỗi sub-shot một khung cắt khác của cùng ảnh (wide → detail → khác góc). Không tốn thêm chi phí sinh ảnh. Cần: sửa `beat_timing`/`segment_builder` để 1 ảnh → nhiều segment; mỗi segment một crop-box khác nhau.
- **B2 (đắt)**: tăng số ảnh sinh 12 → 30-40/video để mỗi ảnh chỉ phủ ~10s. Tốn SDXL + archival fetch, chậm hơn nhiều. YAGNI trừ khi B1 chưa đủ.

→ B1 mới thật sự giải quyết "never see whole image": người xem thấy toàn ảnh ở sub-shot wide, rồi được dẫn tới chi tiết — thay vì một cú trôi 38s.

### C. Chuyển cảnh — GIỮ hard cut (đừng đổi)

- **concat demuxer = stream-copy, gần như miễn phí, không mất chất** (xác nhận nhiều nguồn). Pipeline đang dùng đúng.
- **xfade crossfade = phải RE-ENCODE toàn bộ segment nối** (không stream-copy được) — đắt, và documentary lịch sử phần lớn **hard-cut** chứ không crossfade từng cảnh.
- Nếu muốn điểm nhấn: chỉ **dip-to-black ngắn ở ranh giới ACT/chapter** (không phải mọi cut). Chi phí re-encode chấp nhận được vì hiếm. Optional, không ưu tiên.

### D. 2.5D parallax — BỎ trên free CPU stack (verify chắc)

- **DepthFlow**: renderer là **GLSL shader chạy GPU**, không phải ffmpeg filter; số liệu 8K50fps giả định RTX 3060 (confirmed 3-0).
- **3d-ken-burns (Adobe)**: cần **CUDA/CuPy** (GPU NVIDIA) + license **CC BY-NC-SA phi thương mại** → loại cho kênh kiếm tiền (confirmed 3-0).
- **depth-anything.cpp**: sinh được depth map trên CPU (~350ms/ảnh, confirmed 3-0) — NHƯNG không có renderer parallax CPU-only bằng ffmpeg để tiêu thụ depth map đó. Nửa giải pháp, vô dụng nếu không có nửa sau.

→ Kết luận: parallax thật không khả thi trên stack hiện tại. Pattern "reveal-first + sub-shot" (A+B) cho ~80% cảm giác chuyên nghiệp với 0 chi phí GPU.

## Bộ tham số đề xuất cụ thể

**16:9 main** (nguồn hỗn hợp aspect):
- zoom target 1.08-1.12 (mặc định **1.10**); frame đầu = full ảnh cover-crop
- sub-shot **5-6s**/cảnh; beat >12s cắt thành 2-3 sub-shot khác crop
- pan: bỏ hoặc ≤3% dịch chuyển; hard cut giữa cảnh

**9:16 shorts** (blurred-pad portrait, beat 5-8s):
- zoom target 1.15-1.20 (mặc định **1.18**)
- beat vốn ngắn (5-8s) → 1 move/beat là đủ, KHÔNG cần sub-shot
- giữ karaoke caption + hard cut hiện có

## Việc cần làm nếu triển khai

- Param-only (A): sửa `TARGET_ZOOM`, `TARGET_ZOOM_PORTRAIT`, pattern reveal-first, giảm/bỏ pan trong `kenburns_ffmpeg.py` — nửa buổi.
- Sub-shot (B1): sửa `beat_timing` + `segment_builder` để 1 ảnh → N segment crop khác nhau — ~1 ngày, cần test kỹ đồng bộ audio.

## Câu hỏi chưa chốt

1. B1 cắt sub-shot cần logic chọn crop-box (rule-based: wide→center→detail, hay theo saliency/face-detect?) — cần quyết trước khi làm.
2. Zoom 1.10 cho main có thể quá nhẹ trên TV lớn — nên render thử 1 video rồi mắt thường quyết 1.08 vs 1.12.
3. Có nên giữ archival grade khi zoom nhẹ hơn (ảnh ít motion → grain noise nổi hơn)?

## Nguồn chính

- https://gboy.medium.com/how-i-animate-archival-images-in-premiere-pro-1f7572896d4f (editor thực chiến, +10% zoom)
- https://www.premiumbeat.com/blog/documentary-tips-working-archival-footage/ (multiple shots from one photo)
- https://yttalk.com/threads/how-long-to-hold-a-still-image-or-scene.165875/ (hold 3-5s)
- https://mko.re/blog/ken-burns-ffmpeg/ (ffmpeg zoompan chuẩn + jitter/upscale)
- https://www.ffmpeg-micro.com/blog/ffmpeg-concat-merge-videos (concat demuxer vs xfade re-encode)
- https://github.com/BrokenSource/DepthFlow, https://github.com/sniklaus/3d-ken-burns, https://github.com/mudler/depth-anything.cpp (2.5D feasibility)
