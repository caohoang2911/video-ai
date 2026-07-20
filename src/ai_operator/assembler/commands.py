"""CLI for the assemble step -- mounted into the shared Typer app by cli.py."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import typer

from ..config import OUTPUT_DIR
from ..logging_setup import get_logger, setup_logging
from .thumbnail_generator import VARIANT_LETTERS, generate as generate_thumbnails
from .video_builder import assemble_video

log = get_logger("assembler.cli")


def register(app: typer.Typer) -> None:
    @app.command("assemble")
    def assemble(
        video_id: int = typer.Option(..., "--video-id", help="Video row id to assemble."),
    ) -> None:
        """Render final.mp4 (Ken Burns + captions + ducked music + branding), then
        generate the 3 thumbnail variants for later manual A/B."""
        setup_logging()
        result = assemble_video(video_id)
        typer.echo(f"Rendered {result['video_path']} ({result['duration_sec']}s)")

        thumbs = generate_thumbnails(video_id)
        typer.echo(f"Thumbnails: {', '.join(thumbs)}")

    @app.command("thumbs")
    def thumbs(
        video_id: int = typer.Option(..., "--video-id", help="Video row id to re-thumbnail."),
        backup: bool = typer.Option(True, help="Copy existing variants aside before overwriting."),
        same_hero: bool = typer.Option(
            False, "--same-hero", help="One shared hero image; variants differ only in headline."
        ),
    ) -> None:
        """Regenerate the 3 thumbnail variants from the already-rendered video and its
        stored assets — no re-encode. Used to bring an older video's thumbnails onto the
        current design, and to refresh the A/B variant set.

        `--same-hero` holds the image fixed so a Studio A/B test varies only the headline;
        otherwise a winning variant cannot be attributed to image or copy."""
        setup_logging()
        if backup:
            saved = _backup_variants(video_id)
            if saved:
                typer.echo(f"Backed up {len(saved)} existing variant(s) -> {saved[0].parent}")

        thumbs = generate_thumbnails(video_id, same_hero=same_hero)
        typer.echo(f"Thumbnails: {', '.join(thumbs)}")


def _backup_variants(video_id: int) -> list[Path]:
    """Copy the current thumb_*.jpg aside so a regenerated set never destroys the variants
    that may already be live on YouTube. Returns the backup copies written."""
    video_dir = OUTPUT_DIR / str(video_id)
    # A timestamp alone is not enough: two regenerations can land in the same second while
    # iterating, and a shared folder means the second copy overwrites the originals this
    # backup exists to protect. Take the first free name instead.
    stamp = f"{datetime.now():%y%m%d-%H%M%S}"
    dest = video_dir / f"_thumb_backup_{stamp}"
    attempt = 2
    while dest.exists():
        dest = video_dir / f"_thumb_backup_{stamp}-{attempt}"
        attempt += 1
    saved: list[Path] = []
    for letter in VARIANT_LETTERS:
        src = video_dir / f"thumb_{letter}.jpg"
        if not src.exists():
            continue
        dest.mkdir(parents=True, exist_ok=True)
        copy = dest / src.name
        shutil.copy2(src, copy)
        saved.append(copy)
    return saved
