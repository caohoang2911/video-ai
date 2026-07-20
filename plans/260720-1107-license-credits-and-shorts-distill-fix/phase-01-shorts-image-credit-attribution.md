# Phase 01 — Shorts image-credit attribution

## Context Links

- `src/ai_operator/publisher/metadata_builder.py` — description builders (main + short)
- `src/ai_operator/publisher/publish.py` — injects `script["image_credits"]` before building the upload body
- `src/ai_operator/ops/shorts_runner.py` — short production; copies parent stills into the child
- `src/ai_operator/media/asset_store.py` — writes `assets` rows, owns the `license` triple format
- `tests/test_shorts_publish_metadata.py` — pins short description layout (hashtags last line)
- `tests/test_shorts_runner.py` — reuse-vs-refetch tests

## Overview

- **Priority:** P0 — the only item in this plan with a live, already-published licence breach.
- **Status:** implemented 2026-07-20; backfill executed; manual Studio edits still outstanding.
- **Description:** Shorts publish with **zero** archival image attribution even when they carry CC BY-SA Wikimedia stills. Two independent defects: the short description builder never emits the credit block, and the parent→child still copy writes no `Asset` row. Fix both, plus a one-off backfill for shorts already rendered, plus manual Studio edits for the 2 live videos (code cannot cure those).

## Key Insights

All verified by reading the files and md5-matching rendered output against the DB.

1. **The delivery path already works and is kind-agnostic.** `publish.py:119` sets `script["image_credits"] = _image_credits(video_id)` for every video regardless of `kind`; `_image_credits` (`publish.py:155-178`) selects `Asset.license` where `kind == "archival"`, splits the `short | artist | page` triple, and emits `f"{artist} — {short} — {page}"` for anything starting `cc by`/`cc-by`, collapsing all PD files into one `"Public-domain photographs via Wikimedia Commons"` line.
2. **`build_short_description` (`metadata_builder.py:86-109`) never reads `image_credits`.** `build_description` does, at `metadata_builder.py:73-75`. So the credits reach the short's script dict and are silently dropped. **This is the load-bearing fix.**
3. **Video 25 proves point 2 in isolation.** It has 5 archival `Asset` rows of its **own** (`video_id=25`), two of them `CC BY-SA 4.0` (DeFacto; Rodhullandemu) — fetched by its own re-fetch path — and still would publish creditless. Fixing the builder alone cures 25.
4. **`_reuse_parent_images` (`shorts_runner.py:312-345`) copies with `shutil.copyfile` (line 345) and writes no `Asset` row.** Shorts 23, 29, 30, 31, 36, 38 have **no image asset rows of their own** — every md5 in their `img/` resolves to a row owned by the *parent* video. So even after fix 2 they publish creditless.
5. **Live breach (md5-verified against `assets`):**
   - video **23** (`iP_xq44_a4A`, `publish_at 2026-07-14`, past → public): `beat_05.jpg` = parent 3's `CC BY-SA 2.0 | Mike W. from Vancouver, Canada`; beats 01/04/06 are parent-3 public-domain archival.
   - video **38** (`TGy_qix1O8k`, `publish_at 2026-07-18`, past → public): `beat_04.jpg` = `CC BY-SA 3.0 | Imveracious`, `beat_06.jpg` = `CC BY-SA 2.0 | Konrad Summers`; `beat_02.jpg` = PD (Stearns, H.T. USGS).
   - Queued (rendered, never uploaded): **25** (2× CC BY-SA 4.0, own rows), **29** (CC BY-SA 3.0 unknown author + CC BY-SA 4.0 Bo Palmqvist + CC0 Janne Ranta), **30** (CC BY-SA 4.0 Mark Markefelt), **31** (CC BY-SA 4.0 Bo Palmqvist + CC0 Janne Ranta), **36** (CC BY-SA 3.0 Imveracious + PD USGS).
   - Correction to the brief: 29/30/31 also carry **CC0** and **CC BY-SA 4.0** stills, not only BY-SA 3.0/2.0. CC0 needs no credit (`_image_credits` folds it into the PD line only if it doesn't match `cc by`; `CC0` does not, so it becomes the PD provenance line — correct behaviour, no action).
6. **There is no `videos.update` code path anywhere in `src/`.** The publisher only calls `videos.insert` (`publish.py` upload step) and `thumbnails.set`. **The code fix cures nothing already published.** Videos 23 and 38 are cured only by hand in YouTube Studio.
7. **Attribution does not cure ShareAlike, and the terminated licences do not auto-reinstate.** CC BY-SA **2.0 and 3.0 have no 30-day cure clause** (that clause is CC BY-SA **4.0 § 6(a)**). The 2.0/3.0 licences on video 23 `beat_05` and video 38 `beat_04`/`beat_06` terminated automatically on first breach. Re-adding credit is a good-faith remediation, **not reinstatement** — technically it requires the licensor's express reinstatement. Practical recommendation: add the credit now (good faith, visible remedy) **and** swap those three specific images for public-domain equivalents at the next re-render of 23/38, which removes the dependency on a licence that is already gone.
8. **`_prune_stale_image_assets` (`shorts_runner.py:289-309`) deletes any `stock|archival|gen` row for the child whose md5 does not match a current `img/beat_*.jpg`.** This is why the new insert must be **md5-keyed per copied file** — bulk-copying all the parent's archival rows would both over-credit images not in the short and create rows that prune immediately deletes (churn on every `regen_short_visuals`, which calls prune at `shorts_runner.py:117`).
9. **Inserting child rows with parent md5s is safe for dedup.** `asset_store._existing_md5s` (`asset_store.py:58`) already scopes a short's dedup to parent + all siblings, so the parent's md5 is in that set either way; the added child rows change nothing.

## Requirements

Functional:
- R1. A short's description must list the CC BY / CC BY-SA credit line for every archival still visible in that short, and no others.
- R2. Copied parent stills must produce a child `Asset` row carrying the parent's `kind`, `source`, `license`, `md5`, with `url_or_path` pointing at the **child** file.
- R3. Shorts already rendered under the old code (29, 30, 31, 36) must gain their rows without re-rendering.
- R4. Videos 23 and 38 must get the credit block pasted into their live YouTube descriptions manually.

Non-functional:
- R5. Fail-open: a copied file with no matching parent row must be skipped with a log line, never abort the render.
- R6. Short description layout must not move: curiosity question stays line 1, hashtags stay the last line.
- R7. No new module; both edits fit inside existing files well under the 200-line guidance (`metadata_builder.py` 160 lines, `shorts_runner.py` 345 lines — the latter is already over, so add ≤ 25 lines and do not grow it further).

## Architecture

```
render:  _reuse_parent_images  --copy-->  output/<child>/img/beat_NN.jpg
                               --md5 lookup on parent's assets rows-->  INSERT Asset(video_id=child)
publish: _image_credits(child) --reads child's archival rows--> script["image_credits"]
                               --> build_short_description  --> description block
```

Both fixes are required; either alone leaves a gap:
- builder fix alone → only shorts that fetched their own stills (25) get credited.
- Asset-row fix alone → rows exist, description still drops them.

Credit-block placement inside the short description (`metadata_builder.py:92-108` `parts` list): question → parent link → sibling link → `#Shorts` → `music_credit` → **archival images (new)** → `AI_DISCLOSURE` → hashtags.

## Related Code Files

Modify:
- `src/ai_operator/publisher/metadata_builder.py` — `build_short_description`, insert credit block after the `music_credit` append (line 104) and before `AI_DISCLOSURE` (line 105).
- `src/ai_operator/ops/shorts_runner.py` — new private helper + call at the end of `_reuse_parent_images` (after the copy loop ending at line 345).
- `tests/test_shorts_publish_metadata.py` — add credit-block tests.
- `tests/test_shorts_runner.py` — add copy-provenance test.

Create:
- `plans/260720-1107-license-credits-and-shorts-distill-fix/backfill_copied_image_credits.py` — throwaway one-off backfill (see step 6).

Delete: none.

## Implementation Steps

1. **(Do this first, no merge required, no code involved.)** Manually edit the live descriptions in YouTube Studio. Append this block to the description of **`iP_xq44_a4A`** (video 23), positioned after the music credit and before the AI-disclosure paragraph:

   ```
   Archival images:
   - Mike W. from Vancouver, Canada — CC BY-SA 2.0 — https://commons.wikimedia.org/wiki/File:Halifax_Explosion_of_1917_(15520739377).jpg
   - Public-domain photographs via Wikimedia Commons
   ```

   And to **`TGy_qix1O8k`** (video 38):

   ```
   Archival images:
   - Imveracious — CC BY-SA 3.0 — https://commons.wikimedia.org/wiki/File:St._Francis_Dam_Disaster_Site_historical_marker.jpg
   - Konrad Summers — CC BY-SA 2.0 — https://commons.wikimedia.org/wiki/File:St._Francis_Dam_site_dike_and_landslide.jpg
   - Public-domain photographs via Wikimedia Commons
   ```

   These strings are exactly what `_image_credits` + `build_description` would emit (`f"{artist} — {short} — {page}"`, em dash U+2014). Do not wait for the code fix; nothing in `src/` can perform this edit.

2. **`build_short_description`** — after the `music_credit` append and before `parts.append(AI_DISCLOSURE)`:

   ```python
   image_credits = script.get("image_credits") or []
   if image_credits:
       parts.append("Archival images:\n" + "\n".join(f"- {c}" for c in image_credits))
   ```

   Comment must state the WHY: per-file Wikimedia licences require the credit wherever the image is used, including the vertical cut. Keep it before `AI_DISCLOSURE` so the disclosure stays adjacent to the hashtag line and the question stays first.

3. **`shorts_runner`** — add a helper next to `_prune_stale_image_assets`:

   ```python
   def _credit_copied_images(parent_id: int, child_id: int) -> None:
       """Mirror the parent's licence rows onto the stills copied into the child.

       Publish builds the archival credit block from the CHILD's asset rows, so a copied
       still with no row publishes uncredited — a licence breach for CC BY-SA files. Keyed
       on file md5 (not beat index) so only images actually on screen get credited and the
       stale-row prune keeps them."""
   ```

   Body: read every `output/<child>/img/beat_*.jpg`, md5 it, build `{md5: child_path}`; load parent rows `select(Asset).where(Asset.video_id == parent_id, Asset.kind.in_(_IMAGE_ASSET_KINDS))`; load existing child md5s to stay idempotent; for each md5 present in both, insert `Asset(video_id=child_id, kind=row.kind, source=row.source, url_or_path=str(child_path), license=row.license, md5=md5)`. Skip (and `log.debug`) any md5 with no parent row. Wrap the whole body in `try/except Exception` → `log.warning` so a DB hiccup never fails an otherwise-good render (R5).

4. Call `_credit_copied_images(parent_id, child_id)` on the last line of `_reuse_parent_images`, **after** the copy loop finishes — not inside it, so one DB session covers all beats.

5. **Tests.**
   - `tests/test_shorts_publish_metadata.py`: (a) `build_short_description` with `image_credits` present emits each credit line; (b) with `image_credits` present the **last** line is still the hashtag line — this guards the existing pin at `tests/test_shorts_publish_metadata.py:18-19`; (c) empty/missing `image_credits` produces no `Archival images:` heading.
   - `tests/test_shorts_runner.py`: given a parent with an archival row for a known file, `_reuse_parent_images` leaves the child with a row whose `md5` matches the copied file, whose `license` equals the parent's verbatim, and whose `url_or_path` contains the child id; a parent file with no row inserts nothing and does not raise.
   - Test names describe the scenario only — no plan or finding references.

6. **Backfill 29, 30, 31, 36** as a **throwaway script** at `plans/260720-1107-license-credits-and-shorts-distill-fix/backfill_copied_image_credits.py`, ~20 lines: `for child_id in (29, 30, 31, 36): _credit_copied_images(parent_id_of(child_id), child_id)`, reusing the step-3 helper (parent ids: 29/30/31→28, 36→35). Justification for script over CLI subcommand: the render path self-credits from now on, so this runs exactly once; a `typer` subcommand is permanent public surface for a one-shot job (YAGNI), and the CLI mounts phase modules that would then have to carry dead code forever. Video 25 needs no backfill — it already owns its rows. Video 23 and 38 rows can be backfilled too (harmless, keeps the audit trail consistent) but that does **not** change their live descriptions; step 1 is the only remedy there.
7. Verify with a read-only query that each backfilled short has rows whose md5 set equals its on-disk still md5 set, then re-check that a `regen_short_visuals` dry pass would not prune them (md5s match files).
8. Docs impact: none (no user-facing surface changes). Do not touch `docs/`.

## Operator Decisions (2026-07-20)

- **CC BY-SA remediation:** credit and keep the images. PD swap is NOT scheduled — recorded as a standing follow-up, not a task.
- **Parent-to-short image reuse:** reuse stays (shorts are cuts of the parent), but one image must not span several shorts of the same family. Scope grew by one item: seed the batch ledger from the shorts a parent already has on disk.
- **Backfill scope:** all shorts missing image rows, not only the CC BY-SA ones. The discovery query found **15** (10, 11, 12, 16, 17, 18, 22, 23, 24, 29, 30, 31, 34, 36, 38), all 6/6 stills credited. This settles Unresolved Question 1 below: published shorts WERE backfilled, deliberately, for audit-trail consistency — it changes nothing on YouTube.

## Deviations From Plan (as built)

1. **Extracted a module instead of a private helper.** Plan put `_credit_copied_images` inside `shorts_runner`. Built as `src/ai_operator/ops/shorts_image_provenance.py` with `output_dir` injected, because `shorts_runner` was already 345 lines and the tests monkeypatch its module-level `OUTPUT_DIR` — a second module reading config directly would have silently escaped that patch. Reviewer approved the deviation.
2. **Added sibling-image seeding** (`beats_used_by_siblings`), per the operator decision above. Not in the original plan.
3. **`_distinct_still_count` now delegates to `still_md5s`**, taking `(video_id, output_dir)`; the duplicated hashing loop and the `hashlib` import left `shorts_runner`.
4. **`credit_copied_images` takes `child_id` / `output_dir` keyword-only** — both ids are plain ints and transposing them would credit the wrong video.
5. **Failure path logs at ERROR with `exc_info`,** not WARNING: `health.recent_errors` only tails ERROR/ALERT, so a warning would have made an uncredited publish both silent and invisible.
6. **`beats_used_by_siblings` builds its own `md5 -> set[int]` map** rather than reusing `still_md5s`, whose `setdefault` collapses duplicate-content files — that collapse would leave a duplicate twin looking unused and pickable again.

## Todo List

- [ ] Paste the archival-credit block into `iP_xq44_a4A` and `TGy_qix1O8k` in YouTube Studio (step 1, independent of merge)
- [x] Emit `image_credits` from `build_short_description`
- [x] Add the provenance helper and call it from `_reuse_parent_images`
- [x] Tests: short description credit block + hashtag-last invariant
- [x] Tests: copy path writes content-keyed child asset row; missing parent row is a no-op
- [x] Run the one-off backfill (15 shorts, all missing image rows)
- [x] Verify backfilled hash sets match on-disk stills (15/15 clean)
- [x] Decide on PD swaps — operator chose credit-and-keep; PD swap not scheduled
- [x] Seed the batch ledger from siblings already on disk (added scope)
- [ ] Audit whether any MAIN published before the credit block existed has the same gap

## Success Criteria

- Rendering a new short off a parent that has stills leaves the child with one `Asset` row per distinct still, `url_or_path` under `output/<child>/img/`, `license` byte-identical to the parent row.
- `build_short_description` on a script with `image_credits` contains `Archival images:` and every credit line; `desc.splitlines()[-1]` is still the hashtag line.
- Shorts 25, 29, 30, 31, 36 would upload with a non-empty archival credit block (check by loading their script.json + running `_image_credits` read-only — no upload).
- Videos 23 and 38 show the credit block in their live YouTube description.
- Full test suite green.

## Risk Assessment

| Risk | Mitigation |
| --- | --- |
| Credit block pushes description past `MAX_DESCRIPTION_LEN` (5000) | Shorts descriptions are ~10 lines; the builder already truncates at line 109. No action, just don't reorder so hashtags get cut. |
| Duplicate rows if the helper runs twice (re-render, backfill after fix) | Skip md5s already present on the child; helper is idempotent. |
| Over-crediting images not on screen | Md5-keyed per file, never bulk row copy. |
| Rows deleted again by `_prune_stale_image_assets` | Rows carry the real file md5, so prune keeps them by construction; assert this in the regen test. |
| DB write failure aborts a good render | Whole helper is fail-open (`try/except` + warning). |
| ShareAlike obligation still unmet | Out of scope of attribution; see Key Insight 7 — plan a PD swap. |

## Security Considerations

None new. No credential, network, or user-input surface is touched. The backfill script is read-mostly (inserts only) and must be run against the live DB deliberately, not from a hook or scheduler.

## Next Steps

- Dependency: none — this phase is self-contained and should ship first.
- Merge overlap: phase 03 also edits `build_short_description` in `metadata_builder.py` and adds cases to `tests/test_shorts_publish_metadata.py`. Neither changes the function signature, so order does not matter, but whoever lands second rebases those two files.
- Follow-up: at the next re-render of videos 23 and 38, replace the CC BY-SA 2.0/3.0 stills with public-domain equivalents (both events have deep PD coverage on Commons), removing reliance on terminated licences.
- Follow-up: consider whether main videos rendered before the archival credit block existed have the same gap (not audited here).

## Unresolved Questions

1. Should the backfill also insert rows for the two published shorts (23, 38)? It fixes the internal audit trail but changes nothing on YouTube — cosmetic vs. leave-history-as-was.
2. Any appetite for a licensor notification (Commons talk page) for the three terminated BY-SA files, or is the credit + PD swap considered sufficient?
3. Main videos published before the credit block landed — was any main ever uploaded without `image_credits`? Not audited; needs a separate pass over `uploads` + `assets`.
