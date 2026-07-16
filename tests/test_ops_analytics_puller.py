"""Key-free unit tests for the analytics puller's metric parsing + upsert. A fake YouTube
Analytics `service` (no network, no OAuth) drives the report-row shapes; the DB upsert runs
against a temp SQLite. Covers core-metric parsing, CTR parsing/scale, and the graceful
"CTR unmeasured" fallbacks so a fresh/low-reach video never corrupts or aborts the pull."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ai_operator.db.base import Base
from ai_operator.db.models_ops import Analytics, RetentionCurve
from ai_operator.ops import analytics_puller as ap

_AS_OF = date(2026, 7, 1)


class _FakeQuery:
    def __init__(self, resp=None, exc=None):
        self._resp, self._exc = resp, exc

    def query(self, **kwargs):
        return self

    def execute(self):
        if self._exc:
            raise self._exc
        return self._resp


class _FakeService:
    def __init__(self, resp=None, exc=None):
        self._q = _FakeQuery(resp, exc)

    def reports(self):
        return self._q


def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ap.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


# --------------------------------------------------------------------------------------
# core metric parsing
# --------------------------------------------------------------------------------------


def test_query_video_parses_core_metrics():
    svc = _FakeService(resp={"rows": [[1234, 5678.5, 42.5]]})
    m = ap._query_video(svc, "v1", _AS_OF)
    assert m == {"views": 1234, "watch_time_min": 5678.5, "avg_view_pct": 42.5}


def test_query_video_none_for_fresh_upload():
    assert ap._query_video(_FakeService(resp={}), "v1", _AS_OF) is None
    assert ap._query_video(_FakeService(resp={"rows": []}), "v1", _AS_OF) is None


# --------------------------------------------------------------------------------------
# CTR parsing + graceful fallback
# --------------------------------------------------------------------------------------


def test_query_ctr_parses_percentage_scaled_value():
    # row = [impressions, impressionsClickThroughRate]; CTR kept as the 0-100 percentage
    svc = _FakeService(resp={"rows": [[10000, 4.83]]})
    assert ap._query_ctr(svc, "v1", _AS_OF) == 4.83


def test_query_ctr_none_when_no_impressions_rows():
    assert ap._query_ctr(_FakeService(resp={"rows": []}), "v1", _AS_OF) is None


def test_query_ctr_none_when_api_raises():
    # an impressions-metric quirk / restriction must not break the pull -> unmeasured
    assert ap._query_ctr(_FakeService(exc=RuntimeError("metric not supported")), "v1", _AS_OF) is None


# --------------------------------------------------------------------------------------
# upsert writes ctr only when measured
# --------------------------------------------------------------------------------------


def test_upsert_sets_ctr_when_measured(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    monkeypatch.setattr(ap, "SessionLocal", Session)
    ap._upsert("v1", _AS_OF, {"views": 100, "watch_time_min": 5.0, "avg_view_pct": 40.0, "ctr": 4.83})
    with Session() as s:
        row = s.scalar(select(Analytics).where(Analytics.youtube_video_id == "v1"))
    assert row.ctr == 4.83


def test_upsert_leaves_ctr_default_when_unmeasured(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    monkeypatch.setattr(ap, "SessionLocal", Session)
    ap._upsert("v2", _AS_OF, {"views": 100, "watch_time_min": 5.0, "avg_view_pct": 40.0})
    with Session() as s:
        row = s.scalar(select(Analytics).where(Analytics.youtube_video_id == "v2"))
    assert row.ctr == 0.0  # model default -> validation reads this as "unmeasured"


def test_upsert_measured_ctr_survives_a_later_unmeasured_pull(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    monkeypatch.setattr(ap, "SessionLocal", Session)
    ap._upsert("v3", _AS_OF, {"views": 100, "watch_time_min": 5.0, "avg_view_pct": 40.0, "ctr": 5.5})
    # a later same-day refresh where CTR came back unmeasured must NOT wipe the good value
    ap._upsert("v3", _AS_OF, {"views": 150, "watch_time_min": 7.0, "avg_view_pct": 41.0})
    with Session() as s:
        row = s.scalar(select(Analytics).where(Analytics.youtube_video_id == "v3"))
    assert row.views == 150 and row.ctr == 5.5


# --------------------------------------------------------------------------------------
# retention curve: parsing + wholesale replace + graceful fallback
# --------------------------------------------------------------------------------------


def test_query_retention_parses_bucket_rows():
    svc = _FakeService(resp={"rows": [[0.01, 0.95, 1.1], [0.02, 0.88]]})
    pts = ap._query_retention(svc, "v1", _AS_OF)
    assert pts[0] == {"elapsed_ratio": 0.01, "watch_ratio": 0.95, "relative_perf": 1.1}
    assert pts[1] == {"elapsed_ratio": 0.02, "watch_ratio": 0.88, "relative_perf": None}


def test_query_retention_empty_or_error_never_breaks_the_pull():
    assert ap._query_retention(_FakeService(resp={}), "v1", _AS_OF) == []
    assert ap._query_retention(_FakeService(exc=RuntimeError("restricted")), "v1", _AS_OF) == []


def test_replace_curve_swaps_rows_wholesale(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    monkeypatch.setattr(ap, "SessionLocal", Session)
    ap._replace_curve("v1", [{"elapsed_ratio": 0.01, "watch_ratio": 1.0, "relative_perf": None}])
    ap._replace_curve("v1", [
        {"elapsed_ratio": 0.01, "watch_ratio": 0.9, "relative_perf": 1.0},
        {"elapsed_ratio": 0.02, "watch_ratio": 0.8, "relative_perf": None},
    ])
    # another video's curve must be untouched by v1's replace
    ap._replace_curve("v2", [{"elapsed_ratio": 0.01, "watch_ratio": 0.5, "relative_perf": None}])
    with Session() as s:
        v1 = s.scalars(select(RetentionCurve).where(RetentionCurve.youtube_video_id == "v1")
                       .order_by(RetentionCurve.elapsed_ratio)).all()
        n_all = len(s.scalars(select(RetentionCurve)).all())
    assert [r.watch_ratio for r in v1] == [0.9, 0.8]  # old snapshot fully replaced
    assert n_all == 3
