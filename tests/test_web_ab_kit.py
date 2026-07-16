"""Studio A/B Test Kit on the video-detail page: a published MAIN surfaces its 3 candidate
titles + 3 thumbnail variants + a Studio deep-link; the ab-setup/set-winner POSTs record
ab_status and the human-observed winner. Shorts and unpublished videos get no kit."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ai_operator.db.engine import SessionLocal
from ai_operator.db.models import Upload, Video
from ai_operator.db.state_machine import VideoState
from ai_operator.web import routes_videos
from ai_operator.web.app import create_app


@pytest.fixture
def client(temp_db, tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    # _media_url resolves render artifacts relative to OUTPUT_DIR -> point it at the test mount
    monkeypatch.setattr(routes_videos, "OUTPUT_DIR", media)
    return TestClient(create_app(output_dir=media)), media


def _seed_published_main(media, *, kind="main", titles=("A title", "B title", "C title")):
    vdir = media / "vid"
    (vdir).mkdir(parents=True, exist_ok=True)
    (vdir / "final.mp4").write_bytes(b"mp4")
    for c in ("a", "b", "c"):
        (vdir / f"thumb_{c}.jpg").write_bytes(b"jpg")
    script = vdir / "script.json"
    script.write_text(json.dumps({
        "title_options": [{"title": t, "thumbnail_text": ""} for t in titles],
    }), encoding="utf-8")
    with SessionLocal() as s:
        v = Video(idempotency_key="ab:1", kind=kind, state=VideoState.PUBLISHED.value,
                  title=titles[0], video_path=str(vdir / "final.mp4"), script_path=str(script))
        s.add(v)
        s.commit()
        vid = v.id
        s.add(Upload(video_id=vid, youtube_video_id="ytABC123", status="published"))
        s.commit()
    return vid


def test_published_main_shows_ab_kit(client):
    c, media = client
    vid = _seed_published_main(media)
    html = c.get(f"/videos/{vid}").text
    assert "A/B Test Kit" in html
    assert "A title" in html and "B title" in html and "C title" in html   # 3 candidates
    assert "studio.youtube.com/video/ytABC123/edit" in html                 # Studio deep-link
    assert html.count('class="copy-btn"') == 3                              # a copy button each
    assert "/media/vid/thumb_a.jpg" in html                                 # thumbnail variant


def test_short_gets_no_ab_kit(client):
    c, media = client
    vid = _seed_published_main(media, kind="short")
    assert "A/B Test Kit" not in c.get(f"/videos/{vid}").text


def test_ab_setup_marks_running(client):
    c, media = client
    vid = _seed_published_main(media)
    c.post(f"/videos/{vid}/ab-setup", follow_redirects=False)
    with SessionLocal() as s:
        row = s.scalar(select(Upload).where(Upload.video_id == vid))
    assert row.ab_status == "running"


def test_set_winner_records_title_and_marks_done(client):
    c, media = client
    vid = _seed_published_main(media)
    c.post(f"/videos/{vid}/set-winner", data={"title": "B title"}, follow_redirects=False)
    with SessionLocal() as s:
        row = s.scalar(select(Upload).where(Upload.video_id == vid))
    assert row.winning_title == "B title" and row.ab_status == "done"
