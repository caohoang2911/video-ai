"""Startup check for critical Python deps that are DECLARED in pyproject but easy to miss when
a venv drifts out of sync (the classic: `sentence-transformers` present in the manifest but
never installed, so gen-topics detonates deep inside an embedding call).

Warn loudly + early at boot so a missing lib surfaces here — with the one-line fix — instead
of as a cryptic ModuleNotFoundError inside a failed job.
"""

from __future__ import annotations

import importlib.util

from ..logging_setup import get_logger

log = get_logger("ops.dependency_check")

# import name -> what breaks without it. Import names, not pip names (sentence_transformers,
# not sentence-transformers; PIL, not pillow).
_CRITICAL: dict[str, str] = {
    "numpy": "scoring + thumbnails",
    "PIL": "thumbnail rendering",
    "sentence_transformers": "topic dedup (gen-topics)",
    "torch": "CLIP relevance + topic dedup",
    "transformers": "CLIP relevance re-ranking",
}


def missing_critical() -> dict[str, str]:
    """Return the subset of critical deps that are NOT importable, {import_name: reason}."""
    return {mod: why for mod, why in _CRITICAL.items() if importlib.util.find_spec(mod) is None}


def warn_if_missing() -> list[str]:
    """Log one prominent warning if any critical dep is missing; return the missing names."""
    missing = missing_critical()
    if missing:
        detail = "; ".join(f"{mod} ({why})" for mod, why in missing.items())
        log.warning(
            "MISSING base dependencies — the venv is out of sync with pyproject. "
            "Run `pip install -e .` in the project venv. Affected: %s",
            detail,
        )
    return list(missing)
