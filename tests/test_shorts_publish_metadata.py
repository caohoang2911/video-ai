"""Short upload metadata: #Shorts + parent funnel link present, hashtags last, main unchanged."""

from ai_operator.publisher.metadata_builder import build_short_description, build_upload_body

_SHORT_SCRIPT = {
    "title": "The Captain Who Sailed Past Safety",
    "curiosity_question": "What did that extra mile cost?",
    "hashtags": ["GeneralSlocum", "Shorts", "History"],
}


def test_short_description_has_funnel_link_and_shorts_tag():
    desc = build_short_description(_SHORT_SCRIPT, "PARENTID123")
    assert "https://youtu.be/PARENTID123" in desc
    assert "#Shorts" in desc
    assert desc.startswith("What did that extra mile cost?")
    # remaining hashtags are the last line and don't duplicate #Shorts
    last = desc.splitlines()[-1]
    assert last == "#GeneralSlocum #History"


def test_short_description_carries_music_credit_when_present():
    script = {**_SHORT_SCRIPT, "music_credit": 'Music: "Long Note One" by Kevin MacLeod (CC BY 4.0)'}
    desc = build_short_description(script, "PARENTID123")
    assert 'Kevin MacLeod' in desc


def test_short_upload_body_uses_short_description():
    body = build_upload_body(
        _SHORT_SCRIPT, publish_at_iso="2026-07-17T12:00:00Z", category_id="27",
        kind="short", parent_youtube_id="PARENTID123",
    )
    assert "#Shorts" in body["snippet"]["description"]
    assert body["snippet"]["title"] == _SHORT_SCRIPT["title"]
    assert body["status"]["privacyStatus"] == "private"  # scheduled, still behind the gate


def test_main_upload_body_unchanged_by_default():
    script = {
        "title_options": [{"title": "A Main Title", "thumbnail_text": ""}],
        "description": "Main hook.", "sources": ["a", "b"], "tags": ["t"], "hashtags": [],
    }
    body = build_upload_body(script, publish_at_iso="2026-07-17T12:00:00Z", category_id="27")
    assert "#Shorts" not in body["snippet"]["description"]
    assert "Main hook." in body["snippet"]["description"]


def test_short_description_adds_one_sibling_link_after_parent_link():
    desc = build_short_description(_SHORT_SCRIPT, "PARENTID123", "SIBLING456")
    assert "https://youtu.be/PARENTID123" in desc
    assert "https://youtube.com/shorts/SIBLING456" in desc
    # parent funnel link stays primary (appears before the sibling line)
    assert desc.index("PARENTID123") < desc.index("SIBLING456")


def test_short_description_has_no_sibling_line_by_default():
    desc = build_short_description(_SHORT_SCRIPT, "PARENTID123")
    assert "youtube.com/shorts/" not in desc
