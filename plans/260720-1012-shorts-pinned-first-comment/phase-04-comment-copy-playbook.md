# Phase 04 — Comment copy playbook

**Priority:** P0 (không có code, nhưng quyết định feature sống hay chết) | **Status:** ⬜

Đọc file này **trước khi** viết comment đầu tiên. Không có code trong phase này.

## Nguyên tắc gốc

Comment ghim **không phải** chỗ nhắc lại curiosity question. `build_short_description`
(`metadata_builder.py:93-95`) đã đặt nguyên văn câu đó làm dòng đầu description — nằm
cách comment vài pixel. Lặp lại nó là tự làm loãng.

Việc của comment ghim là thứ khác hẳn: **mở một tranh cãi mà người xem có thể tham gia
ngay, nhưng không kết thúc được nếu chưa xem video dài.**

## Hình dạng chuẩn — CONTESTED CALL

Năm nhịp, viết liền thành 2 đoạn:

1. **Neo sự thật** — số người chết, bối cảnh, ngày. Câu tường thuật phẳng, không kịch tính.
2. **2-3 sự thật cẩu thả đã được kiểm chứng**, kể phẳng, không bình luận. Đây là nhiên liệu.
3. **Một quyết định đến giờ vẫn còn cãi nhau** — không phải "ai có lỗi", mà một lựa chọn
   cụ thể trong khoảnh khắc cụ thể.
4. **Lời tự bào chữa có ghi chép của chính người đó.** Đây là mảnh quan trọng nhất: nó
   cho người phản đối một thứ cụ thể để đập, và đó mới là cái sinh ra reply-của-reply.
5. **Câu hỏi "bạn có tin không"** + một dòng khép lại giữ nguyên phần chưa tiết lộ.

## Cơ chế thật sự tạo bình luận dài

**Mỗi prompt phải ép một mệnh đề "vì..." nằm trong cùng câu hỏi**, để trả lời một từ
đọc lên thấy cụt. Đây là phần duy nhất trong toàn bộ research sống sót qua vòng phản
biện — mọi con số "câu hỏi tăng X% comment" đều là tương quan, không phải nhân quả,
và không nghiên cứu nào tách được vị trí câu hỏi trong timeline.

Nói cách khác: đừng tin vào "đặt câu hỏi thì có comment". Tin vào "đưa một lập trường
có thể đánh bại được, kèm sẵn lý lẽ của phía bên kia".

## Cấm tuyệt đối

| Cấm | Vì sao |
|---|---|
| "What do you think?" / "Thoughts?" | Mời trả lời một từ, không thêm thông tin nào |
| "Drop a 🚢 if…" / "Like this if…" / "Tag someone" | Engagement bait kinh điển, người đọc nhận ra là bot ngay |
| Menu A/B/C/D | Định dạng dễ sinh reply một chữ cái nhất trên YouTube |
| Nhiều hơn **một** dấu `?` | Câu hỏi chồng câu hỏi làm loãng; giữ đúng một |
| Template có slot dùng lại giữa các video | Spam policy cấm "repetitive comments"; và người xem thấy ngay |
| Đuôi CTA cố định ("Sub for more…") | Biến comment thành quảng cáo, đây là artifact rủi ro cao nhất |
| Nêu đích danh cá nhân trong phần chưa tiết lộ | Làm lộ `protected_reveal`, giết funnel |
| Link ngoài | Trông như spam, và description đã có link video dài |

## Vùng an toàn cho lập trường

Video là thảm hoạ có người chết thật. Ranh giới:

- **Được** tranh cãi về: một **quyết định** có ghi chép, mức độ nghiêm trọng so với các
  vụ khác, chuyện tương tự có xảy ra hôm nay không, lẽ ra phải làm gì khác.
- **Không** tranh cãi về: nạn nhân, giá trị mạng người, chi tiết chết chóc, thuyết âm mưu.
- Lập trường phải nằm **kế bên** phần chưa tiết lộ, không nằm **trên** nó. Với phim tài
  liệu lịch sử, "ai chịu trách nhiệm / hoá ra là gì" thường CHÍNH LÀ payoff — đưa nó vào
  comment là tự phá.

## Năm khuôn — ví dụ viết sẵn bằng TIẾNG ANH

**Kênh nói tiếng Anh cho khán giả Mỹ.** Copy dưới đây là bản ship được, không phải bản
dịch ý. Phần giải thích để tiếng Việt cho operator; phần trong khung là thứ dán lên YouTube.

### 1. Contested call (mặc định — dùng khuôn này trước)

> 1,021 people died on a church picnic boat in the middle of New York City on June 15, 1904.
> The life preservers had been hanging in their racks since the ship was launched in 1891,
> and an inspector had signed off on them five weeks earlier. The company had not run a
> single fire drill that year. And when the fire started, the captain called for more speed
> instead of putting her on the Bronx shore.
>
> That last one is the part nobody has ever settled. He testified that beaching there would
> have set the lumber yards and oil tanks alight and killed people on land too. Tell me
> whether you buy that, and what makes you land where you do — I keep going back and forth
> on it. What the courts decided, and what happened to him ten years later, is in the full
> video.

**Đếm: 118 từ, một dấu `?`… thực ra là KHÔNG có dấu `?`** — "Tell me whether you buy that"
là mệnh lệnh thức, mạnh hơn câu hỏi và vẫn ép mệnh đề "vì". Quy tắc "tối đa một `?`" là
trần, không phải sàn.

Vì sao nó chạy: không trả lời được bằng một từ; bất đồng là bất đồng lịch sử có thật;
lý lẽ phía bên kia nạp sẵn để người ta đập; **không một tên riêng nào xuất hiện** nên
"ai đi tù" còn nguyên trong video dài.

### 2. Standard-read inversion

Nêu cách hiểu phổ thông, nói bạn cho là ngược, kèm chi tiết có nguồn. Đặt tên cho **phe
đối lập cụ thể** thay vì "tell me I'm wrong" — cho người ta một làn để viết cả đoạn.

> Everyone files this one under "freak weather." I think that reading is backwards: the
> barometer readings were on the wire eleven hours before she sailed, and someone chose to
> sail anyway. If you're in the weather camp, come at that eleven hours specifically —
> that's the part I can't get around.

### 3. Threshold / so sánh mức độ

Buộc người đọc xếp hạng vụ này so với một vụ họ đã biết, kèm tiêu chí của chính họ.

> More people died here than in [well-known disaster], in a major city, in broad daylight —
> and almost nobody has heard of it. I've got a theory about what decides whether a disaster
> stays in public memory, but I want yours first: name the factor you think matters most,
> and where it puts this one.

### 4. "Could it happen today"

Chuyển tranh cãi sang hiện tại. **Không tự động an toàn về spoiler** — nếu payoff của video
CHÍNH LÀ "quy định nào ra đời sau vụ này", thì khuôn này làm lộ. Kiểm tra `protected_reveal`
của short trước khi dùng; nếu reveal nằm ở phần hậu quả pháp lý, chuyển sang khuôn 1 hoặc 3.

> [Specific systemic failure] is what turned this from an accident into a body count. The
> rules that came afterward closed that exact gap. But if you work in this world — marine,
> inspection, safety of any kind — tell me whether you've seen the modern version of it
> where you are, and what keeps it alive.

### 5. Local knowledge

Kéo người có liên hệ cá nhân vào. Sinh comment dài nhất, nhưng chỉ dùng khi vụ việc có địa
danh rõ và cộng đồng còn sống.

> This happened at [place]. If you grew up there: was it taught in school, or is it just a
> plaque nobody stops to read — I want to know which version of the story got handed down,
> because the one in the records and the one people tell are not the same.

## Kiểm tra trước khi lưu

1. Đọc lại `protected_reveal` của short — copy có chạm vào nó không?
2. Có tên riêng nào không? Nếu có, nó có phải phần payoff không?
3. Câu hỏi/mệnh lệnh có ép được mệnh đề "vì" không, hay trả lời một từ được?
4. Đếm dấu `?` — tối đa một.
5. Có trùng dòng đầu description (`curiosity_question`) không?
6. 70-160 từ.

## Nhịp dùng khuôn

Đừng dùng khuôn 1 cho cả 3 short của cùng một video — người xem lướt cả batch. Một video
mẹ → 3 short → dùng 3 khuôn khác nhau. Xoay vòng theo tuần, và **luôn viết lại từ đầu**,
không điền vào chỗ trống.

## Độ dài

70–160 từ. Ngắn hơn thì không đủ nhiên liệu tranh cãi; dài hơn thì trên mobile bị cắt
sau "Read more" và mất đúng phần câu hỏi.

## Điều chưa giải quyết

- Lập trường nên gắt tới đâu: nhận định về một vụ tắc trách lịch sử sẽ kéo reply thù
  địch, mà kênh chỉ có một người và không có tự động kiểm duyệt. Bắt đầu ở mức ôn hoà,
  tăng dần nếu thấy chịu được.
- Chưa có cách nào trong repo để biết khuôn nào chạy tốt hơn cho tới khi phase 05 xong.
