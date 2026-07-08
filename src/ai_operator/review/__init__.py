"""Telegram review gate: TIER-1 policy gate (per video) + TIER-2 quality batch review.

Publisher (phase 06) only needs `videos.state == approved`; nothing here is imported by
other phases directly. `commands.py:register(app)` is the only cross-package entry point
(auto-mounted by cli.py).
"""
