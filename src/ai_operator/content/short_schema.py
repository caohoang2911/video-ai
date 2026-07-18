"""Schema for one auto-generated YouTube Short script (child of a main documentary).

The curiosity-gap contract is the make-or-break: narration must deliver exactly one
satisfying verified fact and then WITHHOLD the twist, closing on an open question whose
payoff lives only in the full video. The validators reject the two failure modes —
a bare teaser (no fact, too short) and a spoiler (question missing / statement ending).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NARRATION_MIN_WORDS = 60   # ~25s at documentary TTS pace — below this it's a bare teaser
NARRATION_MAX_WORDS = 130  # ~50s — above this the render can exceed the 60s Shorts cap


class ShortBeat(BaseModel):
    """One visual beat; keywords map onto the PARENT's already-acquired assets."""

    model_config = ConfigDict(extra="ignore")

    keywords: list[str] = Field(min_length=1, max_length=4)
    mood: str


class ShortScript(BaseModel):
    """One self-contained ~30-45s short: hook overlay, punchy narration, curiosity close."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=8, max_length=100)
    # Primary on-screen hook: a white-set / red-gap curiosity HEADLINE burned on the top band,
    # 7-14 words on two lines split by '\n' (setup line + gap line). The renderer reds the
    # number/last line. Empty default keeps pre-headline scripts valid (they fall back below).
    # max_length is a sanity ceiling only — headroom above the 14-word validator so a valid
    # 14-word headline of long words is never rejected by the char cap before the word check.
    overlay_headline: str = Field(default="", max_length=140)
    # Legacy <=6-word hook — now optional, kept only as the render fallback for old scripts.
    text_overlay: str = Field(default="", max_length=60)
    narration: str
    # 5-6 beats over ~40s ≈ a new visual every 5-7s — the retention pacing for stills-based
    # Shorts; 3 stays the floor so pre-pacing scripts and terse LLM outputs still validate.
    beats: list[ShortBeat] = Field(min_length=3, max_length=7)
    curiosity_question: str
    # End-card copy: 2 punchy fragments (<=5 words each), NOT the spoken question repeated —
    # e.g. "Most neighborhoods rebuilt.\nThis one vanished." Empty -> card falls back to the
    # curiosity question (pre-field scripts).
    end_card_text: str = Field(default="", max_length=90)
    hashtags: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("narration")
    @classmethod
    def _narration_word_count(cls, v: str) -> str:
        words = len(v.split())
        if not NARRATION_MIN_WORDS <= words <= NARRATION_MAX_WORDS:
            raise ValueError(
                f"narration must be {NARRATION_MIN_WORDS}-{NARRATION_MAX_WORDS} words, got {words}"
            )
        return v

    @field_validator("curiosity_question")
    @classmethod
    def _must_be_open_question(cls, v: str) -> str:
        v = v.strip()
        if not v or not v.endswith("?"):
            raise ValueError("curiosity_question must be a non-empty open question ending with '?'")
        return v

    @field_validator("overlay_headline")
    @classmethod
    def _headline_word_count(cls, v: str) -> str:
        # 7-14 words is the history-niche sweet spot (a terse fragment under-hooks, a longer
        # line goes unread at phone size); newline is the setup/gap break, not a word.
        v = v.strip()
        if v:
            n = len(v.replace("\n", " ").split())
            if not 7 <= n <= 14:
                raise ValueError(f"overlay_headline must be 7-14 words, got {n}")
        return v

    @model_validator(mode="after")
    def _needs_a_hook(self) -> "ShortScript":
        # A muted-autoplay short with no on-screen hook is dead on arrival; require at least
        # the new headline or the legacy overlay so the render always has a hook line.
        if not (self.overlay_headline.strip() or self.text_overlay.strip()):
            raise ValueError("short needs an overlay_headline (or legacy text_overlay)")
        return self
