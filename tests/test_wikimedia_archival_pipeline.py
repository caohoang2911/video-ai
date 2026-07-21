"""Key-free tests for the Wikimedia Commons archival tier: client license/size filtering,
tier order in visual_fetcher (archival outranks stock photo, falls through when empty),
per-file license persistence, the render-time grade wiring, and the description credit
block. Mocked HTTP; no network, no API keys."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ai_operator.assembler import kenburns_ffmpeg, segment_builder
from ai_operator.db.base import Base
from ai_operator.db.models import Asset
from ai_operator.media import asset_store, stock_clients, visual_fetcher
from ai_operator.publisher import metadata_builder

# the publisher package re-exports the publish() FUNCTION under the module's name;
# import_module returns the real submodule (same trick conftest uses for db.engine)
publish_module = importlib.import_module("ai_operator.publisher.publish")


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------

def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _commons_page(idx: int, *, license_name: str, width: int = 1600, ext: str = "jpg",
                  artist: str = "<a href='#'>Jane Doe</a>") -> dict:
    name = f"File{idx}.{ext}"
    return {
        "index": idx,
        "imageinfo": [{
            "url": f"https://upload.wikimedia.org/orig/{name}",
            "thumburl": f"https://upload.wikimedia.org/thumb/{name}/1920px-{name}",
            "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{name}",
            "width": width, "height": 1200,
            "extmetadata": {
                "LicenseShortName": {"value": license_name},
                "Artist": {"value": artist},
            },
        }],
    }


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


# --------------------------------------------------------------------------------------
# Phase 1: Commons client — license / size / format gates
# --------------------------------------------------------------------------------------

def test_commons_license_gate_accepts_free_rejects_restricted():
    ok = ["Public domain", "PD-US", "CC0", "CC BY 4.0", "CC BY-SA 3.0", "cc-by-2.0"]
    bad = ["Fair use", "GFDL", "All rights reserved", ""]
    assert all(stock_clients._commons_license_ok(s) for s in ok)
    assert not any(stock_clients._commons_license_ok(s) for s in bad)


def test_commons_search_filters_and_orders_candidates(monkeypatch):
    payload = {"query": {"pages": {
        "b": _commons_page(2, license_name="CC BY 4.0"),
        "a": _commons_page(1, license_name="Public domain"),
        "fair": _commons_page(3, license_name="Fair use"),          # rejected: license
        "tiny": _commons_page(4, license_name="CC0", width=500),    # rejected: below min width
        "svg": _commons_page(5, license_name="CC0", ext="svg"),     # rejected: not a photo format
    }}}
    fake = SimpleNamespace(get=lambda *a, **k: _FakeResp(payload))
    monkeypatch.setattr(stock_clients, "_commons_client", lambda: fake)

    out = stock_clients.search_wikimedia_commons("lusitania 1915")
    assert [c["license"] for c in out] == ["Public domain", "CC BY 4.0"]  # relevance order kept
    assert out[0]["source"] == "wikimedia"
    assert out[0]["artist"] == "Jane Doe"                    # HTML stripped
    assert "/480px-" in out[0]["thumb"]                      # small CLIP preview derived
    assert out[0]["file_page"].startswith("https://commons.wikimedia.org/wiki/")


def test_commons_search_returns_empty_on_http_failure(monkeypatch):
    def _boom(*a, **k):
        raise ConnectionError("offline")
    monkeypatch.setattr(stock_clients, "_commons_client", lambda: SimpleNamespace(get=_boom))
    assert stock_clients.search_wikimedia_commons("anything") == []


def test_disabled_visual_sources_kill_switch(monkeypatch):
    """DISABLED_VISUAL_SOURCES locks a provider out without touching its API key; other
    sources keep working. No HTTP may be attempted for a disabled source."""
    monkeypatch.setattr(stock_clients.settings, "DISABLED_VISUAL_SOURCES", "pixabay, pexels")
    monkeypatch.setattr(stock_clients.settings, "PIXABAY_API_KEY", "k")
    monkeypatch.setattr(stock_clients.settings, "PEXELS_API_KEY", "k")

    def _no_http():
        raise AssertionError("disabled source must not open a session")
    monkeypatch.setattr(stock_clients, "_pixabay_client", _no_http)
    monkeypatch.setattr(stock_clients, "_pexels_client", _no_http)

    assert stock_clients.search_pixabay("ship") == []
    assert stock_clients.search_pixabay_video("ship") == []
    assert stock_clients.search_pexels("ship") == []
    assert stock_clients.search_pexels_video("ship") == []

    # wikimedia NOT in the disabled list -> still queried
    payload = {"query": {"pages": {"a": _commons_page(1, license_name="Public domain")}}}
    monkeypatch.setattr(
        stock_clients, "_commons_client", lambda: SimpleNamespace(get=lambda *a, **k: _FakeResp(payload))
    )
    assert len(stock_clients.search_wikimedia_commons("lusitania")) == 1


# --------------------------------------------------------------------------------------
# Phase 1: tier order — archival hit skips stock photo; archival miss falls through
# --------------------------------------------------------------------------------------

def _acquire_one_beat(monkeypatch, *, archival_hit: bool):
    """Run acquire() over one non-diagram beat (stills_only) with tier fns stubbed."""
    calls = {"archival_saved": 0, "stock": 0}
    monkeypatch.setattr(
        visual_fetcher, "checkpoint",
        SimpleNamespace(is_done=lambda *a: False, write=lambda *a, **k: None),
    )
    monkeypatch.setattr(visual_fetcher, "_archival_anchor", lambda *a: "Test Event")
    monkeypatch.setattr(visual_fetcher, "_estimate_beat_seconds", lambda *a: [0.0])
    cand = {"url": "u", "license": "CC BY 4.0", "artist": "A", "file_page": "p"}
    monkeypatch.setattr(visual_fetcher, "_fetch_archival", lambda *a, **k: cand if archival_hit else None)

    def _fake_stock(*a, **k):
        calls["stock"] += 1
        return ("http://stock/img.jpg", "pexels")
    monkeypatch.setattr(visual_fetcher, "_fetch_stock", _fake_stock)

    def _fake_save_archival(video_id, beat_id, url, **kw):
        calls["archival_saved"] += 1
        return {"kind": "archival", "path": "x"}
    monkeypatch.setattr(
        visual_fetcher, "asset_store",
        SimpleNamespace(
            save_archival=_fake_save_archival,
            save_stock=lambda *a, **k: {"kind": "stock", "path": "y"},
            list_assets=lambda *a: [],
        ),
    )
    shot_list = [{"beat_id": 1, "keywords": ["lusitania", "ship"], "mood": "somber"}]
    saved = visual_fetcher.acquire(101, shot_list, stills_only=True)
    return saved, calls


def test_archival_hit_wins_and_stock_photo_is_never_queried(monkeypatch):
    saved, calls = _acquire_one_beat(monkeypatch, archival_hit=True)
    assert calls == {"archival_saved": 1, "stock": 0}
    assert saved[0]["kind"] == "archival"


def test_archival_miss_falls_through_to_stock_photo(monkeypatch):
    saved, calls = _acquire_one_beat(monkeypatch, archival_hit=False)
    assert calls["stock"] == 1
    assert saved[0]["kind"] == "stock"


def test_illustration_beat_tries_archival_before_generating(monkeypatch):
    """Era-scene beats (visual_kind=illustration) are archival's home turf: a real period
    photograph must win over a painted SDXL scene when Commons has one."""
    monkeypatch.setattr(
        visual_fetcher, "checkpoint",
        SimpleNamespace(is_done=lambda *a: False, write=lambda *a, **k: None),
    )
    monkeypatch.setattr(visual_fetcher, "_archival_anchor", lambda *a: "Test Event")
    monkeypatch.setattr(visual_fetcher, "_estimate_beat_seconds", lambda *a: [0.0])
    cand = {"url": "u", "license": "Public domain", "artist": "A", "file_page": "p"}
    monkeypatch.setattr(visual_fetcher, "_fetch_archival", lambda *a, **k: cand)
    generated = []
    monkeypatch.setattr(visual_fetcher, "_generate_visual",
                        lambda *a, **k: generated.append(1) or None)
    monkeypatch.setattr(
        visual_fetcher, "asset_store",
        SimpleNamespace(save_archival=lambda *a, **k: {"kind": "archival"}, list_assets=lambda *a: []),
    )
    shot = [{"beat_id": 1, "keywords": ["burning ship"], "mood": "somber", "visual_kind": "illustration"}]
    saved = visual_fetcher.acquire(102, shot, stills_only=True)
    assert saved[0]["kind"] == "archival"
    assert generated == []  # không đốt SDXL khi đã có ảnh thật


def test_fetch_archival_skips_urls_already_used_by_earlier_beats(monkeypatch):
    """Anchor-retry hands every beat the SAME candidate pool — the used-set must steer
    later beats to the next-ranked photo instead of the md5-dup -> SDXL fallback."""
    cands = [
        {"url": "u1", "thumb": "t1", "source": "wikimedia", "license": "PD", "artist": "", "file_page": ""},
        {"url": "u2", "thumb": "t2", "source": "wikimedia", "license": "PD", "artist": "", "file_page": ""},
    ]
    monkeypatch.setattr(visual_fetcher.stock_clients, "search_wikimedia_commons", lambda q: list(cands))
    monkeypatch.setattr(visual_fetcher, "_rank_candidates", lambda text, c: list(c))
    # the beat-match floor has its own tests; here every candidate is on-beat
    monkeypatch.setattr(visual_fetcher, "_first_beat_relevant",
                        lambda ranked, text, video_id: ranked[0] if ranked else None)

    first = visual_fetcher._fetch_archival(["kw"], "t", "Event", set())
    assert first["url"] == "u1"
    second = visual_fetcher._fetch_archival(["kw"], "t", "Event", {"u1"})
    assert second["url"] == "u2"                     # ảnh kế tiếp, không đụng hàng
    assert visual_fetcher._fetch_archival(["kw"], "t", "Event", {"u1", "u2"}) is None


def test_map_beat_skips_archival_and_generates(monkeypatch):
    """True map/diagram beats stay generation-first — SDXL draws a clean period map,
    archival search for 'route map' would return noise."""
    monkeypatch.setattr(
        visual_fetcher, "checkpoint",
        SimpleNamespace(is_done=lambda *a: False, write=lambda *a, **k: None),
    )
    monkeypatch.setattr(visual_fetcher, "_archival_anchor", lambda *a: "Test Event")
    monkeypatch.setattr(visual_fetcher, "_estimate_beat_seconds", lambda *a: [0.0])
    fetched = []
    monkeypatch.setattr(visual_fetcher, "_fetch_archival",
                        lambda *a, **k: fetched.append(1) or None)
    monkeypatch.setattr(visual_fetcher, "_generate_visual",
                        lambda *a, **k: (Path("/tmp/x.png"), "sdxl"))
    monkeypatch.setattr(
        visual_fetcher, "asset_store",
        SimpleNamespace(
            save_generated=lambda *a, **k: {"kind": "gen"},
            grade_batch_coherence=lambda paths: (1.0, []),
            list_assets=lambda *a: [],
        ),
    )
    shot = [{"beat_id": 1, "keywords": ["harbor channel map"], "mood": "informative"}]
    saved = visual_fetcher.acquire(103, shot, stills_only=True)
    assert fetched == []          # beat bản đồ không dò Commons
    assert saved[0]["kind"] == "gen"


# --------------------------------------------------------------------------------------
# Phase 1: save_archival persists the per-file license triple
# --------------------------------------------------------------------------------------

def test_save_archival_writes_per_file_license_triple(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    monkeypatch.setattr(asset_store, "SessionLocal", Session)
    monkeypatch.setattr(asset_store, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(
        asset_store, "requests",
        SimpleNamespace(get=lambda *a, **k: SimpleNamespace(
            content=b"jpegbytes", raise_for_status=lambda: None)),
    )
    rec = asset_store.save_archival(
        7, 3, "https://upload.wikimedia.org/x.jpg",
        license_short="CC BY 4.0", artist="Jane Doe",
        file_page="https://commons.wikimedia.org/wiki/File:x.jpg",
    )
    assert rec is not None and rec["kind"] == "archival" and rec["source"] == "wikimedia"
    with Session() as s:
        row = s.execute(select(Asset)).scalars().one()
        assert row.license == "CC BY 4.0 | Jane Doe | https://commons.wikimedia.org/wiki/File:x.jpg"
    assert (tmp_path / "out" / "7" / "img" / "beat_03.jpg").read_bytes() == b"jpegbytes"


# --------------------------------------------------------------------------------------
# Phase 2: render-time grade only for archival beats
# --------------------------------------------------------------------------------------

def test_kenburns_extra_vf_is_appended_to_filter_chain(tmp_path, monkeypatch):
    captured = {}

    def _fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(kenburns_ffmpeg.subprocess, "run", _fake_run)
    img = tmp_path / "beat_01.jpg"
    img.write_bytes(b"x")

    kenburns_ffmpeg.render_segment(img, 2.0, tmp_path / "seg.mp4",
                                   extra_vf=kenburns_ffmpeg.ARCHIVAL_GRADE_VF)
    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    assert vf.endswith(kenburns_ffmpeg.ARCHIVAL_GRADE_VF)

    kenburns_ffmpeg.render_segment(img, 2.0, tmp_path / "seg2.mp4")
    vf_plain = captured["cmd"][captured["cmd"].index("-vf") + 1]
    assert kenburns_ffmpeg.ARCHIVAL_GRADE_VF not in vf_plain


def test_segment_builder_grades_only_archival_beats(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    monkeypatch.setattr(segment_builder, "SessionLocal", Session)
    img_dir = tmp_path / "img"
    img_dir.mkdir()
    with Session() as s:
        s.add(Asset(video_id=9, kind="archival", source="wikimedia",
                    url_or_path=str(img_dir / "beat_01.jpg"),
                    license="Public domain | x | y", md5="m1"))
        s.commit()

    seen = {}

    def _fake_render(image_path, duration, out, motion="zoom_in", extra_vf=None, **kw):
        seen[Path(image_path).name] = extra_vf
        return out
    monkeypatch.setattr(segment_builder.kenburns_ffmpeg, "render_segment", _fake_render)

    shot_list = [{"beat_id": 1}, {"beat_id": 2}]
    segment_builder.build_segments(shot_list, [2.0, 2.0], 9, img_dir, tmp_path / "seg")
    assert seen["beat_01.jpg"] == kenburns_ffmpeg.ARCHIVAL_GRADE_VF  # archival -> graded
    assert seen["beat_02.jpg"] is None                               # generated/stock -> untouched


# --------------------------------------------------------------------------------------
# Thumbnail: archival photos lead the variant sources
# --------------------------------------------------------------------------------------

def _add_asset(session, video_id, kind, path):
    session.add(Asset(video_id=video_id, kind=kind, source="x", url_or_path=str(path),
                      license="L", md5=str(path)))


def test_thumbnail_sources_archival_first_then_others(tmp_path, monkeypatch):
    from ai_operator.assembler import thumbnail_generator as tg
    Session = _session_factory(tmp_path)
    monkeypatch.setattr(tg, "SessionLocal", Session)
    arch = tmp_path / "beat_02.jpg"; arch.write_bytes(b"a")
    gen1 = tmp_path / "beat_01.jpg"; gen1.write_bytes(b"g")
    gen2 = tmp_path / "beat_03.jpg"; gen2.write_bytes(b"g")
    with Session() as s:
        _add_asset(s, 4, "archival", arch)
        _add_asset(s, 4, "gen", gen1)
        _add_asset(s, 4, "gen", gen2)
        s.commit()
    picked = tg._thumbnail_sources(4)
    assert picked[0] == arch                       # variant a = ảnh tư liệu thật
    assert set(picked[1:]) == {gen1, gen2}         # slot còn lại lấp bằng nguồn khác


def test_thumbnail_sources_all_archival_when_plenty(tmp_path, monkeypatch):
    from ai_operator.assembler import thumbnail_generator as tg
    Session = _session_factory(tmp_path)
    monkeypatch.setattr(tg, "SessionLocal", Session)
    paths = []
    with Session() as s:
        for i in range(4):
            p = tmp_path / f"beat_{i:02d}.jpg"; p.write_bytes(b"a")
            _add_asset(s, 5, "archival", p)
            paths.append(p)
        _add_asset(s, 5, "gen", tmp_path / "missing.jpg")  # file không tồn tại -> loại
        s.commit()
    picked = tg._thumbnail_sources(5)
    assert len(picked) == 3 and all(p in paths for p in picked)


def test_thumbnail_sources_unchanged_without_archival(tmp_path, monkeypatch):
    from ai_operator.assembler import thumbnail_generator as tg
    Session = _session_factory(tmp_path)
    monkeypatch.setattr(tg, "SessionLocal", Session)
    g = tmp_path / "beat_01.jpg"; g.write_bytes(b"g")
    with Session() as s:
        _add_asset(s, 6, "stock", g)
        s.commit()
    assert tg._thumbnail_sources(6) == [g]


# --------------------------------------------------------------------------------------
# Phase 3: description credit block
# --------------------------------------------------------------------------------------

def test_build_description_renders_archival_credit_block():
    script = {"description": "hook", "image_credits": [
        "Jane Doe — CC BY 4.0 — https://commons.wikimedia.org/wiki/File:x.jpg",
        "Public-domain photographs via Wikimedia Commons",
    ]}
    desc = metadata_builder.build_description(script)
    assert "Archival images:" in desc
    assert "- Jane Doe — CC BY 4.0 — https://commons.wikimedia.org/wiki/File:x.jpg" in desc


def test_build_description_without_credits_has_no_empty_block():
    desc = metadata_builder.build_description({"description": "hook"})
    assert "Archival images:" not in desc


def test_image_credits_cc_by_lines_plus_single_pd_provenance(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path)
    monkeypatch.setattr(publish_module, "SessionLocal", Session)
    with Session() as s:
        s.add_all([
            Asset(video_id=5, kind="archival", source="wikimedia", url_or_path="a.jpg",
                  license="CC BY 4.0 | Jane Doe | https://c/1", md5="a"),
            Asset(video_id=5, kind="archival", source="wikimedia", url_or_path="b.jpg",
                  license="Public domain | unknown author | https://c/2", md5="b"),
            Asset(video_id=5, kind="archival", source="wikimedia", url_or_path="c.jpg",
                  license="PD-US | Lib of Congress | https://c/3", md5="c"),
            Asset(video_id=5, kind="gen", source="sdxl", url_or_path="d.jpg",
                  license="AI-generated", md5="d"),           # non-archival: ignored
            Asset(video_id=6, kind="archival", source="wikimedia", url_or_path="e.jpg",
                  license="CC BY 2.0 | Other | https://c/4", md5="e"),  # other video: ignored
        ])
        s.commit()
    credits = publish_module._image_credits(5)
    assert credits == [
        "Jane Doe — CC BY 4.0 — https://c/1",
        "Public-domain photographs via Wikimedia Commons",   # 2 PD files -> one line
    ]


# --------------------------------------------------------------------------------------
# _first_beat_relevant -- the floor that lets an off-beat pool fall through to the tiers below
# --------------------------------------------------------------------------------------


@pytest.fixture
def beat_match(monkeypatch, tmp_path):
    """Stub the thumb download + the vision judgment; return the recorded scoring order."""

    def _install(scores: dict[str, float | None]):
        thumb = tmp_path / "t.jpg"
        thumb.write_bytes(b"jpeg")
        monkeypatch.setattr(visual_fetcher, "_download_thumb", lambda url, dest: thumb if url else None)

        def _score(narration, image_bytes, video_id=None):
            judged.append(order.pop(0))
            return scores[judged[-1]]

        order = list(scores)
        from ai_operator.content import llm_client

        monkeypatch.setattr(llm_client, "score_scene_match", _score)

    judged: list[str] = []
    _install.judged = judged
    return _install


def _cand(url):
    return {"url": url, "thumb": f"th-{url}", "license": "PD", "artist": "", "file_page": ""}


def test_off_beat_pool_falls_through_instead_of_illustrating_the_wrong_thing(beat_match):
    # Commons is full of museum catalogue photography: a rusted hull fragment in a display case
    # belongs to the event and shows nothing of a line about a judicial inquiry. Better to hand
    # the beat to generation, whose prompt is written from the narration, than to show it.
    beat_match({"u1": 0.0, "u2": 0.0})

    assert visual_fetcher._first_beat_relevant([_cand("u1"), _cand("u2")], "a judicial inquiry opened", 1) is None


def test_second_candidate_saves_the_beat_when_the_top_one_is_off(beat_match):
    beat_match({"u1": 0.0, "u2": 1.0})

    best = visual_fetcher._first_beat_relevant([_cand("u1"), _cand("u2")], "the ship detonated", 1)

    assert best["url"] == "u2"


def test_only_the_top_candidates_are_judged(beat_match):
    # One vision call per candidate: a photo the ranker buried is not going to be the save.
    beat_match({"u1": 0.0, "u2": 0.0, "u3": 1.0})

    best = visual_fetcher._first_beat_relevant([_cand(u) for u in ("u1", "u2", "u3")], "text", 1)

    assert best is None
    assert len(beat_match.judged) == visual_fetcher._BEAT_MATCH_MAX_JUDGED


def test_unjudgeable_beat_keeps_the_top_candidate(beat_match):
    # No key / quota / outage must not starve the render of real photographs — degrade to the
    # old take-the-top behaviour rather than sending every beat to generation.
    beat_match({"u1": None})

    best = visual_fetcher._first_beat_relevant([_cand("u1"), _cand("u2")], "text", 1)

    assert best["url"] == "u1"


def test_beat_without_narration_is_not_judged(beat_match):
    beat_match({})

    best = visual_fetcher._first_beat_relevant([_cand("u1")], "", 1)

    assert best["url"] == "u1" and beat_match.judged == []
