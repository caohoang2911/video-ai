"""Logging: rotating file + stdout. Configured once; never logs secret values."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import LOG_DIR, settings

_CONFIGURED = False


def setup_logging(level: str | None = None) -> logging.Logger:
    """Attach handlers to the `operator` logger tree (idempotent)."""
    global _CONFIGURED
    root = logging.getLogger("operator")
    if _CONFIGURED:
        return root

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root.setLevel(level or settings.LOG_LEVEL)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s:%(module)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        LOG_DIR / "operator.log", maxBytes=5_000_000, backupCount=3
    )
    file_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    root.propagate = False
    _CONFIGURED = True
    return root


def get_logger(name: str) -> logging.Logger:
    """Child logger under the `operator` namespace."""
    return logging.getLogger(f"operator.{name}")
