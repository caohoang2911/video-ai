"""Caption text for the TIER-1 review message.

Section headers + the metadata a reviewer needs to actually inspect the cut (not just
rubber-stamp it): duration, research depth, script snippet, and how many visual assets
went into the render.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select

from ..db.engine import SessionLocal
from ..db.models import Asset, Video


def build_caption(video: Video) -> str:
    tags_preview = ", ".join((video.tags or [])[:5]) or "none"
    duration = f"{video.duration_sec}s" if video.duration_sec else "unknown"
    snippet = (video.description or "")[:200] or "(no description)"
    research_depth = _research_depth(video.script_path)
    fact_summary = _fact_summary(video.script_path)
    asset_count = _asset_count(video.id)
    # Surface the re-voice block up front so the reviewer knows an approval tap will bounce
    # (the callback handler hard-blocks PASS_* until `revoice` restores the brand voice).
    revoice_warn = "⚠ NEEDS RE-VOICE — approval blocked until `revoice` runs\n\n" if video.needs_revoice else ""

    # Plain text (no Markdown): AI-generated titles/descriptions routinely contain
    # unbalanced _ * ` [ chars that make Telegram reject a Markdown-parsed caption with
    # HTTP 400, which would stall the review gate. Cosmetic emphasis isn't worth that risk.
    return (
        f"TIER-1 POLICY REVIEW — video #{video.id}\n\n"
        f"{revoice_warn}"
        f"Title: {video.title or '(untitled)'}\n"
        f"Duration: {duration}  ·  Research depth: {research_depth}  ·  Visuals: {asset_count}\n"
        f"Fact-check: {fact_summary}\n"
        f"Tags: {tags_preview}\n\n"
        f"Description snippet:\n{snippet}\n\n"
        f"Check: audio · video · caption · policy-flags · visuals"
    )


def _research_depth(script_path: str | None) -> str:
    if not script_path:
        return "unknown"
    path = Path(script_path)
    if not path.exists():
        return "unknown"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    return data.get("research_depth", "unknown")


def _fact_summary(script_path: str | None) -> str:
    """`N ok / N weak / N review` from the flag-only cross-check, so the reviewer sees the
    machine-checked confidence signal at the gate. `review` count is the one to eyeball —
    it means Wikipedia contradicted the claim or the skeptic called it unsupported."""
    if not script_path or not Path(script_path).exists():
        return "n/a"
    try:
        data = json.loads(Path(script_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "n/a"
    counts = {"ok": 0, "weak": 0, "review": 0, "unflagged": 0}
    for c in data.get("citations", []):
        counts[c.get("fact_status") or "unflagged"] = counts.get(c.get("fact_status") or "unflagged", 0) + 1
    parts = [f"{counts[k]} {k}" for k in ("ok", "weak", "review", "unflagged") if counts[k]]
    return " / ".join(parts) if parts else "n/a"


def _asset_count(video_id: int) -> int:
    with SessionLocal() as s:
        count = s.scalar(select(func.count()).select_from(Asset).where(Asset.video_id == video_id))
    return int(count or 0)
