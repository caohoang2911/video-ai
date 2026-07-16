"""Unit tests for Ken Burns motion math: duration-scaled zoom (no freeze tail on long
beats), center-anchored zoom, pan sweep clamping, per-beat variant cycling, and the
portrait-vs-landscape zoom amplitude split. Pure expression checks + a captured-command
check; no real ffmpeg run needed here (test_segment_builder exercises the real filter).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_operator.assembler import kenburns_ffmpeg
from ai_operator.assembler.kenburns_ffmpeg import (
    DIP_FADE_SECONDS,
    FPS,
    MOTIONS,
    TARGET_ZOOM,
    TARGET_ZOOM_PORTRAIT,
    _motion_exprs,
    motion_for_index,
)


def _step_from_expr(expr: str) -> float:
    # linear-in-`on` form: "min(1.0+0.001234*on,1.28)" / "max(1.28-0.001234*on,1.0)"
    for sep in ("+", "-"):
        if f"{sep}" in expr and "*on" in expr:
            return float(expr.split("*on")[0].split(sep)[-1])
    raise AssertionError(f"no step found in {expr!r}")


def _eval_z(expr: str, on: int) -> float:
    """Evaluate a zoom expression (pure function of `on`; min/max/+/-/* only) for one frame."""
    return eval(expr, {"__builtins__": {}}, {"min": min, "max": max, "on": on})


@pytest.mark.parametrize("seconds", [3.0, 8.0, 20.0, 45.0])
@pytest.mark.parametrize("motion", ["zoom_in", "zoom_out"])
def test_zoom_step_scales_with_duration_so_motion_never_freezes(seconds, motion):
    """The zoom target must be reached exactly at the segment's LAST frame. The old fixed
    step hit the cap after ~8s of wall time and froze for the remainder of longer beats."""
    frames = int(round(seconds * FPS))
    z, x, y = _motion_exprs(motion, frames, TARGET_ZOOM)
    step = _step_from_expr(z)
    travelled = step * (frames - 1)
    # step is serialized at 8 decimals, so allow up to one frame's worth of rounding
    assert abs(travelled - (TARGET_ZOOM - 1.0)) < step


def test_zoom_expressions_anchor_center_not_top_left():
    for motion in ("zoom_in", "zoom_out"):
        _, x, y = _motion_exprs(motion, 120, TARGET_ZOOM)
        assert x == "iw/2-(iw/zoom/2)"
        assert y == "ih/2-(ih/zoom/2)"


def test_pan_expressions_hold_zoom_and_sweep_clamped():
    z_lr, x_lr, y_lr = _motion_exprs("pan_lr", 120, 1.3)
    z_rl, x_rl, _ = _motion_exprs("pan_rl", 120, 1.3)
    assert z_lr == "1.3" and z_rl == "1.3"          # constant zoom during pans
    assert x_lr.startswith("min(") and "on/" in x_lr  # clamped left-to-right sweep
    assert x_rl.startswith("max(") and x_rl.endswith(",0)")  # clamped right-to-left
    assert y_lr == "ih/2-(ih/zoom/2)"               # vertically centered


def test_single_frame_segment_does_not_divide_by_zero():
    z, _, _ = _motion_exprs("zoom_in", 1, TARGET_ZOOM)
    assert "*on" in z  # expression still well-formed


def test_zoom_out_starts_at_target_no_wide_flash():
    """Regression: zoom_out must render its FIRST frame (on=0) already at `target`, then ease
    down to 1.0. The old `if(eq(on,1),...)` form left frame 0 at zoom 1.0 (wide), so a zoom-out
    beat flashed wide then punched in for one frame -- the jarring 'zoom out fast then zoom in'."""
    frames = 120
    z, _, _ = _motion_exprs("zoom_out", frames, TARGET_ZOOM)
    assert "eq(on,1)" not in z
    assert _eval_z(z, 0) == pytest.approx(TARGET_ZOOM)          # first frame already zoomed
    assert _eval_z(z, frames - 1) == pytest.approx(1.0)         # last frame back to full
    # strictly non-increasing across the clip (no snap-in anywhere)
    vals = [_eval_z(z, i) for i in range(frames)]
    assert all(b <= a + 1e-9 for a, b in zip(vals, vals[1:]))


def test_zoom_in_starts_wide_and_ends_at_target():
    frames = 120
    z, _, _ = _motion_exprs("zoom_in", frames, TARGET_ZOOM)
    assert _eval_z(z, 0) == pytest.approx(1.0)                  # first frame full/wide
    assert _eval_z(z, frames - 1) == pytest.approx(TARGET_ZOOM)
    vals = [_eval_z(z, i) for i in range(frames)]
    assert all(b >= a - 1e-9 for a, b in zip(vals, vals[1:]))   # non-decreasing, no snap


def test_unknown_motion_raises():
    with pytest.raises(ValueError):
        _motion_exprs("spin", 120, 1.3)


def test_motion_for_index_cycles_all_variants_and_adjacent_beats_differ():
    n = len(MOTIONS)
    seq = [motion_for_index(i) for i in range(2 * n)]
    assert seq[:n] == list(MOTIONS) == seq[n:]
    assert all(a != b for a, b in zip(seq, seq[1:]))


def test_default_rotation_has_no_lateral_pan():
    # lateral pans never show the full frame -> excluded from the per-beat cycle
    assert "pan_lr" not in MOTIONS and "pan_rl" not in MOTIONS
    assert set(MOTIONS) == {"zoom_in", "zoom_out"}


def test_non_16x9_source_renders_square_pixels_and_target_aspect(tmp_path):
    """Real-ffmpeg regression test: a source whose aspect differs from the target (square
    SDXL still, tall archival scan) must come out SAR 1:1 at the exact target aspect.
    A bare `scale` compensates SAR to preserve the source aspect; that flag survives
    zoompan + concat and players then letterbox the whole video (square-with-black-bars)."""
    import subprocess

    src = tmp_path / "tall.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=navy:s=1920x1267", "-frames:v", "1", str(src)],
        check=True, capture_output=True,
    )
    seg = kenburns_ffmpeg.render_segment(src, 1.0, tmp_path / "seg.mp4", motion="pan_lr")
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v",
         "-show_entries", "stream=sample_aspect_ratio,display_aspect_ratio",
         "-of", "csv=p=0", str(seg)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert probe == "1:1,16:9"


def test_fade_flags_append_black_dip(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(kenburns_ffmpeg.subprocess, "run",
                        lambda cmd, **kw: captured.append(cmd[cmd.index("-vf") + 1])
                        or SimpleNamespace(returncode=0, stderr=""))
    img = tmp_path / "beat_01.jpg"
    img.write_bytes(b"x")
    kenburns_ffmpeg.render_segment(img, 10.0, tmp_path / "a.mp4", fade_in=True, fade_out=True)
    vf = captured[0]
    assert f"fade=t=in:st=0:d={DIP_FADE_SECONDS}" in vf
    assert f"fade=t=out:st={10.0 - DIP_FADE_SECONDS:.3f}:d={DIP_FADE_SECONDS}" in vf
    # no fades by default
    kenburns_ffmpeg.render_segment(img, 10.0, tmp_path / "b.mp4")
    assert "fade=" not in captured[1]


def test_portrait_render_uses_stronger_zoom_than_landscape(tmp_path, monkeypatch):
    captured = []

    def _fake_run(cmd, **kw):
        captured.append(cmd[cmd.index("-vf") + 1])
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(kenburns_ffmpeg.subprocess, "run", _fake_run)
    img = tmp_path / "beat_01.jpg"
    img.write_bytes(b"x")

    kenburns_ffmpeg.render_segment(img, 2.0, tmp_path / "land.mp4")
    kenburns_ffmpeg.render_segment(img, 2.0, tmp_path / "port.mp4", size=(1080, 1920))
    kenburns_ffmpeg.render_segment(img, 2.0, tmp_path / "over.mp4", target_zoom=1.5)

    assert str(TARGET_ZOOM) in captured[0] and str(TARGET_ZOOM_PORTRAIT) not in captured[0]
    assert str(TARGET_ZOOM_PORTRAIT) in captured[1]
    assert "1.5" in captured[2]
