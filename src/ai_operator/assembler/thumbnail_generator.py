"""3 thumbnail variants generated immediately at render time (not after upload) so
the manual YouTube-Studio A/B test always has candidates ready to go.

Each variant pairs a distinct key-frame with one title option's `thumbnail_text` — the
overlay line written to pair with that specific title (script.json carries 3 title options),
so the A/B title test and thumbnail test line up variant-for-variant.

The HERO (variant a — the primary thumb_path) is chosen for authenticity AND relevance: a
real archival photo that clears the CLIP relevance gate, enhanced with a subject-preserving
FLUX Kontext relight; when no archival is both relevant and available, a synthetic FLUX drama
frame stands in. Variants b/c stay real frames with a PIL cinematic grade — cheaper, and a
more varied A/B set. Every fal step degrades to a PIL grade so a thumbnail is never missing.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from ..config import OUTPUT_DIR, settings
from ..db import SessionLocal
from ..db.models import Asset, Video
from ..logging_setup import get_logger
from ..media import clip_reranker, cloud_flux
from . import thumbnail_frame_score, thumbnail_style

log = get_logger("assembler.thumbnail")

WIDTH, HEIGHT = 1280, 720
N_VARIANTS = 3
VARIANT_LETTERS = "abc"
_SCALE_FILL = f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}"

# Preserve-subject Kontext edit: relight/regrade only, never invent or remove objects — keeps
# a real historical photo defensible (a derivative grade, not a fabrication).
_KONTEXT_INSTRUCTION = (
    "enhance cinematic lighting, contrast and depth; add subtle atmospheric haze; "
    "preserve the subject, composition and all real details exactly; "
    "do NOT add, remove or invent objects; keep photorealistic and natural."
)


def generate(video_id: int) -> list[str]:
    """Write `thumb_a.jpg`, `thumb_b.jpg`, `thumb_c.jpg` under output/<video_id>/ and
    record the primary one on `videos.thumb_path`. Requires assemble() to have run."""
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None or not video.video_path:
            raise ValueError(f"video {video_id} has no rendered video_path yet")
        video_path = Path(video.video_path)
        title = video.title or ""

    video_dir = OUTPUT_DIR / str(video_id)
    overlays = _overlay_texts(video_dir / "script.json")
    archival_ranked, others_ranked, subject = _gated_pools(video_id)
    hero_src, hero_mode, synth_path = _pick_hero(video, archival_ranked, video_id)

    kicker = thumbnail_style.compose_kicker(subject, title)  # clean SUBJECT·YEAR eyebrow, shared

    pool: list[Path] = [hero_src] if hero_src is not None else []
    for p in archival_ranked + others_ranked:
        if p not in pool:
            pool.append(p)
    if not pool:
        pool = [video_path]

    paths = []
    for i in range(N_VARIANTS):
        frame_path = video_dir / f"_thumb_frame_{i}.jpg"
        variant_path = video_dir / f"thumb_{VARIANT_LETTERS[i]}.jpg"
        # each variant's punch line pairs with its title option; fall back to a title-derived
        # hook when that option carried no thumbnail_text (older scripts).
        headline = overlays[i] if i < len(overlays) and overlays[i].strip() else \
            thumbnail_style.fallback_headline(title, subject)
        try:
            _extract_frame(pool[i % len(pool)], frame_path)
            # `_prepare_hero` returns True when the frame is ALREADY cinematically graded
            # (Kontext hero / synthetic) -> skip the PIL grade so it is not double-graded.
            already_graded = _prepare_hero(frame_path, hero_mode, video_id) if i == 0 else False
            _overlay_text(frame_path, headline, variant_path, kicker, grade=not already_graded)
        except Exception as exc:  # noqa: BLE001 - a bad source must never leave a variant missing
            log.warning("thumb variant %s failed (%s) -> plain video keyframe", VARIANT_LETTERS[i], exc)
            _extract_frame(video_path, frame_path)
            _overlay_text(frame_path, headline, variant_path, kicker, grade=True)
        finally:
            frame_path.unlink(missing_ok=True)
        paths.append(str(variant_path))

    if synth_path is not None:
        synth_path.unlink(missing_ok=True)

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
    try:
        script = json.loads(script_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:  # corrupt script -> title-derived headlines
        log.warning("thumbnail overlays: unreadable script.json (%s)", exc)
        return []
    # `or ""` (not the .get default) also coalesces an explicit JSON null thumbnail_text.
    return [(o.get("thumbnail_text") or "").upper() for o in script.get("title_options", [])]


def _caption_free_sources(video_id: int) -> tuple[list[Path], list[Path]]:
    """Raw per-beat visuals as frame sources, split `(archival, others)`. Unlike the final
    render these carry NO burned narration captions, so nothing shows through the overlay
    text. Each group is ordered by filename (== beat order) so equal-scored candidates keep a
    deterministic beat-order tie-break."""
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


def _subject_text(video_id: int) -> str:
    """Event/subject phrase for the relevance gate — the same clean pre-colon anchor the
    archive search uses, so the gate judges against what the video is actually about."""
    from ..media.visual_fetcher import _archival_anchor  # local: avoid import cycle at module load

    try:
        return _archival_anchor(video_id)
    except Exception:  # noqa: BLE001 - gate is best-effort; empty subject => gate skipped
        return ""


def _relevance_gate(paths: list[Path], subject: str, video_id: int) -> list[Path]:
    """Drop archival photos whose CLIP cosine relevance to `subject` is below the threshold —
    a good-looking but wrong-subject archive (wrong ship, wrong livery) must not face the
    video. No-op when CLIP is unavailable or a score can't be taken (best-effort)."""
    if not paths or not subject or not clip_reranker.available():
        return paths
    kept = []
    for p in paths:
        s = clip_reranker.score(subject, p)
        if s is None:  # unreadable / model hiccup -> keep, don't punish on a failed measure
            kept.append(p)
            continue
        log.info("thumb relevance %.3f (min %.2f) subject=%r img=%s",
                 s, settings.THUMB_RELEVANCE_MIN, subject, p.name)
        if s >= settings.THUMB_RELEVANCE_MIN:
            kept.append(p)
    return kept


def _gated_pools(video_id: int) -> tuple[list[Path], list[Path], str]:
    """`(archival_ranked, others_ranked, subject)`: archival filtered by the relevance gate
    then frame-score ranked; other visuals frame-score ranked; the subject phrase used."""
    subject = _subject_text(video_id)
    archival, others = _caption_free_sources(video_id)
    archival = _relevance_gate(archival, subject, video_id)
    return (
        thumbnail_frame_score.rank(archival, N_VARIANTS),
        thumbnail_frame_score.rank(others, N_VARIANTS),
        subject,
    )


def _thumbnail_sources(video_id: int) -> list[Path]:
    """Ordered variant base frames, ARCHIVAL FIRST (relevance-gated), others filling the rest.
    Kept as a thin, directly-testable view of source selection; `generate` adds hero synthesis
    on top."""
    archival_ranked, others_ranked, _ = _gated_pools(video_id)
    picked = list(archival_ranked)
    if len(picked) < N_VARIANTS:
        picked += others_ranked[: N_VARIANTS - len(picked)]
    return picked[:N_VARIANTS]


def _pick_hero(video: Video, archival_ranked: list[Path], video_id: int) -> tuple[Path | None, str | None, Path | None]:
    """Choose the primary-variant source: a gate-passing archival photo ("archival"), else a
    synthetic FLUX drama frame ("synthetic"). Returns `(hero_src, mode, synth_temp)` — mode
    None (with no source) when neither is available and `generate` falls back to the pool."""
    if archival_ranked:
        return archival_ranked[0], "archival", None
    if settings.FAL_KEY:
        try:
            synth = cloud_flux.generate(
                _hero_prompt(video), is_diagram=False, photoreal=True, video_id=video_id
            )
            return synth, "synthetic", synth
        except Exception as exc:  # noqa: BLE001 - never block a thumbnail on the synthetic tier
            log.warning("synthetic hero generation failed (%s) -> falling back to best frame", exc)
    return None, None, None


def _prepare_hero(frame_path: Path, hero_mode: str | None, video_id: int) -> bool:
    """Ready the primary variant's frame; return whether stylize should skip its PIL grade.
    A real archival hero gets a Kontext relight (toggle on); a synthetic hero is already
    cinematic. Both then skip the grade. Kontext failure / toggle off -> PIL grade the frame.
    """
    if hero_mode == "archival" and settings.THUMBNAIL_KONTEXT_ENHANCE:
        enhanced = None
        try:
            enhanced = cloud_flux.kontext_edit(frame_path, _KONTEXT_INSTRUCTION, video_id=video_id)
            _extract_frame(enhanced, frame_path)  # rescale Kontext output back to WIDTHxHEIGHT
            return True  # already graded -> skip PIL grade
        except Exception as exc:  # noqa: BLE001 - degrade to PIL grade, never a missing thumb
            log.warning("Kontext enhance failed (%s) -> PIL grade", exc)
            return False
        finally:
            if enhanced is not None:  # drop the Kontext temp even if the rescale raised
                enhanced.unlink(missing_ok=True)
    return hero_mode == "synthetic"  # synthetic already cinematic; archival w/o Kontext -> grade


def _hero_prompt(video: Video) -> str:
    """Cinematic dark synthetic-hero prompt anchored on the video's subject (pre-colon/dash)."""
    subject = re.split(r":| — | – | -- ", (video.title or "").strip(), maxsplit=1)[0].strip()
    subject = subject or settings.NICHE
    return (
        f"cinematic documentary movie-poster still of {subject}, dramatic low-key lighting, "
        "moody atmosphere, volumetric haze, deep shadows, teal and amber color grade, "
        "photorealistic, ultra detailed, no text, no watermark"
    )


def _extract_frame(src: Path, out_path: Path) -> None:
    """One WIDTHxHEIGHT frame from `src`: a mid-ish frame for a b-roll clip, the scaled image
    for a still. Aspect is filled-and-cropped (no distortion)."""
    seek = ["-ss", "1"] if src.suffix.lower() == ".mp4" else []  # 1s in; every clip is longer
    cmd = ["ffmpeg", "-y", *seek, "-i", str(src), "-frames:v", "1", "-vf", _SCALE_FILL, str(out_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extract failed for {src.name}: {result.stderr[-500:]}")


def _overlay_text(frame_path: Path, text: str, out_path: Path, kicker: str, grade: bool = True) -> None:
    """Cinematic grade (optional) + vignette, then the negative-space poster headline (see
    thumbnail_style) under the shared brass `kicker`."""
    img = thumbnail_style.stylize(Image.open(frame_path), grade=grade)
    thumbnail_style.draw_title(img, text, kicker=kicker)
    img.save(out_path, "JPEG", quality=92)
