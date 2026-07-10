"""Pick a music bed from the local royalty-free library by the script's dominant mood.

Library layout: `assets/music/<bucket>-<slug>.mp3` where bucket is `somber` or `tense`.
Tracks are Kevin MacLeod / incompetech (CC BY 4.0) — attribution is REQUIRED, so picking a
track also writes its credit line into script.json (`music_credit`) for the publisher to put
in the YouTube description, and registers a `music` Asset row for the license audit trail.
Selection rotates deterministically by video_id so consecutive videos don't share one bed.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import PROJECT_ROOT
from .ffmpeg_encode import probe_duration
from ..db import SessionLocal
from ..db.models import Asset
from ..logging_setup import get_logger

log = get_logger("assembler.music_picker")

MUSIC_DIR = PROJECT_ROOT / "assets" / "music"

# filename stem -> (display title, credit line). CC BY 4.0 requires naming the work + author.
_CREDITS = {
    "somber-long-note-one": "Long Note One",
    "somber-ossuary-5-rest": "Ossuary 5 - Rest",
    "tense-dark-times": "Dark Times",
    "tense-grim-league": "Grim League",
}
_CREDIT_FMT = (
    'Music: "{title}" by Kevin MacLeod (incompetech.com), licensed under CC BY 4.0 '
    "(creativecommons.org/licenses/by/4.0)"
)

# beat-mood vocabulary -> bucket; anything unmatched counts toward the default somber bed
_TENSE_HINTS = (
    "tense", "foreboding", "ominous", "chaotic", "desperate", "predatory",
    "cataclysmic", "panic", "urgent", "suspense",
)


def _dominant_bucket(script: dict) -> str:
    moods = " ".join(b.get("mood", "") for b in script.get("shot_list", [])).lower()
    tense = sum(moods.count(h) for h in _TENSE_HINTS)
    calm = max(1, len(script.get("shot_list", []))) - tense
    return "tense" if tense > calm else "somber"


def _safe_duration(path: Path) -> float:
    try:
        return probe_duration(path)
    except Exception:  # noqa: BLE001 - unknown length just skips the seam-avoidance filter
        return 0.0


def _credit_for(path: Path) -> str:
    title = _CREDITS.get(path.stem, path.stem.replace("-", " ").title())
    return _CREDIT_FMT.format(title=title)


def pick_for_video(video_id: int, video_dir: Path) -> str | None:
    """Choose a library bed for this video; persist credit + audit row. None if no library."""
    script_path = Path(video_dir) / "script.json"
    if not script_path.exists() or not MUSIC_DIR.exists():
        return None
    script = json.loads(script_path.read_text(encoding="utf-8"))

    bucket = _dominant_bucket(script)
    candidates = sorted(MUSIC_DIR.glob(f"{bucket}-*.mp3")) or sorted(MUSIC_DIR.glob("*.mp3"))
    if not candidates:
        return None
    # Avoid a mid-video loop seam: prefer beds long enough to play straight through (the
    # mux loops a too-short bed, and the restart is an audible break). Only when no track
    # covers the runtime, take the longest one (fewest seams). Unknown durations skip this.
    narration = Path(video_dir) / "narration.mp3"
    narr = _safe_duration(narration) if narration.exists() else 0.0
    durs = {c: _safe_duration(c) for c in candidates}
    if narr > 0 and any(d > 0 for d in durs.values()):
        fitting = [c for c in candidates if durs[c] >= narr]
        candidates = fitting or [max(candidates, key=lambda c: durs[c])]
    track = candidates[video_id % len(candidates)]  # deterministic rotation across videos

    credit = _credit_for(track)
    script["music_credit"] = credit  # publisher puts this line in the YouTube description
    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

    with SessionLocal() as s:  # license audit trail, and _resolve_music_path finds it on re-runs
        existing = s.query(Asset).filter_by(video_id=video_id, kind="music").first()
        if existing is None:
            s.add(Asset(video_id=video_id, kind="music", source="incompetech",
                        url_or_path=str(track), license=credit))
            s.commit()

    log.info("music bed for video %s: %s (%s)", video_id, track.name, bucket)
    return str(track)
