"""Trace which parent still backs each copied child still, by file content hash.

Shorts reuse their parent video's stills, and that reuse copies bytes and nothing else.
Two separate needs depend on knowing where a copied file came from: publish builds the
archival credit block from the CHILD's asset rows, and a later batch needs to know which
parent images its siblings already took. Both are answered by hashing the files, because a
copied still is renamed to the child's own beat index and keeps no reference to the parent
beat it came from.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select

from ..db import SessionLocal
from ..db.models import Asset, Video
from ..logging_setup import get_logger

log = get_logger("ops.shorts_image_provenance")

IMAGE_ASSET_KINDS = ("stock", "archival", "gen")


def still_md5s(video_id: int, output_dir: Path) -> dict[str, Path]:
    """Content hash -> path for every beat still currently on disk for one video.

    `output_dir` is passed in rather than read from config so callers and tests share one
    view of where renders live.
    """
    found: dict[str, Path] = {}
    for path in sorted((output_dir / str(video_id) / "img").glob("beat_*.jpg")):
        try:
            found.setdefault(hashlib.md5(path.read_bytes()).hexdigest(), path)
        except OSError:
            continue
    return found


def credit_copied_images(parent_id: int, *, child_id: int, output_dir: Path) -> None:
    """Mirror the parent's licence rows onto the stills copied into the child.

    Publish builds the archival credit block from the CHILD's own asset rows, so a copied
    still that has no row publishes uncredited — a licence breach for the CC BY-SA files
    among them. Keyed on content hash rather than beat index, so only images actually on
    screen get credited and the stale-row prune keeps them. Idempotent, and fail-open:
    provenance bookkeeping must never sink an otherwise-good render. Child is keyword-only
    because both ids are plain ints and transposing them would credit the wrong video.
    """
    try:
        child_stills = still_md5s(child_id, output_dir)
        if not child_stills:
            return
        with SessionLocal() as s:
            parent_rows = {
                row.md5: row
                for row in s.scalars(
                    select(Asset).where(
                        Asset.video_id == parent_id, Asset.kind.in_(IMAGE_ASSET_KINDS)
                    )
                ).all()
                if row.md5
            }
            already = {
                md5
                for md5 in s.scalars(
                    select(Asset.md5).where(
                        Asset.video_id == child_id, Asset.kind.in_(IMAGE_ASSET_KINDS)
                    )
                ).all()
                if md5
            }
            added = 0
            for md5, path in child_stills.items():
                source_row = parent_rows.get(md5)
                if md5 in already or source_row is None:
                    continue
                s.add(
                    Asset(
                        video_id=child_id,
                        kind=source_row.kind,
                        source=source_row.source,
                        url_or_path=str(path),
                        license=source_row.license,
                        md5=md5,
                    )
                )
                added += 1
            if added:
                s.commit()
                log.info(
                    "short %s: mirrored %s image licence rows from parent %s",
                    child_id, added, parent_id,
                )
    except Exception as exc:  # noqa: BLE001 - provenance must not fail a good render
        # ERROR, not WARNING: this is the only signal that a licensed still shipped
        # uncredited, and the ops dashboard only tails ERROR/ALERT lines.
        log.error(
            "short %s: could not mirror image provenance from parent %s: %s",
            child_id, parent_id, exc, exc_info=True,
        )


def beats_used_by_siblings(parent_id: int, output_dir: Path) -> set[int]:
    """Parent beat ids already on screen in this parent's surviving shorts.

    A batch produced later — a second run, or a re-roll that kept the published shorts —
    starts with an empty in-memory ledger, so without this the highest-scoring parent
    stills get picked again and one frame ends up in several shorts of the same family.
    Discarded shorts are excluded for free: their rows and output dirs are deleted before
    a re-roll starts, which releases their images back to the pool.

    Fail-open like the rest of this module: an unreadable render tree must not abort a
    whole batch, it just costs some visual variety.
    """
    try:
        # Deliberately not still_md5s(): two parent beats can hold identical bytes, and
        # collapsing them would leave the twin looking unused and pickable again.
        beats_of_md5: dict[str, set[int]] = {}
        for path in sorted((output_dir / str(parent_id) / "img").glob("beat_*.jpg")):
            try:
                digest = hashlib.md5(path.read_bytes()).hexdigest()
            except OSError:
                continue
            beats_of_md5.setdefault(digest, set()).add(int(path.stem.split("_")[1]))
        if not beats_of_md5:
            return set()
        with SessionLocal() as s:
            sibling_ids = s.scalars(select(Video.id).where(Video.parent_id == parent_id)).all()
        used: set[int] = set()
        for sibling_id in sibling_ids:
            for md5 in still_md5s(sibling_id, output_dir):
                used |= beats_of_md5.get(md5, set())
        return used
    except Exception as exc:  # noqa: BLE001 - variety bookkeeping must not abort a batch
        log.error("parent %s: could not read sibling image usage: %s", parent_id, exc, exc_info=True)
        return set()
