"""Read views render from the live DB (HTML) and negotiate JSON under /api. No network:
the temp_db fixture rebinds SessionLocal; create_app's media mount points at tmp_path."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from ai_operator.db.engine import SessionLocal
from ai_operator.db.models import Upload, Video
from ai_operator.db.models_ops import Job
from ai_operator.db.state_machine import VideoState
from ai_operator.web.app import create_app


@pytest.fixture
def client(temp_db, tmp_path):
    return TestClient(create_app(output_dir=tmp_path / "media"))


def _seed_video(**kw) -> int:
    with SessionLocal() as s:
        v = Video(idempotency_key=kw.pop("idempotency_key", "k1"), **kw)
        s.add(v)
        s.commit()
        return v.id


def test_html_pages_render(client):
    for path in ["/", "/videos", "/topics", "/jobs", "/costs", "/analytics"]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("text/html")


def test_api_variants_return_json(client):
    for path in ["/api/", "/api/videos", "/api/jobs", "/api/costs", "/api/analytics", "/api/topics"]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("application/json"), path


def test_video_shows_in_list_and_detail(client):
    vid = _seed_video(state=VideoState.PENDING_REVIEW.value, title="hello world")

    listing = client.get("/api/videos").json()
    assert any(v["id"] == vid and v["title"] == "hello world" for v in listing["videos"])

    detail = client.get(f"/api/videos/{vid}").json()
    assert detail["video"]["id"] == vid
    assert "assets" in detail and "costs" in detail and "decisions" in detail
    # PENDING_REVIEW can legally transition to POLICY_OK -> PASS_POLICY offered
    assert "PASS_POLICY" in detail["allowed_decisions"]

    assert client.get(f"/videos/{vid}").status_code == 200      # HTML detail renders


def test_missing_video_is_404(client):
    assert client.get("/api/videos/424242").status_code == 404


def test_video_detail_has_copy_subtitles_button(client, tmp_path):
    import json as _json
    script = tmp_path / "script.json"
    script.write_text(_json.dumps({"narration": "This is the spoken transcript to copy."}))
    vid = _seed_video(idempotency_key="t1", state=VideoState.RENDERED.value,
                      title="X", script_path=str(script))
    html = client.get(f"/videos/{vid}").text
    assert "Copy phụ đề" in html
    assert "This is the spoken transcript to copy." in html  # narration rides in data-t


def test_video_detail_hides_button_without_transcript(client):
    vid = _seed_video(idempotency_key="t0", state=VideoState.DRAFT.value, title="Y")
    assert "Copy phụ đề" not in client.get(f"/videos/{vid}").text  # no script.json -> no button


def test_shorts_list_has_per_short_rerender_button(client):
    # A main's shorts table offers a per-short re-render (gen-visuals) button — but only for
    # re-rollable states (voiced/rendered); a short past review shows no button.
    main_id = _seed_video(idempotency_key="m1", kind="main",
                          state=VideoState.PUBLISHED.value, title="Main")
    rendered = _seed_video(idempotency_key="s1", kind="short", parent_id=main_id,
                           state=VideoState.RENDERED.value, title="Short rendered")
    published = _seed_video(idempotency_key="s2", kind="short", parent_id=main_id,
                            state=VideoState.PUBLISHED.value, title="Short published")

    html = client.get(f"/videos/{main_id}").text
    assert f"/videos/{rendered}/enqueue/gen-visuals" in html      # rendered short -> button
    assert "Render lại" in html
    assert f"/videos/{published}/enqueue/gen-visuals" not in html  # published short -> no button


def test_channel_link_on_analytics_page_only(client):
    from ai_operator.config import settings

    assert settings.CHANNEL_URL in client.get("/analytics").text
    # deliberately NOT in the shared sidebar — the link lives on the analytics page
    assert settings.CHANNEL_URL not in client.get("/videos").text


def test_published_video_gets_watch_link_in_list_and_detail(client):
    vid = _seed_video(state=VideoState.PUBLISHED.value, title="live one")
    with SessionLocal() as s:
        # a failed first attempt then the confirmed upload — the newest id must win
        s.add(Upload(video_id=vid, youtube_video_id=None, status="failed"))
        s.add(Upload(video_id=vid, youtube_video_id="abc123XYZ", status="published"))
        s.commit()

    row = next(v for v in client.get("/api/videos").json()["videos"] if v["id"] == vid)
    assert row["youtube_url"] == "https://youtu.be/abc123XYZ"

    detail = client.get(f"/api/videos/{vid}").json()
    assert detail["upload"]["youtube_url"] == "https://youtu.be/abc123XYZ"
    assert "https://youtu.be/abc123XYZ" in client.get(f"/videos/{vid}").text  # HTML shows the link


def test_unpublished_video_has_no_watch_link(client):
    vid = _seed_video(idempotency_key="unpub", state=VideoState.RENDERED.value)
    row = next(v for v in client.get("/api/videos").json()["videos"] if v["id"] == vid)
    assert row["youtube_url"] is None
    assert client.get(f"/api/videos/{vid}").json()["upload"] is None


def test_state_filter(client):
    _seed_video(idempotency_key="a", state=VideoState.APPROVED.value)
    _seed_video(idempotency_key="b", state=VideoState.DRAFT.value)
    approved = client.get("/api/videos?state=approved").json()["videos"]
    assert approved and all(v["state"] == "approved" for v in approved)


def test_detail_polls_only_while_a_job_is_in_flight(client):
    """The 3s auto-refresh is expensive (it re-fetches the whole detail page). A settled
    video never changes on its own, so the poll must be OFF unless a job is pending/running
    — otherwise every open tab hammers the server and the boosted UI feels stuck."""
    vid = _seed_video(idempotency_key="poll", state=VideoState.RENDERED.value)

    # settled render, no queued work -> no self-poll
    assert 'hx-trigger="every 3s"' not in client.get(f"/videos/{vid}").text

    with SessionLocal() as s:
        s.add(Job(command="assemble", video_id=vid, status="running", idempotency_key="jp"))
        s.commit()
    # a job is now moving the video -> poll wakes up so the stepper tracks progress
    assert 'hx-trigger="every 3s"' in client.get(f"/videos/{vid}").text


def test_detail_survives_missing_retention_table(client):
    """An un-migrated/partial DB (retention_curve absent) must not 500 the detail page —
    the retention panel just hides. Regression for uploaded videos being unopenable."""
    vid = _seed_video(idempotency_key="noret", state=VideoState.PUBLISHED.value)
    with SessionLocal() as s:
        s.add(Upload(video_id=vid, youtube_video_id="ret404xyz", status="published"))
        s.commit()
        s.execute(text("DROP TABLE retention_curve"))
        s.commit()

    assert client.get(f"/videos/{vid}").status_code == 200


def test_media_url_is_none_for_deleted_artifact(tmp_path, monkeypatch):
    """The DB pointer can outlive its file (revoice deletes final.mp4 before the re-render
    lands) — a URL to a missing file must not be emitted, or the page shows a broken player."""
    from ai_operator.web import routes_videos

    monkeypatch.setattr(routes_videos, "OUTPUT_DIR", tmp_path)
    live = tmp_path / "3" / "final.mp4"
    live.parent.mkdir()
    live.write_bytes(b"x")
    url = routes_videos._media_url(str(live))
    # carries an ?v=<mtime> cache-buster so a re-rendered artifact at the same path is refetched
    assert url is not None and url.startswith("/media/3/final.mp4?v=")

    live.unlink()  # revoice tore the render down; the DB pointer is now stale
    assert routes_videos._media_url(str(live)) is None
