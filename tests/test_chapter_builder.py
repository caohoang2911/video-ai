"""Key-free unit tests for YouTube chapter generation: 0:00-pinned first stamp, intro-card
offset on later stamps, sub-10s beats merged (no line), label fallback to keywords, and the
description block only activating at YouTube's 3-chapter minimum. No ffmpeg, no network."""

from __future__ import annotations

from ai_operator.assembler.chapter_builder import build_chapters
from ai_operator.publisher import metadata_builder as mb


def _beats(n, with_titles=True):
    return [
        {
            "beat_id": i + 1,
            "keywords": [f"keyword {i+1}"],
            **({"chapter_title": f"Chapter Label {i+1}"} if with_titles else {}),
        }
        for i in range(n)
    ]


def test_first_chapter_pinned_to_zero_and_intro_offset_applied():
    lines = build_chapters(_beats(3), [40.0, 40.0, 40.0], intro_seconds=3.0)
    # beat 1 starts at 0:00 (absorbs the 3s intro card); beat 2 at 3+40=43s; beat 3 at 3+80=83s
    assert lines == ["0:00 Chapter Label 1", "0:43 Chapter Label 2", "1:23 Chapter Label 3"]


def test_short_beat_is_merged_not_emitted():
    lines = build_chapters(_beats(3), [40.0, 5.0, 40.0], intro_seconds=0.0)
    assert lines == ["0:00 Chapter Label 1", "0:45 Chapter Label 3"]  # 5s beat folded into #1


def test_label_falls_back_to_first_keyword():
    lines = build_chapters(_beats(1, with_titles=False), [30.0])
    assert lines == ["0:00 Keyword 1"]


def test_hour_formatting():
    lines = build_chapters(_beats(2), [3600.0, 60.0], intro_seconds=0.0)
    assert lines[1].startswith("1:00:00 ")


def test_empty_inputs():
    assert build_chapters([], []) == []


# --------------------------------------------------------------------------------------
# description integration
# --------------------------------------------------------------------------------------


def test_description_includes_chapters_block():
    script = {
        "description": "Hook line.",
        "sources": [],
        "chapters": ["0:00 The Crossing", "1:10 The Warning", "2:30 The Collision"],
    }
    desc = mb.build_description(script)
    assert "Chapters:\n0:00 The Crossing\n1:10 The Warning\n2:30 The Collision" in desc
    assert desc.index("Chapters:") < desc.index(mb.AI_DISCLOSURE)  # chapters above the boilerplate


def test_description_omits_chapters_below_youtube_minimum():
    script = {"description": "Hook.", "chapters": ["0:00 Only", "1:00 Two"]}  # < 3 stamps
    assert "Chapters:" not in mb.build_description(script)
