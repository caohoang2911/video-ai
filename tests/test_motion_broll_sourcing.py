"""Key-free unit tests for motion-first b-roll sourcing: stock-video file selection, the
ffmpeg normalize pass (real ffmpeg -> 1920x1080@24fps, audio stripped), asset_store b-roll
persistence (md5 dedup + `kind="video_broll"`), and visual_fetcher's video-first-then-stills
ordering + motion-ratio accounting + `stills_only` escape hatch.

No network/API calls: stock searches short-circuit on a missing key, `requests.get` is
monkeypatched to real local mp4 bytes, and the provider/search boundaries are stubbed. Only
local ffmpeg/ffprobe (already pipeline dependencies) run for real.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ai_operator import checkpoint
from ai_operator.db.base import Base
from ai_operator.db.models import Asset
from ai_operator.media import asset_store, stock_clients, video_normalize
from ai_operator.media import visual_fetcher as vf


def _make_session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _make_clip(path: Path, *, size="640x480", rate=30, with_audio=True, seconds=0.4) -> None:
    """A real off-spec source clip (odd res + fps + audio) for the normalize pass to fix."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440"]
    cmd += ["-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [str(path)]
    subprocess.run(cmd, check=True, capture_output=True)


def _probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


# --------------------------------------------------------------------------------------
# stock-video file selection
# --------------------------------------------------------------------------------------


def test_best_pexels_file_picks_smallest_landscape_mp4_at_or_above_1080p():
    video = {"video_files": [
        {"link": "sd", "file_type": "video/mp4", "width": 960, "height": 540},
        {"link": "fhd", "file_type": "video/mp4", "width": 1920, "height": 1080},
        {"link": "uhd", "file_type": "video/mp4", "width": 3840, "height": 2160},
        {"link": "portrait", "file_type": "video/mp4", "width": 1080, "height": 1920},
        {"link": "webm", "file_type": "video/webm", "width": 1920, "height": 1080},
    ]}
    assert stock_clients._best_pexels_file(video) == "fhd"


def test_best_pexels_file_falls_back_to_largest_when_nothing_reaches_1080p():
    video = {"video_files": [
        {"link": "tiny", "file_type": "video/mp4", "width": 640, "height": 360},
        {"link": "hd720", "file_type": "video/mp4", "width": 1280, "height": 720},
    ]}
    assert stock_clients._best_pexels_file(video) == "hd720"


def test_best_pexels_file_none_when_no_landscape_mp4():
    assert stock_clients._best_pexels_file({"video_files": [
        {"link": "p", "file_type": "video/mp4", "width": 720, "height": 1280},  # portrait only
    ]}) is None


def test_best_pixabay_file_picks_smallest_tier_at_or_above_1080p():
    hit = {"videos": {
        "large": {"url": "L", "width": 3840, "height": 2160},
        "medium": {"url": "M", "width": 1920, "height": 1080},
        "small": {"url": "S", "width": 1280, "height": 720},
    }}
    assert stock_clients._best_pixabay_file(hit) == "M"


def test_best_pixabay_file_skips_portrait_tiers():
    # portrait-only hit -> None (never pillarbox a vertical clip into the 16:9 frame)
    assert stock_clients._best_pixabay_file({"videos": {
        "large": {"url": "P", "width": 1080, "height": 1920},
    }}) is None
    # mixed -> the landscape tier wins even if a portrait tier is "smaller"
    assert stock_clients._best_pixabay_file({"videos": {
        "large": {"url": "L", "width": 1920, "height": 1080},
        "small": {"url": "P", "width": 720, "height": 1280},
    }}) == "L"


def test_search_video_returns_empty_without_api_key(monkeypatch):
    monkeypatch.setattr(stock_clients.settings, "PEXELS_API_KEY", None)
    monkeypatch.setattr(stock_clients.settings, "PIXABAY_API_KEY", None)
    assert stock_clients.search_pexels_video("shipwreck") == []
    assert stock_clients.search_pixabay_video("shipwreck") == []


# --------------------------------------------------------------------------------------
# ffmpeg normalize pass
# --------------------------------------------------------------------------------------


def test_normalize_outputs_1080p24_no_audio(tmp_path):
    src = tmp_path / "src.mp4"
    _make_clip(src, size="640x480", rate=30, with_audio=True)
    dst = tmp_path / "norm" / "out.mp4"

    video_normalize.normalize(src, dst)

    streams = _probe(dst)["streams"]
    video = next(s for s in streams if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1920, 1080)
    assert video["avg_frame_rate"] == "24/1"                       # CFR 24fps
    assert not any(s["codec_type"] == "audio" for s in streams)    # audio stripped


# --------------------------------------------------------------------------------------
# asset_store.save_video_broll
# --------------------------------------------------------------------------------------


def test_save_video_broll_normalizes_dedups_and_tags_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(asset_store, "OUTPUT_DIR", tmp_path)
    Session = _make_session_factory(tmp_path)
    monkeypatch.setattr(asset_store, "SessionLocal", Session)

    clip = tmp_path / "download.mp4"
    _make_clip(clip, size="1280x720", rate=25, with_audio=True)
    clip_bytes = clip.read_bytes()

    class _Resp:
        content = clip_bytes
        def raise_for_status(self): pass

    monkeypatch.setattr(asset_store.requests, "get", lambda url, timeout=0: _Resp())

    rec = asset_store.save_video_broll(1, 3, "http://x/clip.mp4", "pexels")
    assert rec is not None
    assert rec["kind"] == "video_broll"
    dest = Path(rec["path"])
    assert dest.exists() and dest.suffix == ".mp4"
    assert not (dest.parent / "beat_03.raw.mp4").exists()  # raw source cleaned up
    streams = _probe(dest)["streams"]
    assert (streams[0]["width"], streams[0]["height"]) == (1920, 1080)

    # second call, identical bytes -> md5 dedup skips it
    assert asset_store.save_video_broll(1, 4, "http://x/clip.mp4", "pexels") is None
    with Session() as s:
        rows = s.execute(select(Asset).where(Asset.video_id == 1)).scalars().all()
        assert len(rows) == 1
        assert rows[0].kind == "video_broll"
        assert "CC0" not in rows[0].license  # pexels -> not the CC0 line


# --------------------------------------------------------------------------------------
# visual_fetcher.acquire hybrid ordering + motion ratio + stills-only
# --------------------------------------------------------------------------------------


def _patch_checkpoint(monkeypatch):
    written: dict = {}
    monkeypatch.setattr(vf.checkpoint, "is_done", lambda vid, step: False)
    monkeypatch.setattr(vf.checkpoint, "write", lambda vid, step, data: written.update(data))
    return written


def _beats(n: int) -> list[dict]:
    return [{"beat_id": i, "keywords": ["ocean", "storm"], "mood": "tense"} for i in range(1, n + 1)]


def test_acquire_prefers_video_then_falls_back_to_stills(tmp_path, monkeypatch):
    written = _patch_checkpoint(monkeypatch)
    monkeypatch.setattr(vf, "_fetch_stock_video_list", lambda kw, n, text="": [("vurl", "pexels")])
    monkeypatch.setattr(vf, "_fetch_stock", lambda kw, text="": ("iurl", "pixabay"))
    # beat 1 lands real footage; beat 2's clip fails to download/normalize -> stills fallback
    monkeypatch.setattr(vf.asset_store, "save_video_broll",
                        lambda vid, bid, url, src, index=0: {"kind": "video_broll", "beat": bid} if bid == 1 else None)
    monkeypatch.setattr(vf.asset_store, "save_stock",
                        lambda vid, bid, url, src: {"kind": "stock", "beat": bid})
    monkeypatch.setattr(vf, "_generate_visual",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("stills tier reached unexpectedly")))

    saved = vf.acquire(7, _beats(2))

    assert [r["kind"] for r in saved] == ["video_broll", "stock"]
    assert written["motion_beats"] == 1  # exactly one beat on real footage


def test_acquire_montages_multiple_clips_for_a_long_beat(tmp_path, monkeypatch):
    """A beat estimated to run long pulls several DISTINCT clips (montage), each saved with its
    own index, instead of one clip destined to loop repeatedly."""
    _patch_checkpoint(monkeypatch)
    monkeypatch.setattr(vf, "_estimate_beat_seconds", lambda vid, sl: [40.0])  # ~40s beat
    monkeypatch.setattr(vf, "_fetch_stock_video_list",
                        lambda kw, n, text="": [(f"u{i}", "pexels") for i in range(n)])  # exactly n distinct
    saves: list[tuple] = []

    def _save(vid, bid, url, src, index=0):
        saves.append((bid, index, url))
        return {"kind": "video_broll", "beat": bid, "index": index}

    monkeypatch.setattr(vf.asset_store, "save_video_broll", _save)

    saved = vf.acquire(21, [{"beat_id": 1, "keywords": ["ocean"], "mood": "tense"}])

    assert vf._clips_needed(40.0) == 4                 # ceil(40/12) capped at 4
    assert len(saved) == 4                             # four montage clips persisted for the beat
    assert [s[1] for s in saves] == [0, 1, 2, 3]       # contiguous clip indices


def test_acquire_diagram_beat_falls_back_to_stock_when_no_generator(tmp_path, monkeypatch):
    """A diagram/illustration beat skips the stock tiers and needs the generator; with no SDXL/fal
    it must fall back to a stock photo rather than leave the beat with no frame (which crashes assemble)."""
    _patch_checkpoint(monkeypatch)
    monkeypatch.setattr(vf, "_generate_visual", lambda *a, **k: None)          # no SDXL/fal installed
    monkeypatch.setattr(vf, "_fetch_stock", lambda kw, text="": ("iurl", "pexels"))   # last-resort stock hit
    monkeypatch.setattr(vf.asset_store, "save_stock", lambda vid, bid, url, src: {"kind": "stock", "beat": bid})

    saved = vf.acquire(11, [{"beat_id": 1, "keywords": ["route map", "diagram"], "mood": "informative"}])
    assert [r["kind"] for r in saved] == ["stock"]


def test_acquire_stills_only_skips_video_tier(tmp_path, monkeypatch):
    written = _patch_checkpoint(monkeypatch)
    video_calls: list = []
    monkeypatch.setattr(vf, "_fetch_stock_video_list", lambda kw, n, text="": video_calls.append(kw) or [])
    monkeypatch.setattr(vf, "_fetch_stock", lambda kw, text="": ("iurl", "pexels"))
    monkeypatch.setattr(vf.asset_store, "save_stock",
                        lambda vid, bid, url, src: {"kind": "stock", "beat": bid})

    saved = vf.acquire(8, _beats(3), stills_only=True)

    assert video_calls == []                       # video tier never consulted
    assert [r["kind"] for r in saved] == ["stock", "stock", "stock"]
    assert written["motion_beats"] == 0


def test_force_generate_skips_stock_and_generates_every_beat(tmp_path, monkeypatch):
    """gen-all mode must bypass BOTH stock tiers and send every beat to SDXL generation --
    for period/event topics where stock returns off-content footage."""
    _patch_checkpoint(monkeypatch)
    # any stock call in this mode is a bug -> blow up if the fetchers are consulted
    monkeypatch.setattr(vf, "_acquire_broll_clips",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("stock video consulted")))
    monkeypatch.setattr(vf, "_fetch_stock",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("stock photo consulted")))
    gen_beats: list[int] = []
    monkeypatch.setattr(vf, "_generate_visual",
                        lambda bid, kw, mood, dia: (gen_beats.append(bid), (tmp_path / f"g{bid}.png", "sdxl"))[1])
    monkeypatch.setattr(vf, "_flush_generated_batch",
                        lambda vid, items: [{"kind": "gen", "beat": it.beat_id} for it in items])

    saved = vf.acquire(30, _beats(3), force_generate=True)

    assert gen_beats == [1, 2, 3]                       # every beat generated
    assert [r["kind"] for r in saved] == ["gen", "gen", "gen"]


def test_clips_needed_scales_with_beat_length():
    assert vf._clips_needed(0) == 1          # unknown -> single clip
    assert vf._clips_needed(10) == 1         # short beat -> one clip
    assert vf._clips_needed(24) == 2         # ceil(24/12)
    assert vf._clips_needed(45) == vf.MAX_CLIPS_PER_BEAT   # long beat capped
