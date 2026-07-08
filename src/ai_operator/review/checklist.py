"""Checklist tickboxes are a review AID only — they never move `videos.state` or write a
`decisions` audit row (that would let a reviewer "pass" by ticking boxes instead of
actually deciding). State persists via app_state_store so it survives a bot restart.
"""

from __future__ import annotations

from .app_state_store import get_json, set_json
from .keyboards import CHECKLIST_ITEMS, checklist_keyboard


def _key(video_id: int) -> str:
    return f"checklist:{video_id}"


def toggle_item(video_id: int, item: str) -> None:
    if item not in CHECKLIST_ITEMS:
        return
    state = get_json(_key(video_id)) or {}
    state[item] = not state.get(item, False)
    set_json(_key(video_id), state)


def render_checklist(video_id: int):
    state = get_json(_key(video_id)) or {}
    return checklist_keyboard(video_id, state)
