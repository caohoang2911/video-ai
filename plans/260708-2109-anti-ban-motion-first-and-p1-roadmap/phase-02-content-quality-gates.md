---
phase: 2
title: "Content quality gates"
status: done
priority: P1
effort: "3-4h"
dependencies: []
---

# Phase 2: Content quality gates

## Overview
Strengthen the "original value" signals in the script: scored payoff nodes (surprise gate), an
interpretive POV `angle` (not a neutral summary), and thumbnail text paired to each title option.
These are editorial-judgment signals YouTube's inauthenticity detection rewards.

## Requirements
- Functional: `payoff_nodes` become scored objects; reject a script with <2 nodes scoring ≥3.
  `title_options` become `{title, thumbnail_text}` pairs; the thumbnail generator uses `thumbnail_text`.
  `angle` must be an interpretive POV, enforced in the prompt (reviewer can still reject).
- Non-functional: pydantic-validated; backward-safe writes to `script.json`; consumers updated in lockstep.

## Architecture
Schema change ripples content → assembler (thumbnail) → publisher (title, publish). Current
`content/schema.py` has `payoff_nodes: list[str]` and `title_options: list[str]`; both become lists of
objects. Pick ONE on-the-wire shape for `script.json`: `title_options: list[dict] {title, thumbnail_text}`
(plain JSON, not pydantic). Attribute access (`.title`, `.thumbnail_text`) is valid ONLY inside
`script_generator.py`, where the real `ScriptOutput` pydantic object exists in memory before it is
serialized to `script.json`. Every consumer that instead loads `script.json` back off disk —
`thumbnail_generator.py`, `metadata_builder.py`, `ab_variants.py`, and `publisher/publish.py` (an
omitted `title_options` consumer in the original design: its no-script fallback and its DB-title
overlay both inject bare strings) — sees plain dicts and must use dict access
(`opt["title"]`, `opt.get("thumbnail_text", "")`), never `.title`. `assembler/thumbnail_generator.py`
currently overlays keywords → switch to `thumbnail_text`.

## Related Code Files
- Modify: `src/ai_operator/content/schema.py` (`PayoffNode{text:str, surprise_score:int(1-5)}`; `TitleOption{title:str, thumbnail_text:str}`; update `ScriptOutput`)
- Modify: `src/ai_operator/content/script_generator.py` (reject if `<2` payoff nodes with `surprise_score>=3` → `_fail_video` + reject_reason; ONLY place that touches `TitleOption`/`PayoffNode` as pydantic attributes, before `script.json` serialization)
- Modify: `prompts/script_system.md` (angle = interpretive POV/hot-take; each payoff node scored 1-5 for surprise; each title paired with ≤5-word `thumbnail_text`)
- Modify: `src/ai_operator/assembler/thumbnail_generator.py` (overlay `opt["thumbnail_text"]` — dict access, instead of keywords)
- Modify: `src/ai_operator/publisher/metadata_builder.py` + `src/ai_operator/publisher/ab_variants.py` (read `opt["title"]` — dict access; A/B over the paired variants)
- Modify: `src/ai_operator/publisher/publish.py` (omitted from the original design — its no-script
  fallback (`[title] if title else []`) and its DB-title overlay (`[title, *[t for t in title_options
  if t != title]]`) both inject bare strings into a field now shaped `list[dict]`; fix both to the dict shape)

## Implementation Steps
1. `schema.py`: add `PayoffNode` + `TitleOption` pydantic models; `payoff_nodes: list[PayoffNode]`,
   `title_options: list[TitleOption]`. Keep `extra="ignore"` for LLM drift tolerance. `script.json` is
   written via the model's dict dump, so on disk each title option is `{title, thumbnail_text}` — the
   ONE on-the-wire shape every downstream consumer agrees on.
2. `prompts/script_system.md`: require angle as interpretive POV (e.g. "why this was covered up / the
   forgotten lesson"), each payoff node with `surprise_score`, each title with a short punchy `thumbnail_text`.
3. `script_generator.py`: after pydantic validation, count payoff nodes with `surprise_score>=3`; if `<2`,
   `_fail_video(reason)` (mirrors existing research-reject path). This is the ONLY module that reads
   `payoff_nodes`/`title_options` as pydantic attributes (`.text`, `.surprise_score`, `.title`,
   `.thumbnail_text`) — it holds the real `ScriptOutput` object before serialization.
4. `thumbnail_generator.py`: overlay `opt["thumbnail_text"]` (dict access, loaded from `script.json`);
   keep 3 variants (pair with the 3 titles).
5. `metadata_builder.py` + `ab_variants.py`: `opt["title"]` (dict access) for the publish title + A/B
   variants. (Publisher DB-title overlay from base pipeline still wins for operator edits.)
6. `publish.py`: fix the no-script fallback from `[title] if title else []` (bare string) to
   `[{"title": title, "thumbnail_text": ""}] if title else []`; rewrite the DB-title overlay from
   `[title, *[t for t in title_options if t != title]]` (bare strings) to the dict shape:
   `[{"title": title, "thumbnail_text": ""}, *[o for o in title_options if o.get("title") != title]]`.
7. Update `content/commands.py` help/output if it prints title/payoff. Verify compile + import; a sample
   `ScriptOutput` with scored nodes validates; a `<2`-strong-payoff script is rejected; grep the whole
   tree for `title_options` / `payoff_nodes` to confirm no leftover `.title`/`list[str]` access outside
   `script_generator.py`.

## Success Criteria
- [ ] `ScriptOutput.payoff_nodes` = scored objects; `title_options` = `{title, thumbnail_text}`.
- [ ] Script with fewer than 2 payoff nodes scoring ≥3 → video FAILED with reason (no downstream steps).
- [ ] Thumbnails render `thumbnail_text` (not raw keywords); 3 variants map to the 3 titles.
- [ ] Publish title + A/B variants read `opt["title"]` (dict access); operator DB edits still override.
- [ ] `publish.py`'s no-script fallback and DB-title overlay both emit `{title, thumbnail_text}` dicts,
      never bare strings — no crash/shape-mismatch when a video has no `script_path`.
- [ ] compile + import clean; no consumer left reading the old `list[str]` shape or attribute-accessing
      a disk-loaded `title_options`/`payoff_nodes` entry.
- [ ] Key-free pytest: round-trip a sample `ScriptOutput` through `script.json` write → dict-load →
      every disk consumer (metadata_builder, thumbnail_generator, ab_variants, publish) without a
      live API key.

## Risk Assessment
- Ripple miss: a consumer still treating `title_options`/`payoff_nodes` as `list[str]`, or attribute-
  accessing a disk-loaded dict → grep all usages; import-test; the key-free round-trip test above
  catches this class of bug directly (this is exactly how `publish.py` was missed originally).
- Over-strict payoff gate stalling production: threshold (≥2 nodes ≥3) is tunable in one place; log rejections.
