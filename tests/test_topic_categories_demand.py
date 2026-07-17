"""Key-free unit tests for topic sub-niche categories, the YouTube demand/opportunity score
(best-effort, never raises), category+demand tagging in suggest_topics, and the dependency
health-check. No network, no real YouTube, no model downloads."""

from __future__ import annotations

import json

from ai_operator.content import topic_backlog
from ai_operator.content import topic_categories as tc
from ai_operator.content import topic_demand
from ai_operator.ops import dependency_check


# --------------------------------------------------------------------------------------
# categories
# --------------------------------------------------------------------------------------


def test_category_valid_falls_back_to_maritime():
    assert tc.valid("aviation") == "aviation"
    assert tc.valid("bogus") == "maritime"
    assert tc.valid(None) == "maritime"


def test_category_label_and_domain():
    assert tc.label("rail") == "Đường sắt"
    assert "railway" in tc.domain("rail")
    assert "maritime" in tc.domain("bogus")  # unknown -> anchor niche


# --------------------------------------------------------------------------------------
# demand opportunity score
# --------------------------------------------------------------------------------------


def test_opportunity_rewards_demand_and_penalizes_saturation():
    low = topic_demand._opportunity(1_000, 0)        # 1k median -> ~0
    mid = topic_demand._opportunity(100_000, 0)      # 100k -> middling
    high = topic_demand._opportunity(1_000_000, 0)   # 1M -> ~100
    assert low < mid < high and high >= 95
    assert topic_demand._opportunity(1_000_000, 5) < high  # saturation dampens the same demand


def test_demand_none_when_unconfigured_or_empty(monkeypatch):
    monkeypatch.setattr(type(topic_demand.settings), "missing", lambda self, keys: True)
    assert topic_demand.score("MS Estonia") is None
    assert topic_demand.score_json("MS Estonia") == (None, None)
    monkeypatch.setattr(type(topic_demand.settings), "missing", lambda self, keys: False)
    assert topic_demand.score("   ") is None  # empty query short-circuits


class _Endpoint:
    def __init__(self, resp):
        self._resp = resp

    def list(self, **kw):
        return self

    def execute(self):
        return self._resp


class _FakeService:
    def __init__(self, search, videos):
        self._s, self._v = _Endpoint(search), _Endpoint(videos)

    def search(self):
        return self._s

    def videos(self):
        return self._v


def test_demand_full_path_computes_median_and_competition(monkeypatch):
    monkeypatch.setattr(type(topic_demand.settings), "missing", lambda self, keys: False)
    search = {"items": [{"id": {"videoId": "a"}}, {"id": {"videoId": "b"}}]}
    videos = {"items": [
        {"snippet": {"title": "Estonia doc"}, "statistics": {"viewCount": "1000000"}},
        {"snippet": {"title": "Estonia 2"}, "statistics": {"viewCount": "400000"}},
    ]}
    from ai_operator.publisher import oauth_headless
    monkeypatch.setattr(oauth_headless, "build_service", lambda: _FakeService(search, videos))
    res = topic_demand.score("MS Estonia")
    assert res["median_views"] == 700_000       # median(1_000_000, 400_000)
    assert res["competition"] == 2               # both >= the strong-incumbent threshold
    assert 0 <= res["score"] <= 100 and len(res["top"]) == 2


def test_demand_best_effort_on_api_error(monkeypatch):
    monkeypatch.setattr(type(topic_demand.settings), "missing", lambda self, keys: False)
    from ai_operator.publisher import oauth_headless

    def _boom():
        raise RuntimeError("quota exceeded")

    monkeypatch.setattr(oauth_headless, "build_service", _boom)
    assert topic_demand.score("MS Estonia") is None  # swallows the error, never blocks gen-topics


# --------------------------------------------------------------------------------------
# suggest_topics tags category + demand
# --------------------------------------------------------------------------------------


def test_suggest_topics_tags_category_and_demand(monkeypatch):
    sink: list = []

    class _S:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def add(self, o):
            sink.append(o)

        def flush(self):
            for i, o in enumerate(sink, 1):
                if getattr(o, "id", None) is None:
                    o.id = i

        def commit(self):
            pass

    monkeypatch.setattr(topic_backlog, "SessionLocal", lambda: _S())
    monkeypatch.setattr(topic_backlog, "complete",
                        lambda *a, **k: '{"topics":[{"title":"Some Air Crash: 1977","angle":"x","source_hint":"y"}]}')
    monkeypatch.setattr(topic_backlog, "parse_json", json.loads)
    monkeypatch.setattr(topic_backlog, "is_duplicate", lambda title: False)
    monkeypatch.setattr(topic_backlog, "record", lambda title, session=None: None)
    monkeypatch.setattr(topic_backlog.topic_demand, "score_json", lambda q: (72, '{"score":72}'))

    created = topic_backlog.suggest_topics(1, category="aviation")
    assert len(created) == 1
    assert created[0].category == "aviation"
    assert created[0].demand_score == 72
    assert created[0].title == "Some Air Crash: 1977"


# --------------------------------------------------------------------------------------
# dependency health-check
# --------------------------------------------------------------------------------------


def test_translate_to_vi_best_effort(monkeypatch):
    assert topic_backlog.translate_to_vi("") is None
    assert topic_backlog.translate_to_vi("   ") is None
    monkeypatch.setattr(topic_backlog, "complete", lambda *a, **k: "  Bản dịch tiếng Việt  ")
    assert topic_backlog.translate_to_vi("An English angle") == "Bản dịch tiếng Việt"

    def _boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(topic_backlog, "complete", _boom)
    assert topic_backlog.translate_to_vi("An English angle") is None  # never blocks the caller


def test_demand_reason_formats_views_and_competition():
    from ai_operator.web.routes_topics import _demand_reason

    assert _demand_reason(json.dumps({"median_views": 1_200_000, "competition": 3})) == "~1.2M view/video · 3 video mạnh"
    assert _demand_reason(json.dumps({"median_views": 4_000, "competition": 0})) == "~4K view/video · 0 video mạnh"
    assert _demand_reason(None) == "" and _demand_reason("not json") == ""


def test_missing_critical_reports_absent_modules(monkeypatch):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr("importlib.util.find_spec",
                        lambda name, *a, **k: None if name == "torch" else real(name))
    miss = dependency_check.missing_critical()
    assert "torch" in miss and "numpy" not in miss
