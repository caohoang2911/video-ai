# API Implementation Reference (verified 2026-07-08)

> Deep-research of 5 version-sensitive APIs. Use these EXACT signatures when implementing
> phases 03/04/05/06. Corrections to the plan are flagged **[PLAN FIX]**.

---

## 1. YouTube Data API v3 — `google-api-python-client==2.198.0` (phase 06)

**OAuth headless (refresh token):**
```python
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
creds = Credentials(token=None, refresh_token=RT, token_uri="https://oauth2.googleapis.com/token",
                    client_id=CID, client_secret=CS,
                    scopes=["https://www.googleapis.com/auth/youtube.upload",
                            "https://www.googleapis.com/auth/youtube",
                            "https://www.googleapis.com/auth/yt-analytics.readonly"])
if not creds.valid: creds.refresh(Request())
yt = build("youtube","v3",credentials=creds)
```

**Upload (resumable):**
```python
from googleapiclient.http import MediaFileUpload
body = {"snippet":{"title":t[:100],"description":d,"tags":tags,"categoryId":"27"},
        "status":{"privacyStatus":"private","publishAt":iso_utc,
                  "selfDeclaredMadeForKids":False,"containsSyntheticMedia":True}}
media = MediaFileUpload(path, mimetype="video/mp4", chunksize=8*1024*1024, resumable=True)  # multiple of 256KB
req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
while True:
    status, resp = req.next_chunk()   # 5xx -> backoff min(2**n,64); 404 -> restart whole upload
    if resp: break
vid = resp["id"]
```

- ✅ `status.containsSyntheticMedia=True` **IS a real API field** (Oct 2024+) → auto AI-label. Compliance strategy valid.
- `publishAt` requires `privacyStatus="private"`; past `publishAt` publishes immediately.
- `selfDeclaredMadeForKids` settable; `madeForKids` is read-only (computed).
- **chunksize MUST be a multiple of 256KB** (256*1024). `-1` = whole file in one request.
- Session URI expires ~7 days; 404 → cannot resume, restart with new request.
- Quota: insert now **~1 unit** (was 1600, changed Dec 2025); thumbnails.set=50. Throttle ≤3/wk is trivially safe. Keep guard.
- `thumbnails.set(videoId=, media_body=MediaFileUpload(thumb, mimetype="image/jpeg"))` — **does NOT require phone verification** (per official docs). ≤2MB, JPEG/PNG. Still wrap non-blocking.
- Refresh token dies after 6 months inactivity → phase 07 monthly `creds.refresh()` keep-alive.
- **[PLAN FIX] Test & Compare (title/thumbnail A/B) is STUDIO-ONLY — no public API.** Phase 06 `test_and_compare.py` must NOT call an API. Instead: emit the 2–3 title variants + 3 thumbnails and a manual Studio checklist; record the human-observed winner via a CLI (`set-winner`). Keep `uploads.winning_title/winning_thumbnail/ab_status` columns.

---

## 2. MoviePy — `moviepy==2.2.1` + `Pillow==11.1.0` (phase 04)

- Import `from moviepy import VideoFileClip, TextClip, ImageClip, CompositeVideoClip, CompositeAudioClip, AudioFileClip, concatenate_videoclips` — **NOT `moviepy.editor`** (removed).
- v1→v2: `.set_*`→`.with_*` (outplace, reassign!); `.fx()`→`.with_effects([...])`; `.close()` deprecated (no-op, may warn — **don't call it**).
- **[PLAN FIX] Pillow: pin `==11.1.0`** (research-confirmed stable for 2.2.1 TextClip). 12.x breaks (`_multiline_spacing`); 10.2.0 is fallback only. Plan's `10.2.0` pin superseded.
- **TextClip `font=None` now WORKS** (uses Pillow default) but pass a real `.ttf` for branded captions:
```python
txt = TextClip(text=seg_text, font="assets/branding/caption.ttf", font_size=48, color="white",
               stroke_color="black", stroke_width=2, method="caption", size=(1600,None), duration=seg.end-seg.start)
txt = txt.with_start(seg.start).with_position(("center", 900))
```
- Export H.264: `clip.write_videofile("final.mp4", fps=30, codec="libx264", preset="fast", ffmpeg_params=["-crf","23","-pix_fmt","yuv420p"], threads=8)`. Always set `fps` explicitly.
- `concatenate_videoclips(clips, method="chain")` (no resize). `CompositeVideoClip([base,*caps], size=(1920,1080))` (later = on top). `CompositeAudioClip([narration, music.with_volume_scaled(0.2)])`.
- Ken Burns via FFmpeg `zoompan` subprocess (pre-render) is still the right call — MoviePy zoom is CPU-heavy.

---

## 3. ElevenLabs — `elevenlabs==2.56` (phase 03)

**[PLAN FIX] Request-stitching uses `previous_request_ids` (LIST, max 3) and needs `with_raw_response` to read the id from headers:**
```python
from elevenlabs.client import ElevenLabs
client = ElevenLabs(api_key=KEY)
prev_ids = []
def synth(text, prev_text=None, next_text=None):
    r = client.text_to_speech.with_raw_response.convert(
        voice_id=VID, text=text, model_id="eleven_multilingual_v2", output_format="mp3_44100_128",
        voice_settings={"stability":0.6,"similarity_boost":0.8,"style":0.0,"use_speaker_boost":True},
        previous_text=prev_text, next_text=next_text,
        previous_request_ids=prev_ids[-3:] or None)
    rid = r._response.headers.get("request-id")          # read BEFORE consuming iterator
    with open(out,"wb") as f:
        for chunk in r.data: f.write(chunk)               # r.data is Iterator[bytes] — must fully consume
    if rid: prev_ids.append(rid)
```
- request_id expires 2h; stitching NOT supported on `eleven_v3` (use `eleven_multilingual_v2`).
- `previous_text` is IGNORED if `previous_request_ids` supplied.
- Starter = 30k chars/month HARD (no overage); chars = text + previous_text, counted per chunk. → alert at 70%, fallback chain.
- **edge-tts fallback (async):** `await edge_tts.Communicate(text, voice="en-US-ChristopherNeural").save(path)`. Good male doc voices: `ChristopherNeural`, `GuyNeural`. No stitching. Wrap with `asyncio.run` from sync code.

---

## 4. python-telegram-bot — `21.9` (phase 05)

- **`app.run_polling()` is SYNC and blocking** — manages its own event loop. Call directly from CLI, NO `asyncio.run()`. All handler callbacks are `async def`.
```python
app = Application.builder().token(TOKEN).concurrent_updates(False).build()  # sequential -> SQLite-safe
app.add_handler(CommandHandler("chatid", chatid_cb))
app.add_handler(CallbackQueryHandler(cb))     # update.callback_query.data
app.run_polling()
async def cb(update, ctx):
    q = update.callback_query
    code, vid = q.data.split(":")               # callback_data <=64 UTF-8 BYTES
    await q.answer()                             # REQUIRED (clears spinner)
    await q.edit_message_reply_markup(reply_markup=None)
    await q.edit_message_text("APPROVED ...")
await ctx.bot.send_video(chat_id, video=URL_STR, caption=..., reply_markup=markup, supports_streaming=True)
```
- `video=` accepts a plain HTTPS URL string (should end `.mp4`). Whitelist `TELEGRAM_CHAT_ID`, drop others.
- Single polling instance only (2 = 409 conflict). `concurrent_updates(False)` avoids SQLite races.

---

## 5. faster-whisper — `1.2.1` (phase 04 captions)

- **CPU-only on Apple Silicon** (CTranslate2 has no Metal/MPS). Use `base.en` (English) or `small.en`.
```python
from faster_whisper import WhisperModel
model = WhisperModel("base.en", device="cpu", compute_type="int8")     # module-level singleton
segments, info = model.transcribe(mp3, language="en", word_timestamps=False)
caps = [{"start":s.start,"end":s.end,"text":s.text} for s in segments]  # LAZY generator — iterate once
```
- `base.en` ≈ 8–15s for a 10-min mp3 on M1 Max; ~1GB RAM; segment-level is enough (no word_timestamps → faster, avoids TextClip bottleneck).
- First run downloads model (~140MB) to `~/.cache/huggingface/hub/`.

---

## Net plan corrections
1. **phase 06:** drop API-based Test&Compare → manual Studio A/B + `set-winner` CLI (Studio-only). Thumbnail needs no phone verification.
2. **phase 04:** `Pillow==11.1.0` (not 10.2.0); don't call `.close()`; TextClip font optional.
3. **phase 03:** `previous_request_ids` (list, via `with_raw_response`); edge-tts is async.
4. **phase 04 captions:** `base.en`, CPU-only.
