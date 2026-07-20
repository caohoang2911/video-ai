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


def test_short_description_emits_archival_images_block_when_present():
    script = {
        **_SHORT_SCRIPT,
        "image_credits": [
            "Steamer General Slocum, 1904 (Wikimedia Commons, CC BY-SA 4.0)",
            "East River, New York (Library of Congress, public domain)",
        ],
    }
    desc = build_short_description(script, "PARENTID123")
    assert "Archival images:" in desc
    assert "Steamer General Slocum, 1904" in desc
    assert "East River, New York" in desc
    # each credit line is prefixed with "- "
    lines = desc.split("\n")
    image_section = False
    found_credits = 0
    for line in lines:
        if line.startswith("Archival images:"):
            image_section = True
        elif image_section and line.startswith("- "):
            found_credits += 1
    assert found_credits == 2


def test_short_description_archival_images_placed_before_ai_disclosure():
    script = {
        **_SHORT_SCRIPT,
        "image_credits": ["Credit A", "Credit B"],
    }
    desc = build_short_description(script, "PARENTID123")
    lines = desc.split("\n")
    archival_idx = next((i for i, l in enumerate(lines) if l.startswith("Archival images:")), -1)
    ai_disclosure_idx = next((i for i, l in enumerate(lines) if l.startswith("[AI disclosure]")), -1)
    assert archival_idx > 0, "Archival images section should be present"
    assert ai_disclosure_idx > 0, "AI disclosure should be present"
    assert archival_idx < ai_disclosure_idx, "Archival images should come before AI disclosure"


def test_short_description_hashtags_remain_last_with_image_credits():
    script = {
        **_SHORT_SCRIPT,
        "image_credits": ["Some credit"],
    }
    desc = build_short_description(script, "PARENTID123")
    last_line = desc.splitlines()[-1]
    assert last_line.startswith("#"), f"Last line should be hashtags, got: {last_line}"


def test_short_description_missing_image_credits_produces_no_archival_heading():
    desc = build_short_description(_SHORT_SCRIPT, "PARENTID123")
    assert "Archival images:" not in desc


def test_short_description_empty_image_credits_produces_no_archival_heading():
    script = {**_SHORT_SCRIPT, "image_credits": []}
    desc = build_short_description(script, "PARENTID123")
    assert "Archival images:" not in desc
