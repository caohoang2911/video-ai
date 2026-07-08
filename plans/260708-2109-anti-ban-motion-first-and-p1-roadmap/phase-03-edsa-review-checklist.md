---
phase: 3
title: "EDSA review checklist"
status: done
priority: P1
effort: "1-2h"
dependencies: [1]
---

# Phase 3: EDSA review checklist

## Overview
Add an EDSA (Educational/Documentary/Scientific/Artistic) checklist to the TIER-1 policy review so the
reviewer confirms the narration itself states who/what/when/where/why — the concrete signal that earns
YouTube's documentary exception. Also hard-block approval of any `needs_revoice` video.

## Requirements
- Functional: review UI surfaces EDSA tickboxes (who/what/when/where/why said in AUDIO, not just metadata)
  + hook-present + payoff-present; approval (PASS_POLICY/PASS_QUALITY) is blocked while `needs_revoice=True`.
- Non-functional: no new tables (reuse `decisions`); callback_data ≤64 bytes; single-instance safe.

## Architecture
Extends `review/checklist.py` (already renders an inline tickbox message) with EDSA items. The block on
`needs_revoice` lives in `review/callbacks.py`'s `handle_callback`, BEFORE the existing unconditional
`await query.answer()` — Telegram allows exactly ONE `answer()` per callback query, so the check must
parse `code`/`video_id` and short-circuit with its OWN single `query.answer(..., show_alert=True)` +
`return` ahead of the handler's general `answer()` call. It must NOT live in `decision_store.py`: that
path runs after `handle_callback` has already answered the query once, so a second `answer()` there
raises. EDSA answers are informational (logged), not a hard gate, to avoid rubber-stamp friction.

## Related Code Files
- Modify: `src/ai_operator/review/checklist.py` (add EDSA rows: who/what/when/where/why-in-narration, hook, payoff)
- Modify: `src/ai_operator/review/callbacks.py` (in `handle_callback`, move `code`/`video_id` parsing
  above the existing unconditional `await query.answer()`; refuse PASS_POLICY/PASS_QUALITY when
  `Video.needs_revoice` with a single alert-answer + early return, before that unconditional answer fires)
- Modify: `src/ai_operator/review/caption.py` (surface a `⚠ needs re-voice` line when set — plain text)

## Implementation Steps
1. `checklist.py`: add EDSA tickbox rows to the inline checklist keyboard/message; label them clearly
   (e.g. "Narration states WHO/WHAT/WHEN/WHERE/WHY?"). Toggling logs to `decisions` (tier=policy) or is display-only.
2. `callbacks.py`: in `handle_callback`, parse `code`/`video_id` from `query.data` FIRST — ahead of the
   existing unconditional `await query.answer()`. If `code in (PASS_POLICY, PASS_QUALITY)` and
   `Video.needs_revoice` → `await query.answer("Blocked: run revoice first", show_alert=True)` as the
   SINGLE answer for this callback, then `return` immediately (no state change, no `decision_finalize`
   call). Otherwise fall through unchanged to the existing unconditional `await query.answer()` and the
   rest of the dispatch (menu taps, checklist toggles, terminal decisions).
3. `caption.py`: append a plain-text `⚠ needs re-voice` marker when `video.needs_revoice` so the reviewer sees it.
4. Verify: compile + import; a `needs_revoice` video's PASS_POLICY/PASS_QUALITY tap is blocked with a
   single alert and no `InvalidTransition`/double-answer error; EDSA rows render; non-PASS taps (menu,
   checklist toggle, REJECT_*) are unaffected.

## Success Criteria
- [ ] TIER-1 review message shows EDSA (who/what/when/where/why-in-narration) + hook + payoff checklist rows.
- [ ] Attempting to approve a `needs_revoice=True` video is blocked with a clear alert; state unchanged.
- [ ] The block fires exactly once per query (no duplicate `query.answer()` call/exception).
- [ ] Caption shows the re-voice warning when applicable.
- [ ] Key-free pytest: drive `handle_callback` with a mocked `query`/`Update` for a `needs_revoice=True`
      video and assert a single `answer(show_alert=True)` call + no state transition; no live API key needed.
- [ ] compile + import clean; `decisions` schema unchanged (no new columns).

## Risk Assessment
- Checklist friction → rubber-stamp: keep EDSA informational; the existing weekly rubber-stamp alert still applies.
- Depends on Phase 1's `needs_revoice` column — sequence after Phase 1.
