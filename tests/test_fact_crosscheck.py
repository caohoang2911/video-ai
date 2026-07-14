"""Wikipedia cross-check: confirmed on majority match, conflict on year mismatch, and
fail-safe (unconfirmed, never raise) on missing article / network error. Wikipedia client
is mocked — no live network in unit tests."""

from unittest.mock import patch

from ai_operator.content import fact_crosscheck as fc
from ai_operator.content.schema import Citation


def _cit(claim: str) -> Citation:
    return Citation(claim=claim, source="Some Archive", verified=True)


def test_confirmed_on_majority_even_with_one_missing_number():
    claim = "RMS Lusitania sank on 7 May 1915 with about 1,198 dead and 128 Americans."
    # article has the year + full date + one count, but NOT the 128 figure -> majority still holds
    article = ("The RMS Lusitania was sunk on 7 May 1915. Roughly 1198 people died when the "
               "Cunard liner went down off the Irish coast.")
    with patch.object(fc, "_wiki_extract", return_value=("RMS Lusitania", article)):
        v = fc.verdict_for(_cit(claim))
    assert v.status == "confirmed", (v.status, v.matched, v.missing)
    assert "128" in v.missing


def test_conflict_when_claim_year_absent_and_article_has_other_year():
    claim = "RMS Lusitania was sunk in 1916 by a German torpedo."
    article = "The RMS Lusitania was sunk on 7 May 1915."
    with patch.object(fc, "_wiki_extract", return_value=("RMS Lusitania", article)):
        v = fc.verdict_for(_cit(claim))
    assert v.status == "conflict"
    assert "1916" in v.missing


def test_matching_year_clears_conflict():
    claim = "RMS Lusitania sank in 1915."
    article = "The RMS Lusitania was sunk on 7 May 1915."
    with patch.object(fc, "_wiki_extract", return_value=("RMS Lusitania", article)):
        assert fc.verdict_for(_cit(claim)).status == "confirmed"


def test_unconfirmed_when_no_article():
    with patch.object(fc, "_wiki_extract", return_value=None):
        assert fc.verdict_for(_cit("Obscure Event happened in 1899.")).status == "unconfirmed"


def test_wiki_extract_swallows_errors_returns_none():
    class _Sess:
        def get(self, *_a, **_k):
            raise RuntimeError("boom")
    with patch.object(fc, "_wiki_client", return_value=_Sess()):
        assert fc._wiki_extract("Anything") is None


def test_entity_extraction_prefers_quoted_then_capitalized():
    assert fc._claim_entity('The report "Halifax Explosion Inquiry" found fault.') == "Halifax Explosion Inquiry"
    assert fc._claim_entity("RMS Lusitania carried munitions.") == "RMS Lusitania"
    assert fc._claim_entity("the ship sank quickly") == ""  # no proper noun


def test_crosscheck_dedups_identical_entities():
    calls = {"n": 0}

    def fake_verdict(_c):
        calls["n"] += 1
        return fc.CrossCheckVerdict("confirmed")

    cits = [_cit("RMS Lusitania sank in 1915."), _cit("RMS Lusitania sank in 1915.")]
    with patch.object(fc, "verdict_for", side_effect=fake_verdict):
        out = fc.crosscheck_citations(cits)
    assert len(out) == 2 and calls["n"] == 1  # second reused from cache
