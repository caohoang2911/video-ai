# Research Report: End-Screen Outro Hook Formula — Close the Old Story, Open the Next Series

**Conducted:** 2026-07-18 12:45 (Asia/Saigon)
**Scope:** A reusable copy formula for the last ~12s of a video that (a) gives the current story satisfying closure, and (b) opens a curiosity loop toward the next video / next series — feeding the existing `outro_teaser` field and the end-screen outro card.

---

## Tóm tắt (VN)

Công thức **"SEAL & CRACK"** — 4 nhịp cho lời thoại outro + 1 dòng teaser trên card:

1. **SEAL** (đóng vòng cũ): 1 câu chốt payoff của chuyện vừa kể → cho khán giả cảm giác trọn vẹn (tránh "phản bội" khi loop không được đóng).
2. **LINK** (bắc cầu): 1 câu nối chủ đề vừa xong sang "thế giới" lớn hơn của kênh/series.
3. **CRACK** (mở vòng mới): teaser chuyện kế tiếp bằng **chi tiết CỤ THỂ + câu hỏi bị giấu** (curiosity gap của Loewenstein: cụ thể, nhiều cảm xúc, "gần" đủ để thấy với tới).
4. **POINT** (chỉ tay): CTA khớp với element next-video đang hiện trên màn.

Điểm mấu chốt research xác nhận: **phải đóng vòng cũ TRƯỚC rồi mới mở vòng mới** — cliffhanger chỉ hiệu quả khi "trả lời câu cũ đồng thời đặt câu mới"; nếu chỉ treo mà không chốt, khán giả thấy bị lừa. Teaser mạnh nhất khi **cụ thể + salient + có sức nặng cảm xúc + đủ gần để với tới**, không phải mơ hồ kiểu "còn nhiều điều bất ngờ".

Kênh nên tách 2 tầng loop: **micro-loop** (video kế) dùng `outro_teaser` + element next-video; **macro-loop** (series kế) dùng 1 "lời hứa thương hiệu" lặp lại (số thứ tự series + "vault còn niêm phong").

---

## The Formula: "SEAL & CRACK"

Four spoken beats over the last ~12s (the outro card window), then one distilled line on the card.

| Beat | Job | Length | Psych lever |
|------|-----|--------|-------------|
| **SEAL** | Close *this* story's loop — a resonant one-line verdict/payoff | ~2–3s | Closure (avoids Zeigarnik "betrayal") |
| **LINK** | Bridge from this story to the channel's larger pattern/world | ~2s | Continuity / series belonging |
| **CRACK** | Open the *next* loop — concrete detail + withheld answer | ~3–4s | Curiosity gap (Loewenstein) + open loop (Zeigarnik) |
| **POINT** | Direct the click to the on-screen element | ~2s | Aligned spoken CTA ↔ clickable element |

**Pacing:** documentary TTS ≈ 2.5–3 words/s → keep the whole spoken outro **~30–40 words** for a 12s card. Never say "thanks for watching" / "goodbye" (a sign-off ends the session; a bridge hands over the next story — matches `endscreen_outro.py` comment).

### The card line (`outro_teaser`, ≤90 chars)
The card line = a **distilled CRACK**. One line, ≤90 chars, no goodbye, aligns with the next-video thumbnail. Template:

```
[CONCRETE SPECIFIC] + [WITHHELD PAYOFF/QUESTION] + [reachable pointer]
```

The teaser is written to a textfile before `drawtext` (see `endscreen_outro.py:44`), so **apostrophes and colons are safe** in this line (unlike the inline HEADLINE).

---

## The 5 Rules a Good CRACK/Teaser Must Pass

From information-gap theory (Loewenstein 1994) — a gap motivates only when it is:

1. **Specific** — a named place, number, object, date. ✅ "a room sealed behind a brick wall in 1971" ❌ "something shocking".
2. **Salient** — the gap is felt *now*, not abstract. Put the missing piece in the last clause.
3. **Emotionally meaningful** — stakes a human cares about (death, cover-up, betrayal, survival), not trivia.
4. **Reachable** — the answer feels one click away ("…and it's on screen now"), close enough to existing knowledge that the brain expects to close it.
5. **Closes-first** — the SEAL beat must actually resolve the current story. Open loops without prior closure = the "didn't stick the landing" backlash.

> Stacking caveat (Zeigarnik): open **one** new loop at the end, not five. In-body you may keep 3–5 loops live; at the outro, close the video's loop and open exactly one next-loop.

---

## Micro-loop vs Macro-loop (video vs. series)

The request names **"serie tiếp theo"** — treat two loop scopes with two mechanisms:

- **Micro-loop → next VIDEO.** The CRACK + `outro_teaser` + a "specific video" end-screen element. Research: aligning the spoken CTA with a *specific* clickable next video is what drives the high CTR; series/playlist elements "quietly outperform" for episodic content.
- **Macro-loop → next SERIES/season.** A recurring **franchise promise** that reframes each video as one entry in a named, ongoing world. Give the series a name (e.g. *"Sealed"*, *"Buried Archives"*) and let the LINK beat carry the promise: *"This is #7 in [Series] — the vault isn't empty yet."* Viewers "enjoy knowing there is more coming" — that expectation is the binge engine.

Practical split for the outro:
- LINK beat = macro promise (series belonging).
- CRACK beat + card line = micro promise (the exact next video).

---

## Fill-in-the-blank Templates

**Spoken outro (paste into script prompt):**
```
SEAL:  "[One-line verdict of this story — what it ultimately meant/revealed]."
LINK:  "But [this channel/era/place] buried more than one [secret/story]."
CRACK: "The next one: [concrete specific — place/number/object], and [withheld payoff — what it admits / what was inside / who it names]."
POINT: "It's on screen now — press play."
```

**Card line (`outro_teaser`, ≤90 chars), pick one shape:**
```
A) "[Concrete noun]. [Concrete noun]. [Withheld question] — next."
B) "They [action] in [year]. [What surfaced] is on screen now."
C) "[The thing that happened]. [The thing that didn't]. Start here."
```

---

## Worked Examples (forgotten-history / disaster / archival niche)

**Example 1 — spoken outro (~38 words):**
> **SEAL:** "Sealed for twenty-six years — and when it finally opened, it rewrote the whole story."
> **LINK:** "But they buried more than one file."
> **CRACK:** "The next one admits something worse — and almost no one has read it."
> **POINT:** "It's on screen now. Press play."

**Example 2 — spoken outro (series/macro flavor):**
> **SEAL:** "The rescue worked. The cover-up almost did too."
> **LINK:** "This is one of the files they hoped stayed forgotten — and it's not the last."
> **CRACK:** "The next one starts with a photo that shouldn't exist."
> **POINT:** "That story's right here — let's open it."

**Card lines (`outro_teaser`, all ≤90 chars):**
- `One sealed room. Forty years of silence. What was inside is next.` (63)
- `They buried the report in 1971. Someone just dug it back up — next.` (66)
- `A ship that vanished. A photo that shouldn't exist. Start here.` (62)
- `The rescue worked. The cover-up didn't. That file's on screen now.` (65)
- `Everyone signed off on it. One man refused. His story is next.` (61)

---

## Anti-patterns (reject these)

| ❌ Bad | Why it fails | ✅ Fix |
|--------|--------------|--------|
| "Thanks for watching, see you next time!" | Sign-off closes the session | Bridge, never goodbye |
| "There's so much more to discover…" | Vague — no specific gap | Name a place/number/object |
| "In the next video we cover volcanoes." | Answers the gap = kills curiosity | Withhold the payoff, not the topic |
| Cliffhanger with no SEAL | Current loop unresolved → betrayal backlash | Close this story first |
| 3 teasers stacked at the end | Dilutes; none feels reachable | One next-loop only |
| "You won't believe what happens next!!" | Clickbait tone, no substance | Concrete detail + real stake |

---

## Code Integration (scout-verified 2026-07-18)

Corrected premise: guidance was **not** missing. The generation prompt is externalised to `prompts/script_system.md` (loaded verbatim by `prompt_builder.load_system_prompt`), and an `## End-screen teaser` block already existed at `script_system.md:181-187` — but it taught only the *open* ("one more story"), never the *close*. So this task **enhances committed guidance**, it does not fill an empty field.

**Shipped (this session):**
1. **Rewrote `## End-screen teaser`** (`prompts/script_system.md:181-207`) into the two-part **SEAL→CRACK** formula: seal this story's closure, then crack open the next *by kind* (evergreen), + a house-style ✗/✓ calibration set (opens-without-sealing / seals-without-opening / too-vague / names-a-specific-video / good). Prompt-markdown only, zero code risk, redeploys immediately.
2. **Synced the JSON output hint** (`script_system.md:214`) to the SEAL/CRACK contract.
3. **Updated `FALLBACK_TEASER`** (`endscreen_outro.py:33`) from a pure-open line to a seal+open evergreen default ("One forgotten story closes - another is already waiting."). Encode tests pass (`tests/test_ffmpeg_encode.py` 10/10).

**Also shipped — `outro_spoken` (spoken 4-beat close), user chose "build luôn":** the last ~12s is now voiced (SEAL→LINK→CRACK→POINT) on the same ElevenLabs brand voice. 8 files:
- `schema.py` `outro_spoken: str = ""` (defaulted, back-compat) · `script_system.md` `## Spoken outro` guidance + JSON shape (≤35 words, ≤3 sentences, evergreen, must differ from `outro_teaser`).
- `tts_narrator.synthesize_outro()` — short line on the brand voice, own `OUTRO_STEP` checkpoint, **best-effort/never-raises** (None on empty / voice unavailable / quota spent / any error; never edge-tts — no speaker mismatch). Synthesized in the **voice step** (`commands.gen_audio`, refreshed in `revoice`), so assemble stays a pure render step.
- `endscreen_outro.build_endscreen_outro(voice=…)` — card **stretches 12→20s** to cover speech; music **ducks under voice** via the body's exact `sidechaincompress` chain; unreadable audio is **probed and dropped** (never crashes the render); voice fade covers only the trailing tail so the closing CTA lands full-level.
- `branding.make_outro` + `video_builder` wire the voice through (consume `outro_voice.mp3` if present).
- Tests: +7 (real-ffmpeg duck/stretch/voice-only/20s-cap/degrade-on-corrupt + synth guard/graceful-degrade/catch-all). **450 passed.**
- Hardened per adversarial review (4-lens, findings verified): catch-all in `synthesize_outro`, corrupt-audio input guard, CTA-fade fix, prompt length/dedup tightening.

**Also shipped — outro visual upgrade (documentary backdrop, user-approved demo 3):** the card is no longer flat black. `build_endscreen_outro(backdrop_image=…)` renders the closing beat's still via `kenburns_ffmpeg.render_segment` + `ARCHIVAL_GRADE_VF` (body's archival grade) + darken −0.28 + blur 5 + vignette + glow; text fades in with a border. `video_builder._last_still_image` picks the last beat with a still; `branding.make_outro` passes it through; missing/undecodable → flat dark fallback. Two ffmpeg gotchas fixed: (1) corrupt beat image hangs `render_segment`'s `-loop 1` → gated by `_decodable_image` (decode-one-frame; ffprobe is too lenient); (2) JPEG backdrop is full-range `yuvj420p` vs the `yuv420p` concat spec → `scale=out_range=tv` on the backdrop path. Tests +4 (backdrop render / missing+corrupt fallback / `_last_still_image`). `test_ffmpeg_encode.py` 18/18; rest of suite 432/432 (4 unrelated pre-existing `test_thumbnail_hero.py` reds).

**Deferred (optional, not built):**
- **Thread `Topic.category` into the prompt** so the CRACK can name a themed noun ("another forgotten *shipwreck*"). Low value: the model already infers theme from the topic title/facts.

---

## Sources

**End-screen mechanics & retention**
- [TubeBuddy — End-screen strategy: one minute that can double watch time](https://www.tubebuddy.com/blog/youtube-end-screen-strategy-for-views-and-double-watch-time/)
- [TubeBuddy — End screens tips to engage and convert](https://www.tubebuddy.com/blog/youtube-end-screens-tips/)
- [Gyre — High-converting YouTube end screens 2026](https://gyre.pro/blog/how-to-create-high-converting-youtube-end-screens-tips-and-examples)
- [NexLev — End-screen tips to hook clicks](https://www.nexlev.io/youtube-end-screen-tips)
- [YouTube Help — Add end screens](https://support.google.com/youtube/answer/6388789?hl=en)

**Open loop / Zeigarnik / cliffhangers**
- [Zeigarnik effect — Wikipedia](https://en.wikipedia.org/wiki/Zeigarnik_effect)
- [PodIntelligence — Mastering the Zeigarnik effect for engaging storytelling](https://www.podintelligence.com/blog/zeigarnik-effect-for-engaging-storytelling/)
- [Alyssa Matesic — Zeigarnik effect in storytelling](https://www.alyssamatesic.com/free-writing-resources/zeigarnik-effect-on-writing)
- [Rafiul Alam — Why cliffhangers hijack your mind](https://alamrafiul.com/blogs/zeigarnik-effect-cliffhangers/)

**Curiosity gap / information-gap theory**
- [Loewenstein — Curiosity, information gaps, and the utility of knowledge (CMU PDF)](https://www.cmu.edu/dietrich/sds/docs/golman/golman_loewenstein_curiosity.pdf)
- [Psychology Fanatic — Information gap theory](https://psychologyfanatic.com/information-gap-theory/)
- [Medium/ILLUMINATION — Using curiosity gaps to increase engagement](https://medium.com/illumination/how-to-use-curiosity-gaps-to-increase-audience-engagement-b2137baf81cc)

**Faceless documentary / series binge structure**
- [OutlierKit — Faceless YouTube niches & CPM data 2026](https://outlierkit.com/resources/faceless-youtube-channels/)
- [VidPros — Most successful faceless YouTube channels](https://vidpros.com/top-faceless-youtube-channels/)

---

## Open Questions — RESOLVED (scout 2026-07-18)

1. **Series identity tracked? → No.** No series/season/franchise or entry-index anywhere (`schema.py:89-116`, `db/models.py`). The only grouping is `Topic.category` — 6 fixed sub-niche buckets (maritime, aviation, industrial, rail, structural, fire; `topic_categories.py:10-23`), a theme not a numbered series. `Video.parent_id` is only a Short→main link. **⇒ the CRACK must open the next story *by kind/theme*, never by ordinal or series name (that would be fabrication).**
2. **Next-video known at render time? → No.** YouTube's API can't set end-screen elements; they're placed once in Studio and re-applied per upload via "Import from video", with next-video = "Best for viewer" (auto-suggest) — confirmed by `endscreen_outro.py:2-3` + project memory. The pipeline never knows the specific next video. **⇒ `outro_teaser` must stay evergreen (no naming a specific next story).**
3. **Spoken outro today? → No.** Body narration ends on its last resonant sentence; the 12s card is music/silence with drawn teaser text only (`endscreen_outro.py:11,75`; `tts_narrator.py:42`). A spoken SEAL→POINT close needs a new `outro_spoken` field + TTS/mix wiring (scoped above) — deferred pending user decision.

## Remaining Unresolved
None. All gating questions answered; both the visual teaser guidance and the spoken 4-beat close (`outro_spoken`) are shipped, reviewed, and tested. Code not yet committed.
