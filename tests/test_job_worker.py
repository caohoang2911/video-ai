"""Consumer side: DISPATCH<->allowlist parity, atomic claim, sequential exactly-once
execution, and failure isolation (a raising handler fails only its own job)."""

from __future__ import annotations

from ai_operator.db.engine import SessionLocal
from ai_operator.db.models_ops import Job
from ai_operator.ops import job_worker
from ai_operator.web.job_queue import JOB_COMMANDS


def _seed(command: str, **kw) -> int:
    with SessionLocal() as s:
        job = Job(command=command, idempotency_key=f"{command}-{kw}", **kw)
        s.add(job)
        s.commit()
        return job.id


def test_dispatch_matches_allowlist():
    assert set(job_worker.DISPATCH) == set(JOB_COMMANDS)


def test_claim_next_returns_none_on_empty_queue(temp_db):
    assert job_worker.claim_next() is None


def test_jobs_run_sequentially_in_id_order_exactly_once(temp_db, monkeypatch):
    order: list[int] = []
    monkeypatch.setitem(job_worker.DISPATCH, "pull-analytics", lambda job: order.append(job.id))
    monkeypatch.setitem(job_worker.DISPATCH, "gen-topics", lambda job: order.append(job.id))
    a = _seed("pull-analytics")
    b = _seed("gen-topics")

    ran = job_worker.drain_jobs()

    assert ran == 2
    assert order == [a, b]                       # id order, each exactly once
    with SessionLocal() as s:
        rows = {j.id: j for j in s.query(Job).all()}
    assert rows[a].status == "done" and rows[a].finished_at is not None
    assert rows[b].status == "done" and rows[b].started_at is not None


def test_a_raising_handler_marks_only_its_job_failed(temp_db, monkeypatch):
    def _boom(job):
        raise RuntimeError("provider exploded")

    monkeypatch.setitem(job_worker.DISPATCH, "publish", _boom)
    monkeypatch.setitem(job_worker.DISPATCH, "pull-analytics", lambda job: None)
    bad = _seed("publish")
    good = _seed("pull-analytics")

    ran = job_worker.drain_jobs()          # must NOT raise

    assert ran == 2
    with SessionLocal() as s:
        rows = {j.id: j for j in s.query(Job).all()}
    assert rows[bad].status == "failed" and "provider exploded" in rows[bad].error
    assert rows[good].status == "done"     # failure isolated to the bad job


def test_requeue_orphaned_running_jobs_after_restart(temp_db):
    # simulate a job left `running` by a crashed/restarted process
    orphan = _seed("assemble")
    with SessionLocal() as s:
        s.get(Job, orphan).status = "running"
        s.commit()

    n = job_worker.requeue_orphaned_jobs()

    assert n == 1
    with SessionLocal() as s:
        row = s.get(Job, orphan)
    assert row.status == "pending" and row.started_at is None  # reclaimable again
    # and it can now be re-run
    assert job_worker.claim_next() is not None


def test_claim_flips_pending_to_running(temp_db, monkeypatch):
    # a handler that inspects its own row mid-run sees status=running (claim happened first)
    seen: list[str] = []

    def _check(job):
        with SessionLocal() as s:
            seen.append(s.get(Job, job.id).status)

    monkeypatch.setitem(job_worker.DISPATCH, "pull-analytics", _check)
    _seed("pull-analytics")
    job_worker.drain_jobs()
    assert seen == ["running"]


def test_gen_visuals_handler_passes_every_typer_option_explicitly(monkeypatch):
    """Calling a typer command as a plain function leaves unpassed options as OptionInfo
    objects, which are TRUTHY — an unset `gen_all` silently forced every queued
    gen-visuals run into all-SDXL mode (skipping the archival/stock tiers). The handler
    must therefore pass real booleans for every option."""
    captured = {}
    monkeypatch.setattr(
        job_worker.media_commands, "gen_visuals",
        lambda **kw: captured.update(kw),
    )
    job = Job(command="gen-visuals", video_id=7, params={"motion": False}, status="running",
              idempotency_key="k-genvis-typer-trap")
    job_worker._gen_visuals(job)
    assert captured["video_id"] == 7
    assert captured["motion"] is False
    assert captured["gen_all"] is False   # bool thật, không phải OptionInfo truthy
