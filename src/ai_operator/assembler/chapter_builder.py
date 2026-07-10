"""YouTube chapter lines from beat timings.

Chapters measurably lift watch time (+14% view duration per YouTube's own data) and each
chapter can rank independently in Google's "Key Moments" — so labels must be searchable
phrases, which the script's per-beat `chapter_title` provides. Rules enforced here match
YouTube's requirements: first stamp exactly 0:00, ascending order, and no chapter shorter
than 10 seconds (too-short beats are merged into their predecessor by skipping the line).
"""

from __future__ import annotations

MIN_CHAPTER_SECONDS = 10.0


def _fmt(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _label(beat: dict) -> str:
    """chapter_title when the script provides one, else the first keyword, title-cased."""
    title = (beat.get("chapter_title") or "").strip()
    if title:
        return title
    kws = beat.get("keywords") or []
    return str(kws[0]).title() if kws else f"Chapter {beat.get('beat_id', '?')}"


def build_chapters(shot_list: list[dict], durations: list[float], intro_seconds: float = 0.0) -> list[str]:
    """`["0:00 The Final Crossing", "0:48 The Warning Ignored", ...]` from beat durations.

    The first chapter is pinned to 0:00 (a YouTube requirement) and covers the intro card
    plus the first beat. A beat shorter than MIN_CHAPTER_SECONDS emits no line — its time
    simply belongs to the previous chapter (YouTube rejects sub-10s chapters).
    """
    if not shot_list or not durations:
        return []
    lines: list[str] = []
    t = 0.0  # first chapter absorbs the intro card by starting at 0:00
    for i, (beat, dur) in enumerate(zip(shot_list, durations)):
        start = 0.0 if i == 0 else t + intro_seconds
        if i == 0 or dur >= MIN_CHAPTER_SECONDS:
            lines.append(f"{_fmt(start)} {_label(beat)}")
        t += dur
    return lines
