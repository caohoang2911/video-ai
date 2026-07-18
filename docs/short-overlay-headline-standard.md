# Short Overlay Headline Standard

The on-screen top-band hook for YouTube Shorts. One canonical format across the pipeline,
backed by deep research (2026-07-18). Plan: `plans/260718-0341-short-overlay-white-red-headline-standard/`.

## The standard — "White-set / Red-gap Headline"

A curiosity-gap HEADLINE, **7-12 words on two lines** (split by `\n`), pinned in the top blur band.
**Each line is a PUNCHY FRAGMENT (≤6 words / ~26 chars), not a full sentence** — a long clause
overflows the frame.

- **Line 1 — setup** (off-white `#F7F7F7`): subject/action, entity-anchored enough to feel specific.
- **Line 2 — gap** (red `#D62222`): raises the stake/scale/number but **withholds the payoff** (the how/why the full video answers).

Example: `The Man Who Drowned Los Angeles` / `400 Dead, He Envied Them`.

**Render guarantees no overflow:** each line is width-wrapped to the frame; a too-long headline
degrades to a 3rd line (or smaller font) rather than bleeding off-screen. Short headlines stay 2 lines.

**Red rule:** the red line is the one bearing the first number; if no number, the last line.
Exactly one red line — emphasis works by scarcity.

**Case:** Title Case (as authored), matches the reference channel look. Config
`SHORTS_HEADLINE_CASE` (`title` | `upper`).

## Why (research-backed)

- **Inverted-U concreteness** (primary: *When curiosity gaps backfire*, Nature Sci Rep 2025):
  over-stacking entity+year+numbers **closes the gap and lowers CTR** — stay MIDDLING.
- History niche retains on short **7-12-word, 2-line** headlines; terse-fragment-only and
  payoff-first ordering were both empirically refuted. (Research range was 7-14; the prompt now
  targets the tighter 7-12 punchy-fragment band because the top end read as a full sentence and
  needed 3 lines. The schema keeps a lenient 7-14 backstop; the renderer guarantees no overflow
  regardless, so length is a quality preference, not a hard render constraint.)
- Overlay and metadata `title` are **partners, not twins**: the title carries the searchable
  entity (where search finds the short), the overlay carries the want-to-know. Mirror keywords,
  never verbatim-identical (duplicate copy cannibalizes search).
- Hook must land in the first 1-3s (swipe-decision window); the overlay is static from frame 0.

## Per-surface mapping

| Surface | Rule | Where |
|---------|------|-------|
| Long metadata title | 3 formulas, searchable entity, <60 chars | `prompts/script_system.md` |
| Long thumbnail | off-white headline + red payoff (poster) | `assembler/thumbnail_style.py` |
| Short metadata title | entity required, number optional | `content/short_script_generator.py` rule #7 |
| **Short overlay** | **this standard** (`overlay_headline`) | rule #8 + `assembler/headline_text.py` |

## Implementation

- `assembler/headline_text.py` — renders the headline as an ffmpeg `drawtext` chain (one per
  line, `expansion=none`, pixel-fit font). Called by `short_builder._pinned_title_fx`.
- `content/short_schema.py` — `overlay_headline` field (7-14-word validator); legacy
  `text_overlay` kept as render fallback (`_needs_a_hook` requires at least one).
- Render path: `burn_and_mux` `post_fx` (static over Ken Burns pan).

## Do NOT build (research-refuted)

Terse-fragment-only superiority · payoff-first ordering · overlay > title for SEO · overlay
must be shorter than title · hard 42-char/line cap · "font color lowers contrast".

## Caveats

The inverted-U primary source is web article headlines, not Shorts overlays — the *direction*
(over-anchoring hurts) is trustworthy, the numeric thresholds are not portable. Typography
(exact char/line budget, case) has no empirical backing; it is a design choice locked by A/B.
