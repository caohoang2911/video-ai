"""Pure inline-keyboard builders — no DB access here.

Keeping layout separate from what triggers it (see checklist.py / callbacks.py) means the
keyboard shape can change without touching decision or state logic.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import decision_codes as dc

CHECKLIST_ITEMS: tuple[str, ...] = (
    "audio", "video", "caption", "policy", "visuals",
    # EDSA (Educational/Documentary/Scientific/Artistic) evidence — the concrete signals that
    # earn YouTube's documentary exception. `edsa5w` asks the reviewer to confirm the facts are
    # spoken in the AUDIO (not just in metadata); hook/payoff confirm the editorial structure.
    "edsa5w", "hook", "payoff",
)

# Descriptive labels for items whose short callback key isn't self-explanatory; anything not
# listed falls back to the key itself (the original single-word items read fine as-is).
CHECKLIST_LABELS: dict[str, str] = {
    "edsa5w": "WHO/WHAT/WHEN/WHERE/WHY in narration?",
    "hook": "hook present",
    "payoff": "payoff present",
}


def tier1_keyboard(video_id: int, preview_url: str | None = None) -> InlineKeyboardMarkup:
    """TIER-1 POLICY gate — required before a video can open TIER-2 quality review."""
    rows = [
        [
            InlineKeyboardButton("PASS_POLICY", callback_data=f"{dc.PASS_POLICY}:{video_id}"),
            InlineKeyboardButton("Reject", callback_data=f"REJECT_POLICY:{video_id}"),
        ],
        [InlineKeyboardButton("Checklist", callback_data=f"CHECKLIST:{video_id}")],
    ]
    if preview_url:
        rows.append([InlineKeyboardButton("Full Preview", url=preview_url)])
    return InlineKeyboardMarkup(rows)


def tier2_keyboard(video_id: int) -> InlineKeyboardMarkup:
    """TIER-2 QUALITY batch review — does not gate publish, feeds the content-engine."""
    rows = [
        [
            InlineKeyboardButton("PASS_QUALITY", callback_data=f"{dc.PASS_QUALITY}:{video_id}"),
            InlineKeyboardButton("Edit", callback_data=f"EDIT:{video_id}"),
        ],
        [InlineKeyboardButton("Hold / Rerun", callback_data=f"{dc.HOLD_RERUN}:{video_id}")],
        [InlineKeyboardButton("Checklist", callback_data=f"CHECKLIST:{video_id}")],
    ]
    return InlineKeyboardMarkup(rows)


def reason_picker_keyboard(
    prefix: str, reasons: tuple[str, ...], video_id: int
) -> InlineKeyboardMarkup:
    """Sub-menu that forces a specific code — never a bare binary reject/edit tap."""
    buttons = [
        InlineKeyboardButton(reason, callback_data=f"{prefix}{reason}:{video_id}")
        for reason in reasons
    ]
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    return InlineKeyboardMarkup(rows)


def checklist_keyboard(video_id: int, checked: dict[str, bool]) -> InlineKeyboardMarkup:
    """Tickbox inline keyboard — a review aid only, never writes a decision or moves state."""
    rows = [
        [
            InlineKeyboardButton(
                f"{'✅' if checked.get(item) else '⬜'} {CHECKLIST_LABELS.get(item, item)}",
                callback_data=f"CHK_{item.upper()}:{video_id}",
            )
        ]
        for item in CHECKLIST_ITEMS
    ]
    rows.append([InlineKeyboardButton("Back", callback_data=f"CHK_BACK:{video_id}")])
    return InlineKeyboardMarkup(rows)
