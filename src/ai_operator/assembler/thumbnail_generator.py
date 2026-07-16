"""3 thumbnail variants generated immediately at render time (not after upload) so
the manual YouTube-Studio A/B test always has candidates ready to go.

Each variant pairs a distinct key-frame with one title option's `thumbnail_text` — the
overlay line written to pair with that specific title (script.json carries 3 title options),
so the A/B title test and thumbnail test line up variant-for-variant instead of overlaying a
generic hook line on every frame.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from ..config import OUTPUT_DIR
from ..db import SessionLocal
from ..db.models import Asset, Video
from ..logging_setup import get_logger
from . import thumbnail_frame_score, thumbnail_style

log = get_logger("assembler.thumbnail")

WIDTH, HEIGHT = 1280, 720
N_VARIANTS = 3
VARIANT_LETTERS = "abc"
_SCALE_FILL = f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}"


def generate(video_id: int) -> list[str]:
    """Write `thumb_a.jpg`, `thumb_b.jpg`, `thumb_c.jpg` under output/<video_id>/ and
    record the primary one on `videos.thumb_path`. Requires assemble() to have run."""
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None or not video.video_path:
            raise ValueError(f"video {video_id} has no rendered video_path yet")
        video_path = Path(video.video_path)

    video_dir = OUTPUT_DIR / str(video_id)
    overlays = _overlay_texts(video_dir / "script.json")
    sources = _thumbnail_sources(video_id) or [video_path]

    paths = []
    for i in range(N_VARIANTS):
        frame_path = video_dir / f"_thumb_frame_{i}.jpg"
        variant_path = video_dir / f"thumb_{VARIANT_LETTERS[i]}.jpg"
        _extract_frame(sources[i % len(sources)], frame_path)
        _overlay_text(frame_path, overlays[i] if i < len(overlays) else "", variant_path)
        frame_path.unlink(missing_ok=True)
        paths.append(str(variant_path))

    with SessionLocal() as session:
        video = session.get(Video, video_id)
        video.thumb_path = paths[0]
        session.commit()
    return paths


def _overlay_texts(script_path: Path) -> list[str]:
    """Thumbnail overlay lines, one per title option (dict access — script.json entries are
    `{title, thumbnail_text}`, not pydantic objects). Empty when script.json is absent."""
    if not script_path.exists():
        return []
    script = json.loads(script_path.read_text(encoding="utf-8"))
    return [o.get("thumbnail_text", "").upper() for o in script.get("title_options", [])]


def _caption_free_sources(video_id: int) -> tuple[list[Path], list[Path]]:
    """Raw per-beat visuals as frame sources, split `(archival, others)`. Unlike the final
    render these carry NO burned narration captions, so nothing shows through the overlay
    text. Each group is ordered by filename (== beat order) so equal-scored candidates —
    e.g. unreadable files that all rank -inf — keep a deterministic beat-order tie-break."""
    with SessionLocal() as session:
        rows = session.execute(
            select(Asset).where(
                Asset.video_id == video_id,
                Asset.kind.in_(("archival", "video_broll", "gen", "stock")),
            )
        ).scalars().all()
    archival, others = [], []
    for r in rows:
        p = Path(r.url_or_path)
        if p.exists():
            (archival if r.kind == "archival" else others).append(p)
    return sorted(archival, key=lambda p: p.name), sorted(others, key=lambda p: p.name)


def _thumbnail_sources(video_id: int) -> list[Path]:
    """Frame sources for the variants, ARCHIVAL FIRST: in a history niche a real photograph
    thumbnail reads as authentic research (vs an AI-looking frame), so variant `a` — the
    primary thumb_path — is always an archival photo when one exists. Remaining slots fill
    from the other visuals. Within each group candidates are ranked by frame score (contrast
    + detail, text-dense and flat frames penalized) instead of beat position, so a dull or
    typography-heavy photo never becomes the face of the video. Unscoreable sources (b-roll
    mp4s PIL can't open) sink to the bottom but remain usable as a last resort."""
    archival, others = _caption_free_sources(video_id)
    picked = thumbnail_frame_score.rank(archival, N_VARIANTS)
    if len(picked) < N_VARIANTS:
        picked += thumbnail_frame_score.rank(others, N_VARIANTS - len(picked))
    return picked


def _extract_frame(src: Path, out_path: Path) -> None:
    """One WIDTHxHEIGHT frame from `src`: a mid-ish frame for a b-roll clip, the scaled image
    for a still. Aspect is filled-and-cropped (no distortion)."""
    seek = ["-ss", "1"] if src.suffix.lower() == ".mp4" else []  # 1s in; every clip is longer
    cmd = ["ffmpeg", "-y", *seek, "-i", str(src), "-frames:v", "1", "-vf", _SCALE_FILL, str(out_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extract failed for {src.name}: {result.stderr[-500:]}")


def _overlay_text(frame_path: Path, text: str, out_path: Path) -> None:
    """Bold-documentary treatment: cinematic grade + vignette + dark band, then the big
    yellow stroked overlay line (see thumbnail_style)."""
    img = thumbnail_style.stylize(Image.open(frame_path))
    thumbnail_style.draw_title(img, text)
    img.save(out_path, "JPEG", quality=92)
