# Phase 04 — Sibling Shorts Cross-Linking + Publish Spacing (OPTIONAL)

Priority: LOW-MEDIUM | Status: done | Effort: S (~2-4h) | Independent

## Context links

- `src/ai_operator/publisher/publish.py:51-67` — parent-first hard gate already exists
- `src/ai_operator/publisher/metadata_builder.py:86-94` — description already carries parent funnel link
- `src/ai_operator/ops/scheduler.py:127` — publish scan every 6h, char/cap gated
- Internal evidence: Halifax trio = the "mini-series" the advisor proposed, already shipped

## Assessment (honest)

Advisor's mini-series idea is ALREADY the pipeline's structure (batch shorts per parent,
protected-reveal contract, parent-first publish). Remaining deltas are packaging only. Expected
lift is modest vs Phases 1-3; do this last or skip until analytics justify it.

Deliberately rejected (YAGNI, keep rejected unless data says otherwise):
- "Part 1/2/3" titles — shorts are feed-served standalone; explicit sequencing depresses CTR mid-series.
- Playlist automation — Shorts shelf doesn't surface playlists meaningfully.

## Requirements

1. Sibling spacing policy: verify current publish scan order can emit 2 sibling shorts in the same
   6h window; if yes, add min-gap rule (e.g. >=24h between shorts of the same parent) in the publish
   candidate selection — spreads the series, each short gets its own feed test window.
2. Sibling cross-link: when a sibling short is already live, append one line to description
   ("More on this disaster: <short url>") in `metadata_builder`. Only backward-links (new → older
   live sibling); never edit already-published descriptions automatically.
3. Keep parent link primary; sibling link is one line max (description links are tertiary per research).

## Related code files

- Modify: `publisher/publish.py` (candidate selection min-gap), `publisher/metadata_builder.py`
- Tests: extend existing publisher tests; spacing unit test with fixture uploads at varying timestamps

## Implementation steps

1. Read publish candidate query; confirm/add same-parent min-gap filter.
2. Sibling lookup (uploads join on parent_id) in metadata build; append line when >=1 live sibling.
3. Tests for both.

## Success criteria

- Two ready siblings never publish within 24h of each other.
- Third short of a trio ships with parent link + one sibling link in description.

## Risks

- Description edit churn: rule 2 applies at publish time only — zero risk to live videos.
- Over-linking spam signal: cap at 1 sibling link.
