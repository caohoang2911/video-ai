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
# Name-agnostic on purpose: the channel name lives in Studio/About, not baked into every
# upload body, so a rebrand never requires re-editing published descriptions or this code.
SUBSCRIBE_CTA = "🔔 New documentary every week — subscribe so these stories aren't forgotten again."
AI_DISCLOSURE = (
    "[AI disclosure] This video's narration, imagery, and editing were produced "
    "with AI assistance and reviewed by a human before publishing."
)


def load_script(script_path: str | Path) -> dict:
    """Read the phase-02 script.json artifact (narration, titles, sources, tags...)."""
    return json.loads(Path(script_path).read_text(encoding="utf-8"))


def normalize_hashtags(raw: list[str], limit: int = 5) -> list[str]:
    """`['Ship Wreck', '#MaritimeHistory']` -> `['#ShipWreck', '#MaritimeHistory']`.

    YouTube hashtags cannot contain spaces and the first 3 render above the title, so strip
    spaces/punctuation, force a single leading '#', drop blanks/dupes, and cap the count."""
    seen: set[str] = set()
    out: list[str] = []
    for h in raw:
        token = "".join(ch for ch in str(h) if ch.isalnum())  # drop '#', spaces, punctuation
        if not token:
            continue
        tag = f"#{token}"
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            out.append(tag)
        if len(out) >= limit:
            break
    return out


def build_description(
    script: dict, *, music_credit: str = DEFAULT_MUSIC_CREDIT, include_cta: bool = True
) -> str:
    """Compose the public description: base hook + subscribe CTA + sources + music credit +
    AI disclosure + hashtags (last line; YouTube surfaces the first 3 above the title). The
    hook stays first (SEO/engagement) and hashtags stay last (discovery); everything the
    channel adds sits in between."""
    base = (script.get("description") or "").strip()
    sources = script.get("sources") or []
    parts = [base] if base else []
    if include_cta:
        parts.append(SUBSCRIBE_CTA)  # after the hook, before the reference/credit block
    if sources:
        parts.append("Sources:\n" + "\n".join(f"- {s}" for s in sources))
    parts.append(music_credit)
    parts.append(AI_DISCLOSURE)
    hashtags = normalize_hashtags(script.get("hashtags") or [])
    if hashtags:
        parts.append(" ".join(hashtags))
    return "\n\n".join(p for p in parts if p)[:MAX_DESCRIPTION_LEN]


def pick_title(script: dict, override: str | None = None) -> str:
    """Choose the video title: explicit override (e.g. a picked A/B winner) or the first
    `title_options` entry from script.json, truncated to the 100-char cap.

    Disk-loaded `title_options` entries are `{title, thumbnail_text}` dicts, not bare
    strings — read `opt["title"]`, never attribute-access."""
    options = script.get("title_options") or []
    first = options[0].get("title") if options else None
    title = override or first or script.get("title") or "Untitled"
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
