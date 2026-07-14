"""Adversarial skeptic: aligns one verdict per citation by index, degrades missing/garbled
entries and any LLM/parse failure to `doubtful` (never raises). complete() is mocked — no
live LLM in unit tests."""

from unittest.mock import patch

from ai_operator.content import fact_skeptic as fs
from ai_operator.content.schema import Citation


def _cits(n: int) -> list[Citation]:
    return [Citation(claim=f"Claim {i}", source=f"Source {i}", verified=True) for i in range(n)]


def test_wellformed_verdicts_align_by_index():
    raw = ('{"verdicts":[{"index":0,"status":"supported","reason":"solid"},'
           '{"index":1,"status":"unsupported","reason":"manifest cannot state motive"}]}')
    with patch.object(fs, "complete", return_value=raw):
        out = fs.skeptic_verdicts("T", "A", _cits(2))
    assert [v.status for v in out] == ["supported", "unsupported"]
    assert out[1].reason == "manifest cannot state motive"


def test_missing_index_defaults_to_doubtful():
    raw = '{"verdicts":[{"index":0,"status":"supported","reason":"ok"}]}'  # index 1 absent
    with patch.object(fs, "complete", return_value=raw):
        out = fs.skeptic_verdicts("T", "A", _cits(2))
    assert out[0].status == "supported"
    assert out[1].status == "doubtful"


def test_malformed_json_all_doubtful_no_raise():
    with patch.object(fs, "complete", return_value="not json at all"):
        out = fs.skeptic_verdicts("T", "A", _cits(3))
    assert [v.status for v in out] == ["doubtful", "doubtful", "doubtful"]


def test_llm_failure_all_doubtful_no_raise():
    def boom(*_a, **_k):
        raise RuntimeError("no provider")
    with patch.object(fs, "complete", side_effect=boom):
        out = fs.skeptic_verdicts("T", "A", _cits(2))
    assert all(v.status == "doubtful" for v in out)


def test_out_of_range_and_invalid_status_ignored():
    raw = ('{"verdicts":[{"index":9,"status":"supported","reason":"x"},'
           '{"index":0,"status":"bogus","reason":"y"},'
           '{"index":1,"status":"supported","reason":"z"}]}')
    with patch.object(fs, "complete", return_value=raw):
        out = fs.skeptic_verdicts("T", "A", _cits(2))
    assert out[0].status == "doubtful"   # invalid status ignored -> default
    assert out[1].status == "supported"  # valid


def test_empty_citations_returns_empty_no_llm_call():
    with patch.object(fs, "complete") as m:
        out = fs.skeptic_verdicts("T", "A", [])
    assert out == []
    m.assert_not_called()


def test_single_batched_call_for_many_citations():
    raw = '{"verdicts":[]}'
    with patch.object(fs, "complete", return_value=raw) as m:
        fs.skeptic_verdicts("T", "A", _cits(5))
    assert m.call_count == 1  # one batched call, not one per citation
