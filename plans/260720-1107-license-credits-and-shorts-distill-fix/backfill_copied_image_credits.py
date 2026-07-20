"""One-off: give already-rendered shorts the licence rows their copied stills never got.

Shorts rendered before the render path started mirroring provenance carry parent stills
with no Asset row of their own, so they would publish with no archival credit. The render
path self-credits from now on, so this runs exactly once and is deliberately NOT a CLI
subcommand — a permanent command for a one-shot job is dead surface forever.

Inserts only, idempotent (the helper skips md5s the child already has). Run it deliberately
against the live DB, never from a hook or the scheduler:

    PYTHONPATH=src .venv/bin/python plans/260720-1107-license-credits-and-shorts-distill-fix/backfill_copied_image_credits.py
"""
from __future__ import annotations

from sqlalchemy import select

from ai_operator.config import OUTPUT_DIR
from ai_operator.db import SessionLocal
from ai_operator.db.models import Asset, Video
from ai_operator.ops.shorts_image_provenance import (
    IMAGE_ASSET_KINDS,
    credit_copied_images,
    still_md5s,
)


def _shorts_missing_image_rows() -> list[tuple[int, int]]:
    """(child_id, parent_id) for every short that has stills on disk but no image rows."""
    with SessionLocal() as s:
        children = s.execute(
            select(Video.id, Video.parent_id).where(
                Video.kind == "short", Video.parent_id.is_not(None)
            )
        ).all()
        rows_by_child = {
            child_id
            for (child_id,) in s.execute(
                select(Asset.video_id).where(Asset.kind.in_(IMAGE_ASSET_KINDS)).distinct()
            ).all()
        }
    return [
        (child_id, parent_id)
        for child_id, parent_id in children
        if child_id not in rows_by_child and still_md5s(child_id, OUTPUT_DIR)
    ]


def main() -> None:
    targets = _shorts_missing_image_rows()
    if not targets:
        print("nothing to backfill")
        return
    print(f"backfilling {len(targets)} shorts: {[c for c, _ in targets]}")
    for child_id, parent_id in targets:
        credit_copied_images(parent_id, child_id=child_id, output_dir=OUTPUT_DIR)

    # Verify: every row now on a backfilled child must match a still actually on disk,
    # otherwise the stale-row prune would delete it on the next re-roll.
    with SessionLocal() as s:
        for child_id, _ in targets:
            on_disk = set(still_md5s(child_id, OUTPUT_DIR))
            in_db = {
                md5
                for md5 in s.scalars(
                    select(Asset.md5).where(
                        Asset.video_id == child_id, Asset.kind.in_(IMAGE_ASSET_KINDS)
                    )
                ).all()
                if md5
            }
            status = "ok" if in_db and in_db <= on_disk else "CHECK"
            print(f"  short {child_id}: {len(in_db)}/{len(on_disk)} stills credited [{status}]")


if __name__ == "__main__":
    main()
