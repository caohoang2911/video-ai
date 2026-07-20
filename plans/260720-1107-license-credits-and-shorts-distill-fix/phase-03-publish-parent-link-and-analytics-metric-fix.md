# Phase 03 — Publish parent-link gating + analytics CTR metric bug

## Context Links

- `src/ai_operator/publisher/publish.py` — short publish path, parent lookup, uploads row insert
- `src/ai_operator/publisher/metadata_builder.py` — `build_short_description`, `build_upload_body`
- `src/ai_operator/ops/scheduler.py` — `publish_job` (6h interval, swallows exceptions)
- `src/ai_operator/ops/analytics_puller.py` — `_query_ctr`, `_CTR_METRICS`, `RETENTION_MIN_VIEWS`
- `src/ai_operator/ops/validation.py`, `src/ai_operator/ops/health.py`, `src/ai_operator/web/analytics_view.py` — CTR consumers
- `output/logs/operator.log:2535-2538, 5051-5066` — the recurring HTTP 400 from the CTR query
- YouTube Analytics API v2 metric list: https://developers.google.com/youtube/analytics/metrics

## Overview

- **Priority:** P1
- **Status:** not started
- **Description:** Two small, independent fixes in the publish/analytics path. (A) A child Short must not print a "Full video" link when the parent's scheduled go-live is still in the future — omit the line instead of shipping a link that 404s for viewers. (B) The analytics CTR query uses metric identifiers that do not exist in YouTube Analytics API v2; it returns HTTP 400 on every call and has never produced a value. Remove it.

Both fixes are self-contained; they can be implemented and reviewed in either order and touch disjoint files.

## Key Insights

All claims below were verified by opening the files / querying the DB / reading the log.

1. **The parent gate checks existence only, not go-live.** `publish.py:62-64` selects `Upload.youtube_video_id WHERE Upload.video_id == parent_id` and `:65-69` raises if there is no row. Nothing consults the parent's `publish_at`. The comment at `:57-58` already states the intent ("publishing one before the parent is live would ship a dead link") — the code only enforces "uploaded", not "live".
2. **The correct rule already exists one block away.** The sibling-short query at `publish.py:75-81` filters `(Upload.publish_at.is_(None)) | (Upload.publish_at <= now)` with the comment at `:72-73`: "A sibling still scheduled in the future is skipped -- its link would 404 (private) until its publish_at passes." Same reasoning, not applied to the parent.
3. **A raise would head-of-line-block the publish queue — verified.** `scheduler.py:_next_approved_video_id` orders by `Video.id` and returns the FIRST eligible candidate (`scheduler.py:139-147`); `publish_job` calls `publish(...)` inside `try/except Exception` and only logs (`scheduler.py:172-176`); the job runs on `"interval", hours=6` (`scheduler.py:201`). So a raising short is re-selected and re-fails every 6h forever, and every later-id approved video never gets its turn. Hence: **do not raise, do not move any timestamp** — pass `parent_youtube_id=None`.
4. **`None` already means "omit the line".** `metadata_builder.build_short_description` (`:86-99`) guards `if parent_youtube_id:` before appending `▶ Full video: ...`, and `build_upload_body` (`:124-143`) takes `parent_youtube_id: str | None = None` and forwards it. No signature change needed anywhere.
5. **`uploads.publish_at` / `privacy` / `status` are write-once and never reconciled.** They are set at insert (`publish.py:194-203`: `privacy="private"`, `status="scheduled"`) and no code path ever updates them against YouTube. DB confirms: `SELECT privacy,status,count(*) FROM uploads GROUP BY 1,2` → `private|scheduled|19` (all 19 rows). So the field records **intent, not fact**.
   - Trade-off: the gate is **conservative** — for a video that is actually live but whose recorded `publish_at` is still in the future (e.g. someone flipped it public early in Studio), the link is omitted. Cost = one missing funnel link on one Short. The opposite error (linking a still-private video) costs a visibly broken link in a published description that is **never edited afterwards** (see `publish.py:70-71`: "published descriptions are never edited"). Asymmetric cost → conservative is correct.
   - The missing reconciliation of `privacy`/`status` against YouTube is real debt, but it is **out of scope here** and recorded below.
6. **The CTR metrics do not exist — confirmed twice.** `analytics_puller.py:27` sets `_CTR_METRICS = "impressions,impressionsClickThroughRate"`, used at `:65`. The log shows, for every video on every run (e.g. `operator.log:5051`, `:5058`, `:5066`):
   `HttpError 400 ... "Unknown identifier (impressions) given in field parameters.metrics."`
   The official metric list has no `impressionsClickThroughRate` at all, and `impressions` was renamed `adImpressions` (verified ad impressions — a monetization metric, unrelated to thumbnail impressions). Thumbnail impressions + CTR are **Studio-only**; they are not exposed by Analytics API v2 (also absent from the Looker Studio YouTube connector, which is backed by the same API).
7. **The bug is 100% silent and permanent.** `_query_ctr` swallows the error at `:67-69` and returns `None`, so `metrics["ctr"]` is never set (`:147-149`) and `_upsert` leaves the model default (`:121-122`, default `0.0` at `db/models_ops.py:34`). DB confirms: `SELECT ctr,count(*) FROM analytics GROUP BY ctr` → `0.0|61` — every row, no exceptions. One wasted API round-trip per video per day, forever.
8. **All CTR consumers already treat 0 as "unmeasured"** — removing the query changes no downstream behaviour:
   - `ops/validation.py:119` — `ctr_measured = any(r["ctr"] > 0 for r in rows)`, and `:155` only applies `PASS_CTR_PCT` when `ctr_measured`.
   - `ops/health.py:166` — `ctr = f"..." if a['avg_ctr'] else "n/a"  # 0 = CTR not measured yet`.
   - `web/analytics_view.py:64-65` — `if a.ctr:` before appending to the trend series.
   - Existing tests already lock this in: `tests/test_ops_validation.py:128` (`test_uncollected_ctr_does_not_block_strong_pass`) and `tests/test_ops_health.py:176` (`test_render_shows_ctr_na_when_uncollected`).
9. **Do NOT lower `RETENTION_MIN_VIEWS`** (`analytics_puller.py:32`, value `200`). The gate is already satisfied: `SELECT count(*), count(distinct youtube_video_id) FROM retention_curve` → `300` rows across `3` videos, and the top short has 928 lifetime views. Lowering it would only add noise buckets. Explicit do-not-change.

## Requirements

Functional:
- R1: When a Short's parent has an `uploads` row whose recorded `publish_at` is in the future, the Short's description must not contain the `▶ Full video:` line.
- R2: When the parent's `publish_at` is `NULL` or `<= now`, behaviour is unchanged (link present).
- R3: The existing hard failure when the parent has **no** `uploads` row at all stays exactly as is (`publish.py:65-69`).
- R4: `publish()` must not raise for the "parent scheduled in the future" case, and must not mutate any `publish_at`.
- R5: The analytics pull must stop issuing the invalid CTR request. `analytics.ctr` stays in the schema at its `0.0` default.

Non-functional:
- N1: No change to `build_short_description` / `build_upload_body` signatures.
- N2: No new files; both edits are in-place and small. Files stay under ~200 lines.
- N3: No code comment, test name, or filename may reference this plan, phases, or finding codes — comments state the invariant only.

## Architecture

Fix A, inside the single read session in `publish()`:

```
kind == "short"
  └─ SELECT youtube_video_id, publish_at FROM uploads WHERE video_id = parent_id
       ├─ no row                     -> raise (unchanged: parent not on YouTube at all)
       ├─ publish_at > now           -> parent_youtube_id = None   # link omitted, publish proceeds
       └─ publish_at NULL or <= now  -> parent_youtube_id = <id>   # link rendered
                                              │
                     build_upload_body(..., parent_youtube_id=…) -> build_short_description
                                              └─ `if parent_youtube_id:` already omits the line
```

`now` is the same `datetime.now(timezone.utc)` already computed for the sibling query — reuse it (hoist above the parent block) so parent and sibling gates share one instant. DRY.

Fix B: delete the `_query_ctr` code path. `pull_all` keeps writing `views` / `watch_time_min` / `avg_view_pct`; `_upsert`'s `if metrics.get("ctr") is not None` branch (`:121-122`) **stays** — it costs nothing and leaves the door open for a future manual/Studio backfill writing into the same column.

## Related Code Files

Modify:
- `src/ai_operator/publisher/publish.py` — parent lookup at `:59-69`; hoist `now` currently at `:74`
- `src/ai_operator/ops/analytics_puller.py` — remove `_CTR_METRICS` (`:24-27`, incl. its comment), `_query_ctr` (`:56-74`), call site (`:147-149`)
- `tests/test_shorts_publish_metadata.py` — pure `metadata_builder` unit module (no DB, no monkeypatch); it can only cover the *builder* side, i.e. `parent_youtube_id=None` omits the link (`:31` already exercises the populated case). The parent-gate tests must drive `publish()` against a real SQLite round-trip, so they belong in a DB-backed module — reuse the session fixture from an existing DB-driven test module (e.g. the shorts-runner or publish tests) rather than adding DB machinery to a pure-unit file.
- `tests/test_ops_analytics_puller.py` — delete the three `_query_ctr` tests (`:64-81`, including the section banner); update the module docstring at `:3-4` which currently advertises "CTR parsing/scale"; update the stale comment at `:111` only if it still reads oddly

Create: none.

Delete: none (no whole file is removed).

## Implementation Steps

1. In `publish.py`, move `now = datetime.now(timezone.utc)` from inside the sibling block (currently `:74`) up to just before the parent lookup, so both gates share one instant.
2. Replace the parent lookup (`:62-64`) with a row fetch that also returns the recorded go-live, e.g.
   `s.execute(select(Upload.youtube_video_id, Upload.publish_at).where(Upload.video_id == parent_id).order_by(Upload.id.desc())).first()`
   (`.desc()` mirrors the `existing` lookup at `:51-54`: newest row wins if a video was ever re-uploaded.)
3. Keep the raise (`:65-69`) for "no row / no youtube id" — unchanged message.
4. Add the go-live gate: if the fetched `publish_at` is not None and is in the future, set `parent_youtube_id = None` and `log.info(...)` that the parent link was omitted (include video_id + parent_id — this is the only externally visible symptom, so it must be greppable).
   - Naive/aware guard: `Upload.publish_at` round-trips from SQLite as a **naive** datetime. Compare safely (e.g. attach `timezone.utc` when `tzinfo is None`) or the comparison raises `TypeError`. Verify against a real row before finishing.
5. Rewrite the comment at `:57-58` to state the invariant: a Short's funnel link must point at something a viewer can actually open, so an uploaded-but-not-yet-live parent contributes no link; and note the field records scheduled intent, so the gate errs toward omitting.
6. In `analytics_puller.py`: delete `_CTR_METRICS` and its comment (`:24-27`), delete `_query_ctr` (`:56-74`), delete the call site (`:147-149`). Also scrub the two dangling back-references that would otherwise point at a deleted function: the retention comment at `:28-30` and the `_query_retention` docstring at `:79`, both of which read "Optional like CTR". Leave `_upsert`'s ctr branch and the `Analytics.ctr` column untouched.
7. Add a short comment at the `Analytics.ctr` write site (or above `_METRICS`) recording WHY there is no CTR query: thumbnail impressions and click-through rate are Studio-only and not exposed by the Analytics API, so the column stays 0 = unmeasured. Do **not** name the removed metric identifiers in the comment — the success criterion greps for them.
8. Delete `tests/test_ops_analytics_puller.py:64-81` and fix the module docstring; keep the three `_upsert` ctr tests (`:89-115`) — they still guard the "0 = unmeasured" contract.
9. New tests for Fix A:
   - parent upload with `publish_at` in the future → rendered short description contains no `youtu.be/` parent link, and `publish()` does **not** raise;
   - parent upload with `publish_at` in the past → link present (regression guard);
   - parent upload with `publish_at IS NULL` → link present;
   - parent with no upload row → still raises.
10. Run `pytest tests/` in full (the suite is ~479 tests; both edits touch shared paths).

## Todo List

- [ ] Hoist `now` above the parent lookup in `publish.py`
- [ ] Fetch `(youtube_video_id, publish_at)` for the parent, newest row first
- [ ] Keep the no-parent-row raise unchanged
- [ ] Set `parent_youtube_id = None` when the parent's recorded go-live is in the future + log it
- [ ] Handle naive/aware datetime comparison for `Upload.publish_at`
- [ ] Rewrite the parent-block comment to state the invariant (no plan refs)
- [ ] Remove `_CTR_METRICS`, `_query_ctr`, and the call site in `analytics_puller.py`
- [ ] Add the "CTR is not API-exposed; 0 = unmeasured" comment
- [ ] Delete the three `_query_ctr` tests + fix the test module docstring
- [ ] Add the four parent-gate tests
- [ ] Full `pytest tests/` green
- [ ] Confirm the next analytics run logs no `Unknown identifier (impressions)` 400

## Success Criteria

- Publishing a Short whose parent is scheduled in the future succeeds, and the resulting description has no `▶ Full video:` line; a log line records the omission.
- The publish queue never stalls on this condition (no exception path added).
- Parent live / `publish_at` NULL → description unchanged from today, byte-for-byte.
- `grep -rn "impressionsClickThroughRate" src tests` returns nothing (this is why step 7's comment must describe the metric in prose, not by identifier).
- After one analytics run, `output/logs/operator.log` gains zero `Unknown identifier (impressions)` entries, and the per-video pull latency drops by one API round-trip per video.
- `analytics.ctr` values are unchanged (all `0.0`); dashboard shows `n/a` / validation still non-blocking.
- Full test suite green.

## Risk Assessment

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Naive vs aware datetime comparison raises `TypeError` inside `publish()` — swallowed by `scheduler.py:175`, so every short silently fails to publish | Medium | Explicit tz normalization + a test using a real DB round-trip, not an in-memory object |
| Conservative gate omits a link for a parent that is actually already live (intent ≠ fact, see Key Insight 5) | Low-Medium | Accepted: one missing link ≪ one permanent dead link. Revisit if/when upload reconciliation lands |
| Removing `_query_ctr` looks like "losing a metric" to a future reader | Medium | The WHY comment (step 7) plus this phase file; the column and its 0-means-unmeasured semantics stay |
| `.order_by(Upload.id.desc())` changes which row is read for a parent with multiple uploads | Low | Matches the existing `existing` lookup (`publish.py:51-54`); today no video has more than one upload row |

Known debt logged, not fixed here: `uploads.privacy` and `uploads.status` are written once at insert and never reconciled against YouTube — all 19 rows still read `private/scheduled` even for videos that have gone live. Any future feature that needs *actual* live state (not scheduled intent) must add a reconciliation pull first.

Explicit do-not-change: `RETENTION_MIN_VIEWS = 200` (`analytics_puller.py:32`) stays. The gate is already satisfied (300 curve rows / 3 videos).

## Security Considerations

- No new external input, no new credentials, no new network calls. Fix B strictly removes one authenticated API request per video per day (smaller quota and attack surface).
- The omitted-link log line must contain only internal ids (`video_id`, `parent_id`) and at most the parent's YouTube id — no tokens, no OAuth material.
- Fix A can only ever *remove* a URL from a published description; it cannot introduce an attacker-controlled link.

## Next Steps

- Depends on: nothing. Both fixes are independent of the other phases in this plan.
- Follow-up (separate work): reconcile `uploads.privacy` / `uploads.status` against YouTube so "is it live?" can be answered from fact rather than intent — that would also let Fix A's gate become exact.
- Follow-up (optional): if thumbnail CTR is ever wanted, it must come from a manual Studio export written into `analytics.ctr`; the `_upsert` branch already supports that write.

## Unresolved Questions

1. Should the omitted-link case also raise an operator alert (`ops/alerting.alert`) rather than only `log.info`? It is silent-by-design today; an alert would surface a scheduling ordering mistake earlier.
2. Should the "no upload row at all" case likewise stop raising (it head-of-line-blocks the queue by exactly the same mechanism described in Key Insight 3)? Out of scope per triage, but it is the same defect class.
