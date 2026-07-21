"""Script generation: research_gate -> pattern pick -> Claude -> validate -> persist.

The only place a Video row + script.json get created for a topic. JSON-invalid LLM
output is retried (per spec: twice) before giving up — a script still broken after
three attempts needs a human look, not a fourth automatic retry.
"""

from __future__ import annotations

import json

from pydantic import ValidationError
from sqlalchemy import select

from .. import checkpoint
from ..config import OUTPUT_DIR
from ..db import VideoState, assert_transition
from ..config import settings
from ..db.engine import SessionLocal
from ..db.models import Topic, Video
from ..logging_setup import get_logger
from . import fact_crosscheck, pattern_tracker, prompt_builder, topic_backlog
from .llm_client import complete, parse_json
from .research_gate import research
from .schema import ScriptOutput

log = get_logger("content.script_generator")

MAX_JSON_RETRIES = 2                # spec: retry twice on invalid JSON before giving up
CHECKPOINT_STEP = "script_generated"

# Original-value gate: a documentary-exempt script must land enough genuinely surprising
# payoff beats, else it reads as mass-produced filler AND retention sags mid-video. Three
# checks, tuned in one place; a rejected script is logged so thresholds can be loosened if
# they stall real production:
#   - enough STRONG nodes (>= MIN_SCORE),
#   - a healthy AVERAGE (one great twist can't carry five flat beats),
#   - at most one WEAK node (score <= 2) — two "common knowledge" beats is exactly the
#     mid-video sag where viewers drop off.
STRONG_PAYOFF_MIN_SCORE = 3
STRONG_PAYOFF_MIN_COUNT = 3
PAYOFF_MIN_AVG = 3.0
PAYOFF_WEAK_SCORE = 2
PAYOFF_MAX_WEAK_COUNT = 1


def generate(topic: Topic) -> ScriptOutput:
    """Produce and persist script.json/.txt for `topic`; sets videos.state=scripted."""
    video_id = _get_or_create_video(topic)

    cached = _load_if_done(video_id)
    if cached is not None:
        log.info("script already generated for video %d (checkpoint hit) — skipping", video_id)
        return cached

    try:
        research_result = research(topic.title, topic.angle or "", video_id=video_id)
    except Exception:
        _fail_video(video_id, "research_gate rejected topic (insufficient/low-confidence sourcing)")
        raise

    pattern = pattern_tracker.choose_pattern()
    system = prompt_builder.load_system_prompt()
    user = prompt_builder.build_user_prompt(
        topic_title=topic.title,
        angle=topic.angle or "",
        pattern=pattern,
        template_text=prompt_builder.load_pattern_template(pattern),
        citations=[c.model_dump() for c in research_result["citations"]],
    )

    # Flag-only independent cross-check AFTER the prompt is built (so the LLM sees the raw
    # citations, not our verdicts) but BEFORE _generate_with_retry merges them into the
    # persisted script. Never blocks — verify() returns citations unchanged on any failure.
    if settings.FACT_CROSSCHECK_ENABLED:
        research_result["citations"] = fact_crosscheck.verify(
            topic.title, topic.angle or "", research_result["citations"], video_id=video_id
        )

    script = _generate_with_retry(system, user, research_result, video_id)
    _enforce_payoff_gate(video_id, script)

    _persist(video_id, script)
    topic_backlog.mark_used(topic.id)
    return script


def _enforce_payoff_gate(video_id: int, script: ScriptOutput) -> None:
    """Fail the video (no downstream steps) unless the script fields enough strong payoffs.

    This is a content-quality reject, not a JSON-validity retry: re-prompting rarely turns a
    flat topic into a surprising one, so mirror the research-reject path and fail hard for a
    human look — same as `research_gate` rejecting insufficient sourcing.
    """
    scores = [n.surprise_score for n in script.payoff_nodes]
    strong = sum(1 for s in scores if s >= STRONG_PAYOFF_MIN_SCORE)
    weak = sum(1 for s in scores if s <= PAYOFF_WEAK_SCORE)
    avg = sum(scores) / len(scores) if scores else 0.0

    reason = None
    if strong < STRONG_PAYOFF_MIN_COUNT:
        reason = (
            f"weak payoff structure: {strong} node(s) scoring >= {STRONG_PAYOFF_MIN_SCORE} "
            f"(need {STRONG_PAYOFF_MIN_COUNT})"
        )
    elif avg < PAYOFF_MIN_AVG:
        reason = f"weak payoff structure: average surprise {avg:.1f} < {PAYOFF_MIN_AVG} (flat overall)"
    elif weak > PAYOFF_MAX_WEAK_COUNT:
        reason = (
            f"weak payoff structure: {weak} filler node(s) scoring <= {PAYOFF_WEAK_SCORE} "
            f"(max {PAYOFF_MAX_WEAK_COUNT}) — mid-video sag risk"
        )
    if reason:
        log.warning("video %s rejected — %s", video_id, reason)
        _fail_video(video_id, reason)
        raise ValueError(reason)


def _generate_with_retry(system: str, user: str, research_result: dict, video_id: int) -> ScriptOutput:
    last_error: Exception | None = None
    for attempt in range(MAX_JSON_RETRIES + 1):
        prompt = user if last_error is None else (
            f"{user}\n\nPREVIOUS ATTEMPT WAS INVALID: {last_error}\nReturn corrected JSON only."
        )
        raw = complete(system, prompt, max_tokens=6000, step="script_generate", video_id=video_id, thinking=True)
        try:
            data = parse_json(raw)
            merged = {
                **data,
                "citations": [c.model_dump() for c in research_result["citations"]],
                "sources": research_result["sources"],
                "research_depth": research_result["research_depth"],
            }
            return ScriptOutput(**merged)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            log.warning("script JSON invalid (attempt %d/%d): %s", attempt + 1, MAX_JSON_RETRIES + 1, exc)

    _fail_video(video_id, f"script generation failed validation after retries: {last_error}")
    raise ValueError(f"script generation failed after {MAX_JSON_RETRIES + 1} attempts: {last_error}")


def _get_or_create_video(topic: Topic) -> int:
    """Find-or-create the Video row keyed by a topic-derived idempotency key.

    Keying on the topic (not a random id) means re-running generate() for the same
    topic reuses the same video/output dir instead of creating duplicates on retry.
    """
    idem_key = checkpoint.make_idempotency_key("script", str(topic.id))
    with SessionLocal() as s:
        video = s.scalar(select(Video).where(Video.idempotency_key == idem_key))
        if video is None:
            video = Video(topic_id=topic.id, idempotency_key=idem_key, state=VideoState.DRAFT.value)
            s.add(video)
            s.commit()
            s.refresh(video)
        return video.id


def _load_if_done(video_id: int) -> ScriptOutput | None:
    if not checkpoint.is_done(video_id, CHECKPOINT_STEP):
        return None
    path = OUTPUT_DIR / str(video_id) / "script.json"
    if not path.exists():
        return None  # checkpoint says done but the file is gone — treat as not-done, regenerate
    return ScriptOutput(**json.loads(path.read_text(encoding="utf-8")))


def _persist(video_id: int, script: ScriptOutput) -> None:
    video_dir = OUTPUT_DIR / str(video_id)
    video_dir.mkdir(parents=True, exist_ok=True)
    script_path = video_dir / "script.json"
    txt_path = video_dir / "script.txt"
    script_path.write_text(json.dumps(script.model_dump(), indent=2), encoding="utf-8")
    txt_path.write_text(script.narration, encoding="utf-8")  # narration only — citations stay in .json

    with SessionLocal() as s:
        video = s.get(Video, video_id)
        # Idempotent: a resume/rewrite (checkpoint lost, or crash between commit and
        # checkpoint.write) can re-enter with the row already SCRIPTED. There is no
        # SCRIPTED->SCRIPTED edge, so only assert the transition when actually advancing.
        if video.state != VideoState.SCRIPTED.value:
            assert_transition(video.state, VideoState.SCRIPTED)
            video.state = VideoState.SCRIPTED.value
        # A rework run (rejected -> scripted) starts a fresh attempt: the old rejection
        # note belongs to the previous cut and would show as a phantom error in the panel.
        video.reject_reason = None
        video.script_path = str(script_path)
        # `script` is the in-memory ScriptOutput here (attribute access is valid); every
        # consumer that instead loads script.json off disk sees plain dicts and uses opt["title"].
        video.title = script.title_options[0].title
        video.description = script.description
        video.tags = script.tags
        s.commit()

    checkpoint.write(video_id, CHECKPOINT_STEP, {"script_path": str(script_path), "script_txt_path": str(txt_path)})


def _fail_video(video_id: int, reason: str) -> None:
    with SessionLocal() as s:
        video = s.get(Video, video_id)
        if video is None:
            return
        try:
            assert_transition(video.state, VideoState.FAILED)
        except Exception:
            return  # already in a terminal/non-failable state — don't mask the original error
        video.state = VideoState.FAILED.value
        video.reject_reason = reason
        s.commit()
