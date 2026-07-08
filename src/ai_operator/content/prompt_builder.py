"""Assemble the script-generation prompt from on-disk prompts/*.md templates.

Prompt wording lives outside code (prompts/) so the anti-slop rules, hook structure,
and pacing grid — the highest-churn part of this pipeline — can be tuned without a
code change or redeploy.
"""

from __future__ import annotations

from ..config import PROMPTS_DIR

_SYSTEM_PATH = PROMPTS_DIR / "script_system.md"
_TEMPLATE_DIR = PROMPTS_DIR / "script_templates"

DEFAULT_WORD_TARGET = 1800  # ~12 min narration at ~150 wpm, mid-point of the 1200-2200 range


def load_system_prompt() -> str:
    return _SYSTEM_PATH.read_text(encoding="utf-8")


def load_pattern_template(pattern: str) -> str:
    path = _TEMPLATE_DIR / f"{pattern}.md"
    if not path.exists():
        raise FileNotFoundError(f"no narrative-pattern template for '{pattern}' at {path}")
    return path.read_text(encoding="utf-8")


def build_user_prompt(
    *,
    topic_title: str,
    angle: str,
    pattern: str,
    template_text: str,
    citations: list[dict],
    word_target: int = DEFAULT_WORD_TARGET,
) -> str:
    """Combine pattern template + topic + verified facts into the final user turn."""
    citation_lines = "\n".join(
        f"- {c['claim']} (source: {c['source']})" for c in citations if c.get("verified")
    )
    if not citation_lines:
        citation_lines = "(no independently verified claims — rely only on well-established public facts)"

    return (
        f"NARRATIVE PATTERN: {pattern}\n{template_text}\n\n"
        f"TOPIC: {topic_title}\n"
        f"ANGLE (unique POV — build the whole script around this): {angle or 'none given, infer one'}\n\n"
        "VERIFIED FACTS (paraphrase in your own words; do not quote verbatim; do not "
        f"invent facts beyond these):\n{citation_lines}\n\n"
        f"Target narration length: ~{word_target} words (8-15 minutes at ~150 wpm).\n"
        "Output ONLY minified JSON matching the schema in the system prompt — no markdown "
        "fences, no commentary before or after."
    )
