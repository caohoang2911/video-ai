"""Phase 3 wiring: merge-rule truth table, flag-only failure passthrough, schema round-trip,
and the caption summary. Wikipedia + skeptic are mocked — no live network/LLM."""

import json
from unittest.mock import patch

from ai_operator.content import fact_crosscheck as fc
from ai_operator.content.fact_crosscheck import CrossCheckVerdict
from ai_operator.content.fact_skeptic import SkepticVerdict
from ai_operator.content.schema import Citation


def _cit(claim="RMS Lusitania sank in 1915.") -> Citation:
    return Citation(claim=claim, source="Some Archive", verified=True)


# --- merge rule truth table ---------------------------------------------------------------

def test_merge_ok_when_both_positive():
    assert fc._merge("confirmed", "supported") == "ok"


def test_merge_review_on_wikipedia_conflict():
    assert fc._merge("conflict", "supported") == "review"


def test_merge_review_on_skeptic_unsupported():
    assert fc._merge("confirmed", "unsupported") == "review"


def test_merge_weak_otherwise():
    assert fc._merge("unconfirmed", "supported") == "weak"
    assert fc._merge("confirmed", "doubtful") == "weak"
    assert fc._merge("unconfirmed", "doubtful") == "weak"


# --- verify() orchestration ---------------------------------------------------------------

def test_verify_annotates_fact_status_and_crosscheck():
    cits = [_cit(), _cit("Obscure claim 1899.")]
    wiki = [CrossCheckVerdict("confirmed", article_title="RMS Lusitania"),
            CrossCheckVerdict("conflict", missing=["1899"])]
    skep = [SkepticVerdict("supported", "solid"), SkepticVerdict("doubtful", "shaky")]
    with patch.object(fc, "crosscheck_citations", return_value=wiki), \
         patch("ai_operator.content.fact_skeptic.skeptic_verdicts", return_value=skep):
        out = fc.verify("Topic", "Angle", cits)
    assert out[0].fact_status == "ok"
    assert out[1].fact_status == "review"          # conflict -> review regardless of skeptic
    assert out[0].crosscheck["wikipedia"] == "confirmed"
    assert out[1].crosscheck["skeptic"] == "doubtful"


def test_verify_returns_unchanged_on_failure():
    cits = [_cit()]
    with patch.object(fc, "crosscheck_citations", side_effect=RuntimeError("boom")):
        out = fc.verify("T", "A", cits)
    assert out is cits                              # untouched, no raise
    assert out[0].fact_status is None


def test_verify_empty_is_noop():
    assert fc.verify("T", "A", []) == []


# --- schema round-trip --------------------------------------------------------------------

def test_citation_roundtrips_new_fields():
    c = Citation(claim="x", source="y", verified=True, fact_status="review",
                 crosscheck={"wikipedia": "conflict"})
    reloaded = Citation(**json.loads(json.dumps(c.model_dump())))
    assert reloaded.fact_status == "review"
    assert reloaded.crosscheck["wikipedia"] == "conflict"


def test_old_citation_without_new_fields_still_valid():
    c = Citation(**{"claim": "x", "source": "y", "verified": True})   # legacy shape
    assert c.fact_status is None and c.crosscheck is None


# --- caption summary ----------------------------------------------------------------------

def test_caption_fact_summary_counts(tmp_path):
    from ai_operator.review import caption
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"citations": [
        {"claim": "a", "source": "s", "verified": True, "fact_status": "ok"},
        {"claim": "b", "source": "s", "verified": True, "fact_status": "ok"},
        {"claim": "c", "source": "s", "verified": True, "fact_status": "review"},
    ]}))
    assert caption._fact_summary(str(script)) == "2 ok / 1 review"


def test_caption_fact_summary_missing_file():
    from ai_operator.review import caption
    assert caption._fact_summary(None) == "n/a"
    assert caption._fact_summary("/nonexistent/script.json") == "n/a"
