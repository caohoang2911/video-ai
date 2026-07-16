"""Fact-check evidence panel on the video detail page + the two arbitration actions:
resolve (human vouches for a flagged claim) and recheck (re-run the flag-only gate).
The gate itself is mocked — no live Wikipedia/LLM."""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ai_operator.db.engine import SessionLocal
from ai_operator.db.models import Video
from ai_operator.db.state_machine import VideoState
from ai_operator.web.app import create_app


@pytest.fixture
def client(temp_db, tmp_path):
    return TestClient(create_app(output_dir=tmp_path / "media"))


def _video_with_script(tmp_path, citations) -> int:
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"citations": citations}), encoding="utf-8")
    with SessionLocal() as s:
        v = Video(state=VideoState.RENDERED.value, idempotency_key="fc:ui:1", kind="main",
                  title="RMS Lusitania: The Manifest", script_path=str(script))
        s.add(v)
        s.commit()
        return v.id


_FLAGGED = [
    {"claim": "Sunk on 7 May 1915.", "source": "Mersey Inquiry", "verified": True,
     "fact_status": "ok", "crosscheck": {"wikipedia": "confirmed", "wikipedia_article": "RMS Lusitania",
                                         "skeptic": "supported", "skeptic_reason": ""}},
    {"claim": "Sunk in 1925.", "source": "Fake Archive", "verified": True,
     "fact_status": "review", "crosscheck": {"wikipedia": "conflict", "wikipedia_article": "RMS Lusitania",
                                             "skeptic": "unsupported", "skeptic_reason": "wrong year"}},
]


def test_detail_page_shows_factcheck_panel(client, tmp_path):
    vid = _video_with_script(tmp_path, _FLAGGED)
    html = client.get(f"/videos/{vid}").text
    assert "Kiểm chứng dữ kiện" in html
    assert "REVIEW" in html and "wrong year" in html          # flagged row + skeptic evidence
    assert "en.wikipedia.org/wiki/RMS_Lusitania" in html      # 1-click arbitration link
    assert "Claim đúng — bỏ cờ" in html                       # resolve button on flagged row


def test_detail_page_hides_panel_without_citations(client, tmp_path):
    vid = _video_with_script(tmp_path, [])
    assert "Kiểm chứng dữ kiện" not in client.get(f"/videos/{vid}").text


def test_resolve_flips_flag_and_stamps_human(client, tmp_path):
    vid = _video_with_script(tmp_path, [dict(c) for c in _FLAGGED])
    r = client.post(f"/videos/{vid}/factcheck/1/resolve", follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as s:
        data = json.loads(open(s.get(Video, vid).script_path).read())
    assert data["citations"][1]["fact_status"] == "ok"
    assert data["citations"][1]["crosscheck"]["human"] == "confirmed"
    assert data["citations"][1]["crosscheck"]["wikipedia"] == "conflict"  # machine trail kept


def test_resolve_index_out_of_range_400(client, tmp_path):
    vid = _video_with_script(tmp_path, [dict(c) for c in _FLAGGED])
    assert client.post(f"/videos/{vid}/factcheck/9/resolve", follow_redirects=False).status_code == 400


def test_recheck_reruns_gate_and_persists(client, tmp_path):
    from ai_operator.content.schema import Citation
    vid = _video_with_script(tmp_path, [dict(c) for c in _FLAGGED])

    def fake_verify(_t, _a, cits, video_id=None):
        return [Citation(**{**c.model_dump(), "fact_status": "weak"}) for c in cits]

    with patch("ai_operator.content.fact_crosscheck.verify", side_effect=fake_verify):
        r = client.post(f"/videos/{vid}/factcheck/recheck", follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as s:
        data = json.loads(open(s.get(Video, vid).script_path).read())
    assert all(c["fact_status"] == "weak" for c in data["citations"])


def test_recheck_preserves_human_confirmed_claims(client, tmp_path):
    """Human arbitration outranks the machines: a vouched citation is kept as-is and
    excluded from the re-run; only the unarbitrated one is recomputed."""
    from ai_operator.content.schema import Citation
    confirmed = {"claim": "Sunk on 7 May 1915.", "source": "Mersey Inquiry", "verified": True,
                 "fact_status": "ok",
                 "crosscheck": {"wikipedia": "conflict", "skeptic": "unsupported", "human": "confirmed"}}
    vid = _video_with_script(tmp_path, [confirmed, dict(_FLAGGED[1])])

    seen = {"n": 0}

    def fake_verify(_t, _a, cits, video_id=None):
        seen["n"] = len(cits)
        return [Citation(**{**c.model_dump(), "fact_status": "weak"}) for c in cits]

    with patch("ai_operator.content.fact_crosscheck.verify", side_effect=fake_verify):
        r = client.post(f"/videos/{vid}/factcheck/recheck", follow_redirects=False)
    assert r.status_code == 303
    assert seen["n"] == 1                                   # only the unarbitrated citation re-ran
    with SessionLocal() as s:
        data = json.loads(open(s.get(Video, vid).script_path).read())
    assert data["citations"][0]["fact_status"] == "ok"      # human verdict untouched
    assert data["citations"][0]["crosscheck"]["human"] == "confirmed"
    assert data["citations"][1]["fact_status"] == "weak"    # the other was recomputed


def test_recheck_all_confirmed_is_noop(client, tmp_path):
    confirmed = {"claim": "x", "source": "y", "verified": True, "fact_status": "ok",
                 "crosscheck": {"human": "confirmed"}}
    vid = _video_with_script(tmp_path, [dict(confirmed)])
    with patch("ai_operator.content.fact_crosscheck.verify") as m:
        r = client.post(f"/videos/{vid}/factcheck/recheck", follow_redirects=False)
    assert r.status_code == 303
    m.assert_not_called()                                   # nothing to re-run, no LLM/wiki spend
