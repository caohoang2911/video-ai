"""P0 go/no-go harness: aggregate the validation window's analytics and emit an advisory
PASS_P0 / KILL_P0 / INSUFFICIENT_DATA decision so the channel doesn't drift on sunk cost.

Pure read over `uploads` + `analytics`. Thresholds live in ONE tunable block below (revisit
with real channel data). KILL_P0 must be clearly *earned* — killing a channel is an
irreversible business call — so an ambiguous-but-not-failing window classifies PASS_P0
(= "no kill signal; continue") with the unmet pass criteria spelled out in the rationale,
never a silent auto-kill. Policy strike count has no public API: read from `app_state`
(key `policy_strikes`, manual), default 0. The report is advisory; the human decides.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from ..db.engine import SessionLocal
from ..db.models import Upload
from ..db.models_ops import Analytics, AppState

# --- Thresholds (single tunable block) ---------------------------------------------------
MIN_WINDOW = 10            # need at least this many *measured* videos to decide at all
PASS_RETENTION_PCT = 30.0  # avg retention >= this for a strong pass
PASS_CTR_PCT = 4.0         # avg CTR% >= this for a strong pass
BREAKOUT_VIEWS = 5_000     # need >=1 video above this ("some videos break out")
KILL_AVG_VIEWS = 2_000     # flat/low views ceiling for a kill signal
KILL_RETENTION_PCT = 30.0  # retention below this + flat views + no trend => kill

STRIKES_KEY = "policy_strikes"

PASS = "PASS_P0"
KILL = "KILL_P0"
INSUFFICIENT = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class ValidationResult:
    window: int
    filled: int
    avg_views: float
    avg_retention_pct: float
    avg_ctr_pct: float
    breakout_count: int
    upward_trend: bool
    strikes: int
    decision: str
    strong_pass: bool
    rationale: str


def _strikes() -> int:
    with SessionLocal() as s:
        row = s.get(AppState, STRIKES_KEY)
    try:
        return int(row.value) if row and row.value else 0
    except (TypeError, ValueError):
        return 0


def _window_rows(window: int) -> list[dict]:
    """Latest analytics snapshot per published video, newest publish first, capped to window.
    Videos published but with no analytics row yet are skipped (they don't count as measured)."""
    with SessionLocal() as s:
        uploads = s.execute(
            select(Upload.youtube_video_id, Upload.created_at)
            .where(Upload.youtube_video_id.is_not(None))
            .order_by(Upload.created_at.desc())
            .limit(window)
        ).all()
        rows: list[dict] = []
        for yt_id, created in uploads:
            a = s.scalar(
                select(Analytics)
                .where(Analytics.youtube_video_id == yt_id)
                .order_by(Analytics.as_of_date.desc())
            )
            if a is not None:
                rows.append({"created": created, "views": a.views,
                             "retention": a.avg_view_pct, "ctr": a.ctr})
    return rows


def _is_upward(rows_new_first: list[dict]) -> bool:
    """True if the later half of the window out-views the earlier half (chronological).

    Caveat: `views` is a cumulative-to-date snapshot, so newer uploads have had fewer days to
    accumulate and the later half is age-biased LOW -> this can read a rising channel as flat
    and (since `not upward` is a KILL and-condition) nudge toward an easier kill. A true trend
    needs per-video age-normalized view rate, which the analytics puller does not collect yet.
    The two other KILL conditions (flat sub-2k views AND sub-30% retention) still gate it."""
    chrono = list(reversed(rows_new_first))  # oldest -> newest
    if len(chrono) < 2:
        return False
    mid = len(chrono) // 2
    early = chrono[:mid]
    late = chrono[mid:]
    early_avg = sum(r["views"] for r in early) / len(early)
    late_avg = sum(r["views"] for r in late) / len(late)
    return late_avg > early_avg


def evaluate(window: int = 20) -> ValidationResult:
    rows = _window_rows(window)
    filled = len(rows)
    strikes = _strikes()

    if filled < MIN_WINDOW:
        return ValidationResult(
            window=window, filled=filled, avg_views=0.0, avg_retention_pct=0.0,
            avg_ctr_pct=0.0, breakout_count=0, upward_trend=False, strikes=strikes,
            decision=INSUFFICIENT, strong_pass=False,
            rationale=f"only {filled}/{MIN_WINDOW} measured videos — window not full",
        )

    avg_views = sum(r["views"] for r in rows) / filled
    avg_ret = sum(r["retention"] for r in rows) / filled
    avg_ctr = sum(r["ctr"] for r in rows) / filled
    ctr_measured = any(r["ctr"] > 0 for r in rows)  # all-zero = CTR not measured (fresh/low-reach)
    breakouts = sum(1 for r in rows if r["views"] >= BREAKOUT_VIEWS)
    upward = _is_upward(rows)

    kill_signal = avg_views < KILL_AVG_VIEWS and avg_ret < KILL_RETENTION_PCT and not upward
    unmet = _unmet_pass_criteria(avg_ret, avg_ctr, breakouts, strikes, ctr_measured)
    strong_pass = not unmet

    if kill_signal:
        decision, rationale = KILL, (
            f"KILL: avg_views {avg_views:.0f} < {KILL_AVG_VIEWS}, "
            f"retention {avg_ret:.1f}% < {KILL_RETENTION_PCT}%, no upward trend"
        )
    else:
        decision = PASS
        rationale = "strong pass: all P0 targets met" if strong_pass else (
            "continue (no kill signal) but below target — " + "; ".join(unmet)
        )

    return ValidationResult(
        window=window, filled=filled, avg_views=round(avg_views, 1),
        avg_retention_pct=round(avg_ret, 1), avg_ctr_pct=round(avg_ctr, 2),
        breakout_count=breakouts, upward_trend=upward, strikes=strikes,
        decision=decision, strong_pass=strong_pass, rationale=rationale,
    )


def _unmet_pass_criteria(
    avg_ret: float, avg_ctr: float, breakouts: int, strikes: int, ctr_measured: bool
) -> list[str]:
    unmet = []
    if avg_ret < PASS_RETENTION_PCT:
        unmet.append(f"retention {avg_ret:.1f}% < {PASS_RETENTION_PCT}%")
    # CTR is only gated when actually measured: a fresh / low-reach video has no impressions
    # data yet, so an all-zero CTR means "unmeasured", not a real 0%. Gating on it regardless
    # would sink a strong pass on nothing but missing data.
    if ctr_measured and avg_ctr < PASS_CTR_PCT:
        unmet.append(f"ctr {avg_ctr:.2f}% < {PASS_CTR_PCT}%")
    if breakouts < 1:
        unmet.append(f"no video >= {BREAKOUT_VIEWS} views")
    if strikes > 0:
        unmet.append(f"{strikes} policy strike(s)")
    return unmet


def render(r: ValidationResult) -> str:
    return "\n".join([
        f"validation report — window={r.window} measured={r.filled}",
        "-" * 60,
        f"avg views     : {r.avg_views}",
        f"avg retention : {r.avg_retention_pct}%",
        f"avg ctr       : {r.avg_ctr_pct}%",
        f"breakouts     : {r.breakout_count} (>= {BREAKOUT_VIEWS} views)",
        f"upward trend  : {r.upward_trend}",
        f"strikes       : {r.strikes}",
        "-" * 60,
        f"DECISION      : {r.decision}",
        f"rationale     : {r.rationale}",
    ])
