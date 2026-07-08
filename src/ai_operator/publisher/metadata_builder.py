"""Builds the `videos.insert` request body (snippet + status) from script.json.

Encodes the channel's compliance posture: explicit AI-disclosure text in the
description (on top of the `containsSyntheticMedia` API flag), source citations,
and a music credit line — all required by the documentary-channel content policy.
"""

from __future__ import annotations

import json
from pathlib import Path

MAX_TITLE_LEN = 100          # YouTube hard cap
MAX_DESCRIPTION_LEN = 5000   # YouTube hard cap
DEFAULT_MUSIC_CREDIT = "Music: royalty-free tracks (see channel About page for licenses)."
AI_DISCLOSURE = (
    "[AI disclosure] This video's narration, imagery, and editing were produced "
    "with AI assistance and reviewed by a human before publishing."
)


def load_script(script_path: str | Path) -> dict:
    """Read the phase-02 script.json artifact (narration, titles, sources, tags...)."""
    return json.loads(Path(script_path).read_text(encoding="utf-8"))


def build_description(script: dict, *, music_credit: str = DEFAULT_MUSIC_CREDIT) -> str:
    """Compose the public description: base copy + sources + music credit + AI disclosure."""
    base = (script.get("description") or "").strip()
    sources = script.get("sources") or []
    parts = [base] if base else []
    if sources:
        parts.append("Sources:\n" + "\n".join(f"- {s}" for s in sources))
    parts.append(music_credit)
    parts.append(AI_DISCLOSURE)
    return "\n\n".join(p for p in parts if p)[:MAX_DESCRIPTION_LEN]


def pick_title(script: dict, override: str | None = None) -> str:
    """Choose the video title: explicit override (e.g. a picked A/B winner) or the
    first `title_options` entry from script.json, truncated to the 100-char cap."""
    options = script.get("title_options") or []
    title = override or (options[0] if options else script.get("title") or "Untitled")
    return title[:MAX_TITLE_LEN]


def build_upload_body(
    script: dict,
    *,
    publish_at_iso: str,
    category_id: str,
    title_override: str | None = None,
) -> dict:
    """Assemble the `videos.insert` request body.

    `publishAt` only takes effect when `privacyStatus="private"` — YouTube silently
    ignores it otherwise, so private isn't just a safety default, it's required for
    scheduling. `selfDeclaredMadeForKids` must be set explicitly (the channel
    default isn't trustworthy) and `containsSyntheticMedia` drives the on-platform
    AI-generated-content label.
    """
    return {
        "snippet": {
            "title": pick_title(script, title_override),
            "description": build_description(script),
            "tags": script.get("tags") or [],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at_iso,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }
