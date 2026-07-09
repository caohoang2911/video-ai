"""Key-free unit tests for description hashtags + SEO metadata: hashtag normalization
(strip spaces/punctuation, single leading '#', dedupe, cap) and that build_description appends
them as the last line (YouTube surfaces the first 3 above the title). No network, no API key."""

from __future__ import annotations

from ai_operator.publisher import metadata_builder as mb


def test_normalize_hashtags_strips_spaces_and_punctuation():
    assert mb.normalize_hashtags(["Ship Wreck", "#MaritimeHistory", "  documentary  "]) == [
        "#ShipWreck", "#MaritimeHistory", "#documentary"
    ]


def test_normalize_hashtags_dedupes_case_insensitively_and_caps():
    out = mb.normalize_hashtags(["History", "history", "#HISTORY", "War", "Sea", "Ships", "Boats"], limit=5)
    assert out[0] == "#History"
    assert sum(1 for t in out if t.lower() == "#history") == 1  # collapsed to one
    assert len(out) == 5                                        # capped


def test_normalize_hashtags_drops_empty_tokens():
    assert mb.normalize_hashtags(["", "#", "  ", "Valid"]) == ["#Valid"]


def test_build_description_appends_hashtags_last():
    script = {
        "description": "A forgotten disaster.",
        "sources": ["Book A", "Report B"],
        "hashtags": ["Shipwreck", "Maritime History", "#Documentary"],
    }
    desc = mb.build_description(script)
    assert desc.strip().endswith("#Shipwreck #MaritimeHistory #Documentary")
    assert mb.AI_DISCLOSURE in desc          # disclosure still present, above the hashtags
    assert "Sources:" in desc


def test_build_description_without_hashtags_is_unchanged_shape():
    desc = mb.build_description({"description": "Body.", "sources": []})
    assert "#" not in desc.split("Body.")[-1].split(mb.AI_DISCLOSURE)[0]  # no hashtag line injected
    assert desc.startswith("Body.")
