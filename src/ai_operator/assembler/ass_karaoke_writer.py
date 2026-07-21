"""Word-level "karaoke" captions for Shorts: whisper segments (with word timestamps) ->
one ASS file whose words light up in sync with the narration via `\\k` timing tags.

SRT can't express per-word timing, so the Shorts path burns this ASS instead; the style is
embedded here (ffmpeg's force_style would clobber the karaoke colours, so burn_and_mux is
called with sub_style=None). Long-form keeps the plain SRT path untouched.

Style = rendered-pixel parity with short_builder._PORTRAIT_SUB_STYLE (that style is script
units on libass' default 384x288 grid; here the grid IS the 1080x1920 frame): ~73px bold
white text, thin black outline + soft drop shadow (outline ~8% of glyph height, not the
old fat 18%), block held above the Shorts UI zone, side margins inside the tall-phone
cover-crop. Spoken words fill white; upcoming words wait dimmed grey.
"""

from __future__ import annotations

from pathlib import Path

# 1080x1920 script grid -> values below are real output pixels.
_PLAY_RES = (1080, 1920)
# BGR &HAABBGGRR: Primary = spoken (white), Secondary = not-yet-spoken (dim grey).
_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,Arial,73,&H00FFFFFF,&H009E9E9E,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,6,3,2,127,127,567,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(seconds: float) -> str:
    """Seconds -> ASS `H:MM:SS.cc` (centisecond) timestamp."""
    cs = max(0, int(round(seconds * 100)))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6_000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean(text: str) -> str:
    """Strip characters that would open/close ASS override blocks or break the line."""
    return text.replace("{", "").replace("}", "").replace("\n", " ").strip()


def _karaoke_text(seg: dict) -> str:
    """`{\\kNN}word` runs for one segment. A silence gap before a word gets its OWN
    zero-glyph run (on the inter-word space) -- folding it into the word's run would flip
    the word to the spoken colour at the START of the gap, i.e. visibly early."""
    words = seg.get("words") or []
    if not words:
        return _clean(seg.get("text") or "")  # no word timing -> plain (still displayed)
    parts: list[str] = []
    prev_end = float(seg["start"])
    for w in words:
        text = _clean(w["text"])
        if not text:
            continue
        start = max(float(w["start"]), prev_end)   # guard against non-monotonic word times
        end = max(float(w["end"]), start)
        gap_cs = int(round((start - prev_end) * 100))
        dur_cs = max(1, int(round((end - start) * 100)))
        sep = " " if parts else ""
        if gap_cs > 0:
            parts.append(f"{{\\k{gap_cs}}}{sep}{{\\k{dur_cs}}}{text}")
        else:
            parts.append(f"{sep}{{\\k{dur_cs}}}{text}")
        prev_end = end
    return "".join(parts)


def write_karaoke_ass(segments: list[dict], path: str | Path) -> Path:
    """Write whisper segments (from `transcribe(..., with_words=True)`) as a karaoke ASS
    file; returns the path. Empty-text segments are skipped; a non-increasing end is
    nudged forward like the SRT writer does so the cue still displays."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = _PLAY_RES
    lines = [_HEADER.format(w=w, h=h)]
    for seg in segments:
        if not (seg.get("text") or "").strip():
            continue
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        if seg.get("words"):
            end = max(end, float(seg["words"][-1]["end"]))  # never cut the last word's run
        if end <= start:
            end = start + 0.5
        text = _karaoke_text(seg)
        if text:
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Karaoke,,0,0,0,,{text}\n")
    path.write_text("".join(lines), encoding="utf-8")
    return path
