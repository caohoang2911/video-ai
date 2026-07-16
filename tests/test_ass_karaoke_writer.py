"""ASS karaoke writer: per-word `\\k` runs track the audio (gaps absorbed into the next
word's run), self-contained portrait style, and the same degenerate-input guards as the
SRT writer (empty text skipped, non-increasing end nudged)."""

from __future__ import annotations

import pytest

from ai_operator.assembler import ass_karaoke_writer
from ai_operator.assembler.ass_karaoke_writer import write_karaoke_ass


def _words(*triples):
    return [{"start": s, "end": e, "text": t} for s, e, t in triples]


def test_dialogue_karaoke_runs_span_the_segment(tmp_path):
    segs = [{
        "start": 0.0, "end": 2.0, "text": "Every clock froze",
        "words": _words((0.0, 0.5, "Every"), (0.5, 1.1, "clock"), (1.1, 2.0, "froze")),
    }]
    content = write_karaoke_ass(segs, tmp_path / "c.ass").read_text()
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,Karaoke,,0,0,0,," in content
    assert "{\\k50}Every {\\k60}clock {\\k90}froze" in content  # 50+60+90 cs = full 2.0s


def test_silence_gap_gets_its_own_run_so_next_word_lights_on_time(tmp_path):
    segs = [{
        "start": 0.0, "end": 1.5, "text": "A B",
        "words": _words((0.0, 0.5, "A"), (1.0, 1.5, "B")),  # 0.5s silence between words
    }]
    content = write_karaoke_ass(segs, tmp_path / "c.ass").read_text()
    # gap run rides the inter-word space; folding it into B's run would light B 0.5s early
    assert "{\\k50}A{\\k50} {\\k50}B" in content


def test_lead_in_silence_before_first_word_delays_its_highlight(tmp_path):
    segs = [{
        "start": 0.0, "end": 1.0, "text": "late",
        "words": _words((0.4, 1.0, "late")),
    }]
    content = write_karaoke_ass(segs, tmp_path / "c.ass").read_text()
    assert "{\\k40}{\\k60}late" in content


def test_last_word_running_past_segment_end_extends_the_dialogue(tmp_path):
    segs = [{
        "start": 0.0, "end": 1.0, "text": "word",
        "words": _words((0.0, 1.4, "word")),
    }]
    content = write_karaoke_ass(segs, tmp_path / "c.ass").read_text()
    assert "Dialogue: 0,0:00:00.00,0:00:01.40,Karaoke" in content


def test_segment_without_words_falls_back_to_plain_text(tmp_path):
    segs = [{"start": 1.0, "end": 2.0, "text": "plain line"}]
    content = write_karaoke_ass(segs, tmp_path / "c.ass").read_text()
    assert "Dialogue: 0,0:00:01.00,0:00:02.00,Karaoke,,0,0,0,,plain line" in content
    assert "\\k" not in content


def test_override_braces_are_stripped_from_words(tmp_path):
    segs = [{
        "start": 0.0, "end": 1.0, "text": "x",
        "words": _words((0.0, 1.0, "{\\an5}evil")),
    }]
    content = write_karaoke_ass(segs, tmp_path / "c.ass").read_text()
    assert "{\\an5}" not in content.split("Dialogue")[1]
    assert "evil" in content


def test_empty_text_segments_are_skipped_and_bad_end_is_nudged(tmp_path):
    segs = [
        {"start": 0.0, "end": 1.0, "text": "  "},
        {"start": 2.0, "end": 2.0, "text": "stuck"},
    ]
    content = write_karaoke_ass(segs, tmp_path / "c.ass").read_text()
    assert content.count("Dialogue:") == 1
    assert "0:00:02.00,0:00:02.50" in content


def test_header_declares_portrait_play_res(tmp_path):
    content = write_karaoke_ass([], tmp_path / "c.ass").read_text()
    assert "PlayResX: 1080" in content and "PlayResY: 1920" in content
    assert "Style: Karaoke," in content


def test_ass_timestamp_format():
    assert ass_karaoke_writer._ts(0) == "0:00:00.00"
    assert ass_karaoke_writer._ts(61.234) == "0:01:01.23"
    assert ass_karaoke_writer._ts(3601.5) == "1:00:01.50"
    assert ass_karaoke_writer._ts(-1) == "0:00:00.00"
