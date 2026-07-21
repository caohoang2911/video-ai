"""Key-free unit tests for the thumbnail event-relevance gate and relevance-first hero
selection: the gate drops wrong-subject archives, keeps unscored images, and fails LOUD (an
operator alert, never a silent pass) when no relevance backend is configured; ranking puts
event-relevance first with the aesthetic frame-score only as a tie-break; `others` are gated
only when no archival is relevant (the branch where one could reach the hero); the entity
extractor anchors search/gate/prompt on the leading event entity."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_operator.assembler import thumbnail_generator as tg
from ai_operator.content import llm_client as lc
from ai_operator.media import visual_fetcher as vf


# --------------------------------------------------------------------------------------
# extract_entity -- one anchor for search, gate subject and synthetic prompt
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("The Halifax Explosion: A City Erased", "The Halifax Explosion"),
        ("Pan Am Flight 103 - Lockerbie", "Pan Am Flight 103"),
        ("RMS Titanic — The Unsinkable Ship", "RMS Titanic"),
        ("The Hindenburg Disaster", "The Hindenburg Disaster"),  # no delimiter -> whole title
        ("Chernobyl | Reactor 4", "Chernobyl"),
        ("Marie-Antoinette's Last Days", "Marie-Antoinette's Last Days"),  # hyphen name kept
        ("  The Halifax Explosion:  A City  ", "The Halifax Explosion"),
        ("", ""),
    ],
)
def test_extract_entity(title, expected):
    assert vf.extract_entity(title) == expected


# --------------------------------------------------------------------------------------
# _relevance_gate -- keep on-event, drop off-event, keep unscored, FAIL LOUD when disabled
# --------------------------------------------------------------------------------------


def test_relevance_gate_keeps_above_threshold_drops_below(monkeypatch):
    monkeypatch.setattr(tg.relevance_scorer, "available", lambda: True)
    scores = {"hi.jpg": 0.8, "lo.jpg": 0.2, "edge.jpg": 0.5}  # threshold is 0.5
    monkeypatch.setattr(tg.relevance_scorer, "score", lambda subj, p, video_id=None: scores[p.name])

    kept = tg._relevance_gate([Path("hi.jpg"), Path("lo.jpg"), Path("edge.jpg")], "Titanic", 1)

    assert {p.name for p, _ in kept} == {"hi.jpg", "edge.jpg"}  # 0.5 >= 0.5 kept, 0.2 dropped
    assert {p.name: s for p, s in kept} == {"hi.jpg": 0.8, "edge.jpg": 0.5}  # score rides along


def test_relevance_gate_keeps_unscored_image(monkeypatch):
    monkeypatch.setattr(tg.relevance_scorer, "available", lambda: True)
    monkeypatch.setattr(tg.relevance_scorer, "score", lambda subj, p, video_id=None: None)

    assert tg._relevance_gate([Path("x.jpg")], "Titanic", 1) == [(Path("x.jpg"), None)]


def test_relevance_gate_passthrough_without_subject():
    assert tg._relevance_gate([Path("a.jpg")], "", 1) == [(Path("a.jpg"), None)]


def test_relevance_gate_fails_loud_when_backend_unavailable(monkeypatch):
    monkeypatch.setattr(tg.relevance_scorer, "available", lambda: False)
    import ai_operator.ops.alerting as alerting

    alerts: list[str] = []
    monkeypatch.setattr(alerting, "alert", lambda msg: alerts.append(msg))

    paths = [Path("a.jpg"), Path("b.jpg")]
    kept = tg._relevance_gate(paths, "Titanic", 7)

    assert [p for p, _ in kept] == paths  # every image passes through (never a missing thumb)
    assert all(s is None for _, s in kept)
    assert len(alerts) == 1 and "DISABLED" in alerts[0]  # but the disabled check is NOT silent


def test_relevance_gate_fails_loud_when_backend_returns_no_score(monkeypatch):
    # key present but every score fails (expired / quota'd / outage) — the likeliest silent-off.
    monkeypatch.setattr(tg.relevance_scorer, "available", lambda: True)
    monkeypatch.setattr(tg.relevance_scorer, "score", lambda subj, p, video_id=None: None)
    import ai_operator.ops.alerting as alerting

    alerts: list[str] = []
    monkeypatch.setattr(alerting, "alert", lambda msg: alerts.append(msg))

    kept = tg._relevance_gate([Path("a.jpg"), Path("b.jpg")], "Titanic", 9)

    assert [p for p, _ in kept] == [Path("a.jpg"), Path("b.jpg")]  # all kept (best-effort)
    assert len(alerts) == 1 and "0/2" in alerts[0]  # broken backend is NOT silent


def test_relevance_gate_fails_loud_when_half_the_pool_goes_unjudged(monkeypatch):
    # A per-minute request quota lets the first images through and rejects the rest: some
    # scores come back, so "did anything score?" looks healthy while most images pass ungated.
    monkeypatch.setattr(tg.relevance_scorer, "available", lambda: True)
    scores = {"a.jpg": 0.9, "b.jpg": 0.9, "c.jpg": None, "d.jpg": None}
    monkeypatch.setattr(tg.relevance_scorer, "score", lambda subj, p, video_id=None: scores[p.name])
    import ai_operator.ops.alerting as alerting

    alerts: list[str] = []
    monkeypatch.setattr(alerting, "alert", lambda msg: alerts.append(msg))

    tg._relevance_gate([Path(n) for n in scores], "Titanic", 9)

    assert len(alerts) == 1 and "2/4" in alerts[0]


def test_relevance_gate_tolerates_a_single_unreadable_image(monkeypatch):
    # One bad file among many is noise, not a disabled gate — it must not cry wolf.
    monkeypatch.setattr(tg.relevance_scorer, "available", lambda: True)
    scores = {"a.jpg": 0.9, "b.jpg": 0.9, "c.jpg": 0.9, "bad.jpg": None}
    monkeypatch.setattr(tg.relevance_scorer, "score", lambda subj, p, video_id=None: scores[p.name])
    import ai_operator.ops.alerting as alerting

    alerts: list[str] = []
    monkeypatch.setattr(alerting, "alert", lambda msg: alerts.append(msg))

    tg._relevance_gate([Path(n) for n in scores], "Titanic", 9)

    assert alerts == []


def test_relevance_gate_no_false_alarm_for_unscorable_others(monkeypatch):
    # expect_scores=False (the video-heavy `others` pool): all-None is normal (clips can't be
    # image-scored) and must NOT raise the broken-backend alert.
    monkeypatch.setattr(tg.relevance_scorer, "available", lambda: True)
    monkeypatch.setattr(tg.relevance_scorer, "score", lambda subj, p, video_id=None: None)
    import ai_operator.ops.alerting as alerting

    alerts: list[str] = []
    monkeypatch.setattr(alerting, "alert", lambda msg: alerts.append(msg))

    kept = tg._relevance_gate([Path("clip.mp4")], "Titanic", 9, expect_scores=False)

    assert kept == [(Path("clip.mp4"), None)]
    assert alerts == []


# --------------------------------------------------------------------------------------
# _rank_relevance_first -- relevance first, aesthetic frame-score as the tie-break only
# --------------------------------------------------------------------------------------


def test_rank_relevance_first(monkeypatch):
    # Within a relevance band the aesthetic order + near-duplicate dedup is delegated to
    # thumbnail_frame_score.rank; stub it to reverse each band's input so the grouping and the
    # highest-band-first ordering are observable without reading real image files.
    monkeypatch.setattr(tg.thumbnail_frame_score, "rank", lambda paths, n: list(reversed(paths)))

    # A,B in one high band (0.80/0.82 -> band 16); C in a lower band (0.55 -> band 11)
    r = tg._rank_relevance_first([(Path("A.jpg"), 0.80), (Path("B.jpg"), 0.82), (Path("C.jpg"), 0.55)])
    assert [p.name for p in r] == ["B.jpg", "A.jpg", "C.jpg"]  # high band (reversed) then low band

    # fail-open (all None) -> single band 0 -> one delegated rank() over all
    r = tg._rank_relevance_first([(Path("A.jpg"), None), (Path("B.jpg"), None)])
    assert [p.name for p in r] == ["B.jpg", "A.jpg"]

    # a measured-relevant band outranks the unscored (None) band regardless of aesthetics
    r = tg._rank_relevance_first([(Path("A.jpg"), 0.70), (Path("B.jpg"), None)])
    assert [p.name for p in r] == ["A.jpg", "B.jpg"]


# --------------------------------------------------------------------------------------
# _gated_pools -- gate `others` ONLY when no archival is relevant (keeps calls off hot path)
# --------------------------------------------------------------------------------------


def test_gated_pools_gates_others_only_when_archival_empty(monkeypatch):
    monkeypatch.setattr(tg, "_subject_text", lambda vid: "Titanic")
    monkeypatch.setattr(tg, "_period_photos", lambda vid: set())  # licence lookup needs no DB here
    monkeypatch.setattr(tg, "_rank_relevance_first", lambda scored, period=None: [p for p, _ in scored])

    gate_calls: list[list[str]] = []

    def fake_gate(paths, subject, video_id, expect_scores=True):
        gate_calls.append([p.name for p in paths])
        return [(p, 0.9) for p in paths]

    monkeypatch.setattr(tg, "_relevance_gate", fake_gate)

    rank_calls: list[list[str]] = []

    def fake_rank(paths, n):
        rank_calls.append([p.name for p in paths])
        return paths

    monkeypatch.setattr(tg.thumbnail_frame_score, "rank", fake_rank)

    # archival present -> others are frame-scored, NOT relevance-gated
    monkeypatch.setattr(tg, "_caption_free_sources", lambda vid: ([Path("arch.jpg")], [Path("oth.jpg")]))
    gate_calls.clear()
    rank_calls.clear()
    _, _, subj = tg._gated_pools(1)
    assert gate_calls == [["arch.jpg"]]
    assert rank_calls == [["oth.jpg"]]
    assert subj == "Titanic"

    # no relevant archival -> `others` must clear the gate too (could reach the hero)
    monkeypatch.setattr(tg, "_caption_free_sources", lambda vid: ([], [Path("oth.jpg")]))
    gate_calls.clear()
    rank_calls.clear()
    tg._gated_pools(2)
    assert gate_calls == [[], ["oth.jpg"]]  # archival (empty) then others gated
    assert rank_calls == [["oth.jpg"]]  # frame-score only PRE-selects; nothing skips the gate


def test_gated_pools_bounds_how_many_others_reach_the_gate(monkeypatch):
    # The `others` pool runs to dozens of stock frames and the gate spends one vision call per
    # image, so gating it whole outruns the request quota to judge frames that could never win
    # a variant slot. Frame-score picks the shortlist; the gate still judges every survivor.
    monkeypatch.setattr(tg, "_subject_text", lambda vid: "Titanic")
    monkeypatch.setattr(tg, "_period_photos", lambda vid: set())  # licence lookup needs no DB here
    monkeypatch.setattr(tg, "_caption_free_sources",
                        lambda vid: ([], [Path(f"o{i}.jpg") for i in range(40)]))
    monkeypatch.setattr(tg, "_rank_relevance_first", lambda scored, period=None: [p for p, _ in scored])

    gated: list[int] = []

    def fake_gate(paths, subject, video_id, expect_scores=True):
        gated.append(len(paths))
        return [(p, 0.9) for p in paths]

    monkeypatch.setattr(tg, "_relevance_gate", fake_gate)

    tg._gated_pools(3)

    assert gated[-1] <= tg.N_VARIANTS * 2


# --------------------------------------------------------------------------------------
# llm_client._parse_unit_score -- defensive parse of the vision score
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("0.73 relevant", 0.73),
        ("1", 1.0),
        ("0.0", 0.0),
        ("2.5", 1.0),  # clamp above 1
        ("Score: .85", 0.85),
        ("no number", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_unit_score(text, expected):
    assert lc._parse_unit_score(text) == expected


# --------------------------------------------------------------------------------------
# period-photo tie-break -- aesthetic punch is the wrong judge of a HERO
# --------------------------------------------------------------------------------------


def test_period_photograph_wins_a_relevance_tie(monkeypatch):
    """Asked whether they show the dam failure, the 1928 photo of the broken dam and a 2012
    snapshot of the empty site both score 1.0. Frame-score handed the slot to the colour photo
    -- more punch, none of the thing a viewer must recognise."""
    modern, era = Path("2012_site.jpg"), Path("1928_ruin.jpg")
    monkeypatch.setattr(tg.thumbnail_frame_score, "usable", lambda p: True)
    # frame-score prefers the modern colour frame; the tie-break must overrule it
    monkeypatch.setattr(tg.thumbnail_frame_score, "rank", lambda paths, n: [modern, era])

    assert tg._rank_relevance_first([(modern, 1.0), (era, 1.0)], {era})[0] == era


def test_period_preference_never_outranks_relevance(monkeypatch):
    """A period photo of the wrong thing must not climb over a modern photo of the right one."""
    era_offevent, modern_onevent = Path("old.jpg"), Path("new.jpg")
    monkeypatch.setattr(tg.thumbnail_frame_score, "usable", lambda p: True)
    monkeypatch.setattr(tg.thumbnail_frame_score, "rank", lambda paths, n: list(paths))

    ranked = tg._rank_relevance_first([(era_offevent, 0.5), (modern_onevent, 1.0)], {era_offevent})

    assert ranked[0] == modern_onevent  # different bands -> relevance still decides


def test_recent_event_with_no_period_photos_keeps_frame_score_order(monkeypatch):
    a, b = Path("a.jpg"), Path("b.jpg")
    monkeypatch.setattr(tg.thumbnail_frame_score, "usable", lambda p: True)
    monkeypatch.setattr(tg.thumbnail_frame_score, "rank", lambda paths, n: [a, b])

    assert tg._rank_relevance_first([(a, 1.0), (b, 1.0)], set()) == [a, b]


@pytest.mark.parametrize("licence,expected", [
    ("Public domain | Stearns, H.T. USGS | https://c/1", True),
    ("PD-US | Lib of Congress | https://c/2", True),
    ("CC BY-SA 2.0 | Konrad Summers | https://c/3", False),
    ("CC BY 4.0 | Jane Doe | https://c/4", False),
    (None, False),
])
def test_public_domain_licence_detection(licence, expected):
    assert tg._is_public_domain(licence) is expected
