# Phase 02 — Content Engine (Topic Backlog + Script Generator)

## Context Links
- Overview: [plan.md](plan.md) · Prev: [phase-01](phase-01-project-scaffold-config.md)
- Research: brief "Anthropic/Gemini script" (nội bộ) + design doc §5 (anti-slop layer).

## Overview
- **Priority:** P0
- **Status:** pending
- **Description:** Sinh backlog chủ đề "Forgotten Maritime Disasters" (seed thủ công = originality + LLM đề xuất) và generate script 8-15' bằng Claude với prompt biến thiên (chống AI-slop), có bước research/nguồn thật và shot-list keyword cho visual-fetcher.

## Key Insights
- **Originality layer = policy survival.** Không để LLM tự bịa; ép cấu trúc "góc riêng (angle) + hook 30s + research nguồn thật + fact list". Human seed topic = tín hiệu original. **[nghiên cứu policy 2026] `angle` PHẢI là LUẬN ĐIỂM / POV diễn giải** (vd "vì sao thảm hoạ này bị che giấu", "bài học bị lãng quên") — KHÔNG phải tường thuật fact trung tính. YouTube inauthentic-filter đòi "góc nhìn máy không tổng hợp được"; review gate reject nếu narration chỉ kể khách quan, không có nhận định.
- **Hook = retention lever (critical).** 30-45s đầu quyết định audience-retention → policy/monetization. Ép cấu trúc 3 tầng: (a) **0-5s pattern-interrupt** — thống kê sốc / claim gây tò mò / hình ám ảnh; (b) **5-30s context+teaser** — dựng bối cảnh + hứa payoff nhưng KHÔNG spoil; (c) **text-overlay key claim** (1 câu ngắn) để phase 03 render on-screen. Sinh **2-3 phương án hook** = **3 lựa chọn cho human chọn 1** ở review gate (phase 05) — **KHÔNG phải A/B thật**: YouTube không cho A/B 30s đầu sau publish (chỉ thumbnail test được qua Test & Compare), nên đây là human-judgment không phải data. Cấm pattern-interrupt sáo (blacklist cụm mở đầu lặp: "What if I told you…", "In the annals of…").
- **Pacing grid (chống drop-off giữa video).** Mỗi 60-90s narration phải có 1 **payoff node** = fact bất ngờ / twist / reveal để reset attention. Outline mẫu 8' (~1200 từ) = 5-6 node. LLM liệt kê node vào metadata để verify mật độ.
- **Payoff-node QUALITY gate (critical cho APV).** Đếm số node ≠ đo chất lượng — LLM sẽ dán nhãn fact nhạt là "payoff" để pass. Ép LLM **tự chấm mỗi node `surprise_score` 1-5** (1=đã biết rộng rãi, 5=twist thật gây sốc/cảm xúc) + 1 câu lý do. **Reject node <3 → regenerate**; script phải có **≥5 node đạt score ≥3** mới hợp lệ. Đây là fix quan trọng nhất giữ APV ≥45% với format ảnh tĩnh (visual không cứu được narration nhạt).
- **Chống AI-slop:** biến thiên cấu trúc script (rotate template: cold-open kể chuyện / câu hỏi / timeline ngược), tránh cụm mở đầu lặp ("In the annals of…"). Giữ pool template trong code, random chọn. **(đã có — mở rộng bên dưới).**
- **Template diversity = anti-inauthentic (critical).** Định nghĩa rõ **3-5 narrative pattern**: `chronological` / `causal-chain` (nhân-quả) / `perspective-flip` (đổi góc nhìn nạn nhân↔điều tra) / `mystery-first` (bí ẩn trước, giải sau) / `impact-backward` (hậu quả trước, truy ngược nguyên nhân). Track pattern đã dùng qua các video; **flag nếu >50% script gần đây cùng 1 pattern** → ép chọn pattern khác (kênh nhìn "đúc khuôn" = rủi ro inauthentic/policy).
- **Script phải sinh 2 output cùng lúc:** (a) narration text (đưa TTS), (b) **shot-list** JSON = list beat `{beat_id, narration_span, keywords[≤4], mood}` để phase 03 fetch hình. Keyword ≤50 token, dạng danh từ ("ancient shipwreck, underwater, 19th century" KHÔNG câu dài) — brief visual xác nhận prompt dài làm giảm chất lượng.
- **Độ dài:** 8-15' narration ≈ 1200-2200 từ (≈150 wpm). Ép LLM target word-count.

## Requirements
Functional:
1. `topic_backlog`: seed list (YAML/JSON thủ công) + hàm LLM `suggest_topics(n)` đề xuất chủ đề mới từ seed → ghi bảng `topics` status=backlog (chờ user duyệt ở review gate hoặc auto-pick).
2. `script_generator`: nhận topic → gọi Claude → trả `{narration, hooks[2-3], pattern, payoff_nodes[{desc, surprise_score, reason}], shot_list, title_options[3×{title, thumbnail_text}], description, tags, sources[]}`.
2.5. `research_gate` (bước fact-check TRƯỚC khi viết script): liệt kê ≥3 nguồn uy tín, cross-verify ngày/địa danh/tên, chấm `research_depth` (Low/Med/High) → **reject Low** (không sinh script). Lưu `citations[]` vào metadata (ẩn khỏi video).
3. Lưu script vào `output/<video_id>/script.json` + `script.txt`; update `videos.state = scripted`.
Non-functional: prompt template ngoài code (`prompts/` .md) để chỉnh không sửa code; retry + JSON schema validation output LLM.

## Architecture — data flow
```
seed_topics.yaml ─┐
                  ├─► topic_backlog.suggest() ─(LLM)─► topics table (backlog)
                  │                                        │ pick
                  ▼                                        ▼
       (user/scheduler chọn topic) ──► research_gate(topic)  [≥3 nguồn, cross-verify, research_depth]
                                          │ reject nếu Low
                                          ▼
                                       script_generator.generate(topic, citations)
                                          │ Claude (pattern chọn tránh trùng >50%)
                                          ▼
        script.json {narration, hooks[2-3], pattern, payoff_nodes[scored≥3],
                     shot_list[], title_options[3×{title,thumb_text}], desc, tags, sources, citations(ẩn)}
                                          │
                                          ▼  update videos.state=scripted
```

## Related Code Files
- Create: `src/ai_operator/content/topic_backlog.py`, `src/ai_operator/content/script_generator.py`, `src/ai_operator/content/research_gate.py` (fact-check ≥3 nguồn + research_depth), `src/ai_operator/content/llm_client.py` (wrapper Anthropic + Gemini fallback), `src/ai_operator/content/schema.py` (pydantic models: ShotBeat, Hook, Citation, ScriptOutput), `prompts/script_system.md`, `prompts/script_templates/` (3-5 pattern đặt tên rõ), `data/seed_topics.yaml`.
- Modify: `db/models.py` (nếu cần cột angle — đã có), `cli.py` (lệnh `gen-topics`, `gen-script`).
- Delete: none.

## Implementation Steps
1. `data/seed_topics.yaml`: 10-15 topic maritime thủ công (title + angle + 1-2 source hint). = originality seed.
2. `content/llm_client.py`: `def complete(system, user, max_tokens, json=True)` dùng `anthropic.Anthropic().messages.create(model="claude-...")`; fallback Gemini nếu Anthropic lỗi/quota. Trả text; parse JSON.
3. `content/schema.py`: `ShotBeat(beat_id:int, narration_span:str, keywords:list[str], mood:str)`; `Hook(variant_id:int, pattern_interrupt:str, context_teaser:str, text_overlay:str)`; `PayoffNode(idx:int, description:str, surprise_score:int, reason:str)` (validator: `surprise_score` ∈ 1-5); `TitleOption(title:str, thumbnail_text:str)` (title theo CTR-pattern: curiosity-gap/số/stakes; `thumbnail_text` = overlay ngắn ≤5 từ **khớp** title để phase 04 ghép cặp title×thumbnail nhất quán); `Citation(claim:str, source:str, verified:bool)`; `ScriptOutput(narration, hooks:list[Hook] (2-3), pattern:str, payoff_nodes:list[PayoffNode], shot_list:list[ShotBeat], title_options:list[TitleOption] (3), description, tags, sources, citations:list[Citation], research_depth:str)`. Validate bằng pydantic.
3.5. `content/research_gate.py`: `research(topic) -> {citations[], research_depth}`: LLM liệt kê ≥3 nguồn uy tín + cross-verify ngày/địa danh/tên; chấm depth Low/Med/High. Nếu Low → raise/skip (không viết script). Citations chỉ vào metadata, KHÔNG vào narration/video.
4. `prompts/script_system.md`: system prompt — vai narrator documentary BBC-style; yêu cầu: word target, **angle = luận điểm/POV diễn giải độc nhất (không tường thuật trung tính)**, **hook 30-45s theo cấu trúc 3 tầng (pattern-interrupt 0-5s → context+teaser → text-overlay), sinh 2-3 phương án hook (human chọn 1)**, **payoff node mỗi 60-90s (5-6 node/8'), mỗi node TỰ CHẤM `surprise_score` 1-5 + lý do**, **3 title theo CTR-pattern (curiosity-gap/số/stakes) mỗi title kèm `thumbnail_text` ≤5 từ khớp**, research nguồn thật (dùng citations đã verify), CẤM cụm mở đầu sáo, output JSON đúng schema, shot_list keywords ngắn.
5. `prompts/script_templates/*.md`: 3-5 khung theo narrative pattern rõ tên (`chronological`, `causal-chain`, `perspective-flip`, `mystery-first`, `impact-backward`). `script_generator` chọn pattern **tránh trùng** (không random thuần — check lịch sử pattern gần đây, **flag/đổi nếu >50% cùng pattern**) → chèn vào prompt.
6. `content/topic_backlog.py`: `load_seeds()`, `suggest_topics(n)` (LLM: "đề xuất N thảm hoạ hàng hải ít được kể, kèm angle"), `pick_next()` (topic backlog cũ nhất chưa dùng).
7. `content/script_generator.py`: `generate(topic) -> ScriptOutput`: gọi `research_gate` trước (reject Low) → build prompt (system + template pattern chọn tránh trùng + topic + citations) → llm_client → validate (hooks≥2; **≥5 payoff_node có `surprise_score`≥3** — nếu <5 node đạt ngưỡng thì **regenerate riêng phần node yếu 1 lần**, vẫn thiếu → raise cho human review gate; title_options=3 mỗi cái có `thumbnail_text`) → **narration mở đầu bằng hook variant[0]** (mặc định, để TTS voice ở phase-03; hooks[1-2] lưu làm phương án swap khi `EDIT_HOOK` ở review gate phase-05) → ghi `output/<id>/script.json` (kèm citations ẩn) + `.txt` (chỉ narration) → tạo/`update` row `videos` state=scripted. Retry 2 lần nếu JSON invalid.
8. `cli.py`: `operator gen-topics --n 10`, `operator gen-script --topic-id X`.
9. Compile + chạy thử 1 topic → kiểm script.json hợp lệ, narration ~1500 từ, shot_list ≥10 beat.

## Todo List
- [ ] seed_topics.yaml (10-15 topic + angle)
- [ ] llm_client (Anthropic + Gemini fallback)
- [ ] schema.py (ShotBeat, Hook, PayoffNode, TitleOption, Citation, ScriptOutput) pydantic
- [ ] research_gate (≥3 nguồn, cross-verify, research_depth, reject Low)
- [ ] script_system.md + 3-5 template pattern (đặt tên rõ) + hook 3 tầng + pacing grid + payoff surprise_score self-rate + title CTR-pattern
- [ ] pattern-diversity guard (track lịch sử, flag >50% trùng)
- [ ] topic_backlog (suggest/pick)
- [ ] script_generator.generate + persist + state (citations ẩn)
- [ ] cli gen-topics / gen-script
- [ ] chạy thử: script.json valid, word-count đạt, shot_list đủ, hooks≥2, **≥5 payoff_node score≥3**, title_options có thumbnail_text

## Success Criteria
- `operator gen-script --topic-id X` sinh `script.json` pass pydantic; narration 1200-2200 từ; `shot_list` ≥10 beat với keywords ≤4 mỗi beat; `sources` ≥2; `citations` ≥3 với `research_depth` ≥ Med (Low bị reject); `hooks` 2-3 phương án (human chọn 1 ở gate, không phải A/B); `payoff_nodes` **≥5 node đạt `surprise_score` ≥3** (node <3 bị reject+regen); `title_options` = 3, mỗi cái kèm `thumbnail_text` khớp title.
- `videos.state = scripted`; citations ẩn khỏi narration/video.
- 2 lần chạy cùng topic → cấu trúc mở đầu KHÁC nhau (biến thiên hoạt động); pattern-diversity guard flag khi >50% video gần đây cùng pattern.

## Risk Assessment
| Risk | L | I | Mitigation |
|---|---|---|---|
| LLM trả JSON hỏng | Med | Med | pydantic validate + retry 2x + prompt "output only JSON"; dùng tool/response_format nếu SDK hỗ trợ. |
| AI-slop lặp mẫu → policy | Med | High | Pool template random + blacklist cụm sáo + human review gate (phase 05). |
| Kênh "đúc khuôn" (>50% cùng pattern) → inauthentic/policy | Med | High | Pattern-diversity guard: track lịch sử pattern, flag + ép đổi khi vượt ngưỡng. |
| LLM bịa nguồn (hallucinate) | Med | High | research_gate: ≥3 nguồn + cross-verify ngày/địa danh/tên + research_depth reject Low TRƯỚC khi viết script; user QA ở review gate. |
| Hook yếu → retention 30s thấp → policy | Med | High | Ép hook 3 tầng + 2-3 phương án cho human chọn ở gate (KHÔNG dựa "A/B" ảo — YouTube không test được 30s đầu); blacklist cụm sáo. |
| Payoff node nhạt → APV rớt <45% (format ảnh tĩnh không cứu được) | **Med** | **High** | QUALITY gate: `surprise_score` 1-5, reject <3, ép ≥5 node đạt ≥3; human QA ở review gate. |
| Title×thumbnail lệch thông điệp → CTR thấp | Med | Med | `title_options` kèm `thumbnail_text` khớp; phase 04 ghép cặp từ cùng nguồn thay vì sinh rời. |
| Cost token phình | Low | Low | Cadence ≤3/tuần; log token/ chi phí mỗi call. |

## Security Considerations
- API key qua config; không log nội dung key. Không đưa PII vào prompt.
- Sources lưu để audit bản quyền narration (không copy nguyên văn tài liệu — paraphrase).

## Next Steps
→ Phase 03 dùng `shot_list` (visual) + `script.txt` (TTS).

## Unresolved Questions
- Auto-pick topic hay bắt user duyệt topic ở review gate? — đề xuất P0: user duyệt topic 1 lần qua Telegram (nằm trong phase 05 mở rộng) để tăng originality; scheduler auto-pick ở P1.
