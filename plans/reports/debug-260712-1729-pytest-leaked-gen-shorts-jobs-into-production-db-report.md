# Pytest leaked gen-shorts jobs into production DB — root cause & fix

## Symptom
Mysterious `gen-shorts` job pairs for videos #10/#11 (both kind=short, children of #9)
appearing repeatedly in the real jobs queue (22 rows total). Each done in ~1s (no-op:
"shorts never spawn shorts"). Timestamps matched every full pytest run.

## Root cause (verified via operator.log + DB forensics)
- `test_content_quality_gates.py` publish tests built a PRIVATE SQLite factory and
  monkeypatched only `pub_mod.SessionLocal` — did NOT use `temp_db`.
- They seed Video id=10/11 (kind defaults "main", no children) and call `publish()`.
- `publish()` → `_try_enqueue_shorts()`: guards read the PATCHED session (test db) → pass.
- Inner `job_queue.enqueue()` uses the SHARED sessionmaker — unpatched, still bound to real
  `data/*.db` → real pending gen-shorts jobs inserted. Live scheduler drained them ~20s later.
- Harmless ONLY because real #10/#11 happen to be shorts (runner kind-guard no-ops). Had they
  been mains without children, every pytest run would trigger REAL shorts production
  (LLM + ElevenLabs chars at 90% quota + render + Telegram).

## Fix applied
1. `tests/conftest.py`: autouse `_no_production_db` fixture — binds shared SessionLocal to an
   EMPTY in-memory engine (no schema) for every test. Forgotten-fixture DB access now fails
   loudly ("no such table") instead of leaking. `temp_db`/`temp_db_fk` layer on top and
   restore to the GUARD (not the real engine) on teardown — no leak window during teardowns.
2. Both publish tests now request `temp_db` so the gen-shorts auto-enqueue path exercises a
   real schema instead of being silently swallowed.
3. Deleted 22 junk done gen-shorts rows (video 10/11) from real DB. Verified post-fix full
   suite (256 passed) created zero new job rows (MAX(id) unchanged at 62).

## Related session context
- Video #3 recovery confirmed: assemble job 62 done 17:28 — final.mp4 rebuilt with new
  ElevenLabs voice; awaiting re-review PASS_POLICY → PASS_QUALITY.

## Unresolved questions
- Pytest still appends to the real `output/logs/operator.log` (test log lines interleave with
  prod — confused this investigation). Optional follow-up: point LOG_DIR at tmp during tests.
- 2 stray "cancelled" jobs (43/44) predate this; unrelated, left as history.
