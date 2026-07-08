"""Pydantic models for script.json — the contract phase 03/04 read from disk.

Validation here is the anti-slop/anti-hallucination enforcement point: an LLM response
that is missing hooks, payoff nodes, or citations never reaches disk as a valid script.
`extra="ignore"` tolerates minor LLM protocol drift (stray commentary fields) without
weakening the required-field checks that actually matter.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ResearchDepth = Literal["Low", "Med", "High"]


class Citation(BaseModel):
    """One fact + the source that backs it, produced by research_gate before scripting."""

    model_config = ConfigDict(extra="ignore")

    claim: str
    source: str
    verified: bool


class Hook(BaseModel):
    """One 30-45s hook variant: pattern-interrupt -> context/teaser -> on-screen text."""

    model_config = ConfigDict(extra="ignore")

    variant_id: int
    pattern_interrupt: str   # 0-5s: shock stat / claim / haunting image description
    context_teaser: str      # 5-30s: sets scene, promises payoff, no spoiler
    text_overlay: str        # single short sentence rendered on-screen (phase 03/04)


class ShotBeat(BaseModel):
    """One shot-list entry — visual-fetcher (phase 03) turns keywords into stock search terms."""

    model_config = ConfigDict(extra="ignore")

    beat_id: int
    narration_span: str
    keywords: list[str] = Field(min_length=1, max_length=4)
    mood: str


class ScriptOutput(BaseModel):
    """Full script.json payload written by script_generator, read by phase 03/04."""

    model_config = ConfigDict(extra="ignore")

    narration: str
    hooks: list[Hook] = Field(min_length=2, max_length=3)
    pattern: str
    payoff_nodes: list[str] = Field(min_length=5)
    shot_list: list[ShotBeat] = Field(min_length=10)
    title_options: list[str] = Field(min_length=3, max_length=3)
    description: str
    tags: list[str] = Field(min_length=1)
    sources: list[str] = Field(min_length=2)
    citations: list[Citation] = Field(min_length=3)
    research_depth: ResearchDepth
