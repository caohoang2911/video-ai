# Phase 04 — Video Assembler (MoviePy 2.x + FFmpeg + Whisper)

## Context Links
- Overview: [plan.md](plan.md) · Prev: [phase-03](phase-03-media-engine.md)
- Research brief: "Video Assembly Workflow MoviePy 2.x + FFmpeg + Whisper".

## Overview
- **Priority:** P0
- **Status:** pending
- **Description:** Ghép `narration.mp3` + ảnh (Ken Burns qua FFmpeg) + caption (faster-whisper timestamps) + nhạc nền (ducking) + intro/outro → export H.264 1080p MP4 sẵn preview/upload.

## Key Insights (từ brief)
- **Ken Burns pre-render bằng FFmpeg `zoompan`** (nhanh hơn nhiều MoviePy native) → xuất từng segment MP4 → nạp lại MoviePy để composite. Tránh MoviePy zoom (CPU-heavy).
- **faster-whisper** lấy timestamps segment-level (5-30s) → caption; word-level chỉ khi cần karaoke (KHÔNG cần P0 → segment-level nhanh hơn, tránh TextClip bottleneck).
- **Ducking:** MoviePy KHÔNG có native ducking → `CompositeAudioClip([narration, music.with_volume_scaled(0.15-0.3)])`. Music nhỏ dưới narration.
- **MoviePy 2.x breaking:** `.set_*` → `.with_*`; `.fx()` → `.with_effects([Effect(...)])`; import `from moviepy` KHÔNG `moviepy.editor`; ImageMagick bỏ (Pillow). **Pin Pillow 10.2.0**.
- **Export:** `write_videofile(codec='libx264', preset='fast', ffmpeg_params=['-crf','23','-pix_fmt','yuv420p'])`. **H.264 bắt buộc** (Telegram preview + YouTube). ~20-40' render CPU cho video 10' (M1 Max không có NVENC → CPU libx264; chấp nhận P0, cadence thấp).
- **Audio sync drift** trên video dài: composite 1-pass, tránh re-read clip nhiều lần, `clip.close()` sau dùng (memory leak).
- **Shot duration rules** (nhịp giữ retention): establishing shot 4-6s, detail/reaction 2-3s, montage 1-2s. Override map narration_span khi shot rơi ngoài khoảng theo type. Đồng bộ 3 lớp: narration tone (câu dài → shot dài) + nhịp nhạc (beat) + điểm cắt segment → cắt trên beat/nghỉ giọng, tránh cắt giữa từ.
- **Thumbnail** không phải bonus: quyết CTR YouTube. Sinh tự động 3 biến thể ngay lúc render (module riêng) để phase 06 A/B, không chờ upload. **Text overlay lấy từ `script.json.title_options[i].thumbnail_text`** (đã ghép cặp với title ở phase-02), KHÔNG tự bịa từ keyword → mỗi thumbnail_i khớp thông điệp title_i, tránh title×thumbnail lệch (giữ CTR). Fallback keyword nếu thiếu `thumbnail_text`.

## Requirements
Functional:
1. Ken Burns từng ảnh → segment MP4 dài = thời lượng beat (map narration_span → duration).
2. Concat segments = video nền khớp tổng thời lượng narration.
3. Caption burn-in segment-level từ Whisper.
4. Mix audio: narration + music ducked + (optional SFX).
5. Ghép intro/outro (branding tĩnh).
6. Export MP4 H.264 1080p → `output/<id>/final.mp4`; update `videos.state = rendered`, ghi `duration_sec`.
Non-functional: 1-pass composite; đóng clip; file <200 dòng (tách kenburns/caption/audio-mix riêng); yuv420p (tương thích mọi player).

## Architecture — pipeline
```
images[] + shot_list(durations) ─► kenburns_ffmpeg → seg_00.mp4..seg_N.mp4
                                        │ concatenate_videoclips (chain)
                                        ▼  base_video
narration.mp3 ─► faster-whisper → segments[{start,end,text}] ─► TextClip[] (segment-level)
music.mp3 ─────────────────────────────────┐
                                            ▼
CompositeVideoClip([base_video]+captions) .with_audio(CompositeAudioClip([narration, music*0.2]))
                                            │ + intro/outro concat
                                            ▼ write_videofile libx264 crf23
                                        final.mp4  → state=rendered
                                            │
final.mp4 ─► thumbnail_generator: 3 key-frame (scene cut/motion) ─► overlay text = script.json title_options[i].thumbnail_text (ghép cặp title_i×thumb_i) ─► tối ưu tương phản ─► thumb_a/b/c.jpg (→ phase 06 A/B)
```

## Related Code Files
- Create: `src/ai_operator/assembler/kenburns_ffmpeg.py` (subprocess FFmpeg zoompan), `src/ai_operator/assembler/caption_whisper.py` (faster-whisper → segments → TextClip list), `src/ai_operator/assembler/audio_mixer.py` (narration+music ducking), `src/ai_operator/assembler/video_builder.py` (orchestrate composite + export), `src/ai_operator/assembler/branding.py` (intro/outro clips), `src/ai_operator/assembler/thumbnail_generator.py` (3 key-frame → overlay `thumbnail_text` paired-title từ script.json → 3 biến thể, <200 dòng), `assets/branding/` (intro.mp4, outro.mp4, font).
- Modify: `cli.py` (`assemble --video-id X`).
- Delete: none.

## Implementation Steps
1. `kenburns_ffmpeg.py`: `render_segment(image_path, duration, out_path, zoom_dir)`: `ffmpeg -loop 1 -i img -vf "zoompan=z='min(zoom+0.0015,1.3)':d={duration*30}:s=1920x1080:fps=30" -c:v libx264 -t {duration} -r 30 -pix_fmt yuv420p out.mp4`. Alternate zoom in/out mỗi beat cho biến hoá. Duration mỗi beat = narration_span length / tổng * total_audio_len, sau đó **clamp theo shot_type**: establishing 4-6s, detail/reaction 2-3s, montage 1-2s. Ưu tiên cắt trên beat nhạc/nghỉ giọng gần nhất.
2. `caption_whisper.py`: `WhisperModel("base", device="cpu", compute_type="int8")`; `transcribe(mp3)` → segments; map → `TextClip(text, font_size=48, color='white', stroke_color='black', stroke_width=2, method='caption', size=(1600,None)).with_start(seg.start).with_end(seg.end).with_position(('center', 900))`. Segment-level (không word).
3. `audio_mixer.py`: `mix(narration_path, music_path)`: load AudioFileClip; `music = music.with_volume_scaled(0.2)` loop/trim tới len narration; `CompositeAudioClip([narration, music])`. Fade in/out music.
4. `branding.py`: load `intro.mp4`/`outro.mp4` (3-5s tĩnh, tạo 1 lần thủ công/Canva). `concatenate_videoclips([intro, body, outro])`.
5. `video_builder.py`: orchestrate: kenburns segments → `concatenate_videoclips(method='chain')` → `CompositeVideoClip([base]+captions)` → `.with_audio(mixed)` → intro/outro → `write_videofile('final.mp4', codec='libx264', preset='fast', ffmpeg_params=['-crf','23','-pix_fmt','yuv420p'], threads=8)`. `close()` mọi clip. Update DB state=rendered + duration_sec.
6. `thumbnail_generator.py`: `generate(final_mp4, thumbnail_texts, out_dir) -> [thumb_a,b,c]` với `thumbnail_texts = [t.thumbnail_text for t in script.title_options]` (3 overlay đã ghép cặp title ở phase-02; fallback `keywords` nếu rỗng). Trích 3 key-frame tại điểm scene-cut/motion cao (FFmpeg `select='gt(scene,0.4)'` hoặc lấy giữa 3 segment dài nhất) → Pillow overlay `thumbnail_texts[i]` lên biến thể i (font branding, stroke đậm) **→ thumb_i khớp title_option_i** (Test & Compare phase-06 có cặp coherent) → tối ưu tương phản (auto-contrast/tăng saturation nhẹ) → xuất 3 biến thể 1280x720 JPG. Gọi sau khi state=rendered; ghi path vào DB/`output/<id>/`. Giữ <200 dòng.
7. `cli.py`: `operator assemble --video-id X` (chạy luôn thumbnail_generator).
8. Verify output: `ffprobe final.mp4` codec=h264, yuv420p, có audio; caption hiển thị; audio sync ở phút cuối (spot-check); 3 thumbnail tồn tại, text đọc được, tương phản đủ.

## Todo List
- [ ] kenburns_ffmpeg render_segment (zoompan, alternate zoom, clamp duration theo shot_type + cắt trên beat)
- [ ] caption_whisper (faster-whisper segment-level → TextClip)
- [ ] audio_mixer (narration + music ducked, fade)
- [ ] branding intro/outro assets + concat
- [ ] video_builder 1-pass composite + export libx264
- [ ] thumbnail_generator: 3 key-frame → overlay `thumbnail_text` (paired-title từ script.json) → optimize contrast → 3 biến thể JPG
- [ ] cli assemble (chạy thumbnail_generator); clip.close() everywhere
- [ ] ffprobe verify h264/yuv420p + sync spot-check; 3 thumbnail đọc được

## Success Criteria
- `final.mp4`: H.264, yuv420p, 1920x1080, 30fps, dài = narration ± intro/outro; audio narration rõ, music dưới nền.
- Caption khớp lời (sai lệch <0.5s), không tràn khung.
- Audio KHÔNG drift ở phút cuối.
- Render 10' video hoàn tất < ~45' trên M1 Max; RAM không leak (theo dõi).
- `videos.state = rendered`, `duration_sec` đúng.

## Risk Assessment
| Risk | L | I | Mitigation |
|---|---|---|---|
| Pillow 11/12 gãy TextClip | Med | High | Pin 10.2.0 (phase 01); test caption sớm. |
| Audio drift video dài | Med | High | 1-pass composite; không re-read; close clips; verify phút cuối. |
| TextClip bottleneck | Med | Med | Segment-level (5-30s) không word-level. |
| Render chậm (CPU-only M1) | Med | Med | Ken Burns pre-render FFmpeg; preset fast; cadence ≤3/tuần chấp nhận. |
| Memory leak render tuần tự | Med | Med | `clip.close()`; chạy 1 video/process (scheduler phase 07). |

## Security Considerations
- Chỉ dùng music royalty-free/licensed (audit `assets` kind=music, license). Không dùng nhạc bản quyền → tránh Content ID.
- Font caption dùng font có license phân phối (vd Open Sans/Noto). Ghi vào `assets/branding/`.

## Next Steps
→ Phase 05 gửi `final.mp4` (URL) qua Telegram để duyệt.

## Unresolved Questions
- Nguồn nhạc + font license cuối? (chốt cùng phase 00 open Q).
- Cần SFX (sóng biển, gió) không? — YAGNI P0, cân nhắc P1 nếu retention thấp ở đoạn tĩnh.
