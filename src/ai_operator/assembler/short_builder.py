"""Vertical (1080x1920) render path for Shorts — a thin portrait orchestrator over the
same building blocks the landscape assembler uses (Ken Burns, captions, branding, encode).

Portrait framing: each landscape beat image becomes a blurred-pad still (image fit to
width, blurred copy fills top/bottom) so nothing is cropped away, then the EXISTING Ken
Burns renderer animates it at portrait size. The first still carries the on-screen hook
overlay (Shorts autoplay muted); the clip closes on a curiosity-question end card.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

from ..checkpoint import is_done, make_idempotency_key
from ..checkpoint import write as write_checkpoint
from ..config import OUTPUT_DIR, settings
from ..content.short_schema import locate_spans
from ..db import InvalidTransition, SessionLocal, VideoState
from ..db.models import Video
from ..logging_setup import get_logger
from . import ass_karaoke_writer, branding, ffmpeg_encode, headline_text, kenburns_ffmpeg, srt_writer
from .caption_whisper import transcribe
from .video_builder import STEP, _persist_rendered_state, _resolve_music_path

log = get_logger("assembler.short_builder")

SHORT_SIZE = (1080, 1920)
MAX_SHORT_SECONDS = 60.0
END_CARD_SECONDS = 3.0
# Portrait caption style: same family as the landscape _SUB_STYLE. libass scales FontSize
# against PlayResY=288, so portrait (1920 tall) doubles the rendered pixels vs landscape —
# 11 lands ~73px (mobile-legible without covering the frame); MarginV=85 (~570px up) keeps
# the block clear of the Shorts UI zone (bottom ~25%: like/comment rail + title strip).
# MarginL/MarginR=45 (script units on PlayResX=384 -> ~127px per side at 1080w): phones
# taller than 16:9 (19.5:9, 20:9) cover-fill the 9:16 frame and crop up to ~10% off each
# side, so caption lines must wrap well inside the frame or edge glyphs get cut on screen.
_PORTRAIT_SUB_STYLE = (
    "FontSize=11,Bold=-1,Outline=0.9,Shadow=0.4,BorderStyle=1,Alignment=2,"
    "MarginV=85,MarginL=45,MarginR=45,"
    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000"
)


def build_short(video_id: int) -> dict:
    """Render `output/<id>/final.mp4` (9:16, <=60s), set state=rendered, return
    {"video_path", "duration_sec"}. Idempotent like assemble_video."""
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None:
            raise ValueError(f"video {video_id} not found")
        state, duration_sec = video.state, video.duration_sec

    video_dir = OUTPUT_DIR / str(video_id)
    final_path = video_dir / "final.mp4"
    if final_path.exists() and (is_done(video_id, STEP) or state == VideoState.RENDERED.value):
        log.info("short %s: already rendered -> reusing %s", video_id, final_path)
        return {"video_path": str(final_path), "duration_sec": duration_sec or 0}
    if state not in (VideoState.VOICED.value, VideoState.RENDERED.value):
        raise InvalidTransition(f"short {video_id} state={state}, expected voiced")

    script = json.loads((video_dir / "script.json").read_text(encoding="utf-8"))
    narration_path = video_dir / "narration.mp3"
    narration_dur = ffmpeg_encode.probe_duration(narration_path)
    if narration_dur + END_CARD_SECONDS > MAX_SHORT_SECONDS:
        raise ValueError(
            f"short {video_id}: narration {narration_dur:.1f}s + end card exceeds the 60s Shorts cap"
        )

    beats = script["beats"]
    # Whisper runs BEFORE the segment loop: its segment ends drive the per-beat durations
    # (image cuts snap to phrase boundaries instead of an even grid) and, when enabled,
    # its word times drive the karaoke captions. One transcription serves both.
    caps = transcribe(narration_path, with_words=settings.SHORTS_KARAOKE_CAPTIONS)
    # beat_targets reports its own span coverage (none / partial); no need to log again here.
    targets = beat_targets(script.get("narration", ""), beats, narration_dur)
    durations = _beat_durations(narration_dur, len(beats), caps, targets)
    if any(d <= 0 for d in durations):
        # The duration machinery guards against this; a leak would hand ffmpeg a negative -t
        # (crash) or a zero-length beat (silently dropped). Fail readably instead.
        raise ValueError(f"short {video_id}: non-positive beat duration in {durations}")

    work = video_dir / "segments"
    work.mkdir(parents=True, exist_ok=True)
    segments: list[Path] = []
    stills: list[Path] = []
    for i in range(len(beats)):
        img = video_dir / "img" / f"beat_{i + 1:02d}.jpg"
        still = _portrait_still(img, work / f"still_{i:02d}.png")
        stills.append(still)
        segments.append(
            kenburns_ffmpeg.render_segment(
                still, durations[i], work / f"seg_{i:02d}.mp4",
                motion=kenburns_ffmpeg.motion_for_index(i), size=SHORT_SIZE,
            )
        )

    if settings.SHORTS_KARAOKE_CAPTIONS and any(s.get("words") for s in caps):
        # ASS carries its own karaoke style; force_style would clobber the per-word timing.
        cap_path = ass_karaoke_writer.write_karaoke_ass(caps, video_dir / "captions.ass")
        cap_style = None
    else:
        cap_path = srt_writer.write_srt(caps, video_dir / "captions.srt")
        cap_style = _PORTRAIT_SUB_STYLE
    base = ffmpeg_encode.concat_copy(segments, video_dir / "base.mp4")
    # Same mood-matched, ducked/swelling bed as mains (picker reads the short's beat moods
    # and writes the CC-BY credit into script.json for the publish description).
    body = ffmpeg_encode.burn_and_mux(
        base, cap_path, narration_path, _resolve_music_path(video_id, video_dir),
        video_dir / "body.mp4", sub_style=cap_style,
        pre_fx=ffmpeg_encode.ambient_glow_fx(narration_dur, SHORT_SIZE),
        post_fx=_pinned_title_fx(
            script.get("overlay_headline") or script.get("text_overlay") or "", video_dir
        ),
    )
    for f in video_dir.glob("hook_*.txt"):
        f.unlink(missing_ok=True)
    # Short punchy card copy (2 fragments) beats re-reading the spoken question; older
    # scripts without end_card_text fall back to the question.
    card_copy = script.get("end_card_text") or script["curiosity_question"]
    end_card = _end_card(stills[-1], card_copy, video_dir / "endcard.mp4", work)
    ffmpeg_encode.concat_copy([body, end_card], final_path, audio_reencode=True)

    rendered = int(round(ffmpeg_encode.probe_duration(final_path)))
    shutil.rmtree(work, ignore_errors=True)
    for f in (base, body, end_card):
        Path(f).unlink(missing_ok=True)

    _persist_rendered_state(video_id, str(final_path), rendered)
    write_checkpoint(
        video_id, STEP,
        {"video_path": str(final_path),
         "idempotency_key": make_idempotency_key(str(video_id), STEP, str(narration_path))},
    )
    return {"video_path": str(final_path), "duration_sec": rendered}


# Image cuts snap to caption-segment ends within this window; smaller would rarely snap,
# larger would visibly unbalance beats. Segment ends are whisper's stable output -- word
# times drift on proper nouns, so they never drive cuts.
_SNAP_TOLERANCE_S = 0.8
_MIN_BEAT_S = 1.5


def beat_targets(narration: str, beats: list[dict], narration_dur: float) -> list[float] | None:
    """Where each image SHOULD cut, from the narration each beat says it illustrates.

    Returns `n_beats - 1` interior boundary times, or None when no beat span could be located
    (older scripts with no spans, or a batch the model paraphrased) so the caller keeps the
    even split.

    Speech runs at a near-constant rate, so a span's character offset into the narration is a
    good proxy for its offset in time -- good enough to put the image on the right sentence,
    which an even split cannot do once sentences differ in length. Each beat that locates its
    span is ANCHORED at that time; a beat whose span was paraphrased is INTERPOLATED between its
    nearest anchored neighbours (and the fixed ends: beat 0 at 0.0, the last beat at
    narration_dur), so one bad span stays local instead of dragging every later boundary with it.
    Matching folds the typography a model drifts on while copying, so a near-verbatim span still
    anchors.
    """
    if not narration or len(beats) < 2:
        return None
    n = len(beats)
    interior = n - 1
    spans = [(b.get("narration_span") or "") for b in beats]
    offsets, total = locate_spans(narration, spans)
    if total == 0:
        return None
    # Anchor every interior beat that located its span. A span that resolves BEFORE an earlier
    # anchor (the model emitted its beats out of order) is treated as unmatched rather than
    # clamped forward -- forward-clamping is what used to warp every boundary after it.
    anchors: list[tuple[int, float]] = [(0, 0.0)]
    for i in range(1, n):
        at = offsets[i]
        if at is None:
            continue
        t = at / total * narration_dur
        if t >= anchors[-1][1]:
            anchors.append((i, t))
    found = len(anchors) - 1  # excludes the fixed beat-0 anchor
    if found == 0:
        n_present = sum(1 for s in spans[1:] if s.strip())
        if n_present:
            first = next((s.strip()[:60] for s in spans[1:] if s.strip()), "")
            log.warning(
                "short: %s interior beat spans present but none located in the narration -- "
                "images fall back to an even split; first: %r", n_present, first,
            )
        else:
            log.info("short: beats carry no narration spans -- images fall back to an even split")
        return None
    if found < interior:
        log.warning(
            "short: %s/%s interior beat spans located, %s interpolated between neighbours",
            found, interior, interior - found,
        )
    anchors.append((n, narration_dur))
    targets: list[float] = []
    for i in range(1, n):
        exact = next((t for bi, t in anchors if bi == i), None)
        if exact is not None:
            targets.append(exact)
            continue
        lo = max((a for a in anchors if a[0] < i), key=lambda a: a[0])
        hi = min((a for a in anchors if a[0] > i), key=lambda a: a[0])
        targets.append(lo[1] + (i - lo[0]) / (hi[0] - lo[0]) * (hi[1] - lo[1]))
    return targets


def _beat_durations(
    narration_dur: float, n_beats: int, caps: list[dict], targets: list[float] | None = None
) -> list[float]:
    """Per-beat durations for the Shorts segment loop: boundaries from `targets` (each beat's
    own narration span) or an even split when there are none, each snapped to the nearest
    caption-segment end within _SNAP_TOLERANCE_S so the image cut lands between phrases
    instead of mid-word. Every boundary keeps _MIN_BEAT_S behind it AND reserves _MIN_BEAT_S
    for each beat still ahead, so no beat -- including the last -- is squeezed below the floor
    or pushed past narration_dur into a negative duration; durations always sum to narration_dur
    exactly."""
    per = narration_dur / n_beats
    if narration_dur < n_beats * _MIN_BEAT_S:
        # Too little audio to give every beat a real shot; an even split at least stays positive.
        return [per] * n_beats
    ends = sorted(float(s.get("end") or 0.0) for s in caps)
    bounds: list[float] = []
    prev = 0.0
    for i in range(1, n_beats):
        target = targets[i - 1] if targets and i - 1 < len(targets) else i * per
        lo = prev + _MIN_BEAT_S
        # Reserve a whole minimum beat for each of the (n_beats - i) beats after this boundary,
        # so the final beat can never collapse to zero or overshoot into a negative duration
        # (which crashes the ffmpeg trim filter) when several targets pile up near the end.
        hi = narration_dur - _MIN_BEAT_S * (n_beats - i)
        cands = [e for e in ends if abs(e - target) <= _SNAP_TOLERANCE_S and lo <= e <= hi]
        # No caption end near the target: keep the boundary moving forward, but by a real beat
        # rather than 0.1s. Two frames of an image is a flicker, not a shot.
        chosen = min(cands, key=lambda e: abs(e - target)) if cands else target
        bounds.append(min(max(chosen, lo), hi))
        prev = bounds[-1]
    return [b - a for a, b in zip([0.0, *bounds], [*bounds, narration_dur])]


def _portrait_still(src: Path, out: Path) -> Path:
    """Composite one landscape image into a 1080x1920 blurred-pad still. The hook title is
    NOT burned here — it would ride the Ken Burns motion; it's pinned at the mux stage."""
    src, out = Path(src).resolve(), Path(out).resolve()
    if not src.exists():
        raise FileNotFoundError(f"short beat image not found: {src}")
    w, h = SHORT_SIZE
    vf = (
        f"split=2[bg][fg];"
        f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=40:2[b];"
        f"[fg]scale={w}:-2[f];[b][f]overlay=(W-w)/2:(H-h)/2"
    )
    cmd = ["ffmpeg", "-y", "-i", str(src), "-vf", vf, "-frames:v", "1", str(out)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"portrait still failed for {src}: {result.stderr[-800:]}")
    return out


def _pinned_title_fx(overlay_text: str, video_dir: Path) -> str | None:
    """Hook headline pinned to the top blur band for the WHOLE body — static while the image
    pans underneath (drawtext runs after zoompan). White-set / red-gap curiosity headline:
    the setup line(s) off-white, the number/gap line red. See `headline_text` for the wrap,
    fit and color logic; the case (Title vs UPPER) is a config pick."""
    return headline_text.build_headline_fx(
        overlay_text or "", video_dir, case=settings.SHORTS_HEADLINE_CASE
    )


_LOGO_PX = 220
_CHANNEL_AVATAR = OUTPUT_DIR / "_channel_assets" / "avatar.png"


def _end_card(last_still: Path, card_copy: str, out: Path, work: Path) -> Path:
    """Curiosity end card that continues the film instead of cutting to a flat color: the
    LAST beat's frame darkened + blurred keeps drifting (Ken Burns), the channel logo sits
    in a circle above the copy, each text line centers independently (a multi-line drawtext
    block is left-ragged) and the CTA line is gold."""
    w, h = SHORT_SIZE
    # 1) darkened, softened backdrop from the final frame
    backdrop = work / "endcard_bg.png"
    _run_ffmpeg(
        ["ffmpeg", "-y", "-i", str(last_still),
         "-vf", "eq=brightness=-0.22:saturation=0.7,boxblur=28", str(backdrop)]
    )
    # 2) the card keeps the motion going — same Ken Burns as the beats
    moving = kenburns_ffmpeg.render_segment(
        backdrop, END_CARD_SECONDS, work / "endcard_motion.mp4", motion="zoom_in", size=SHORT_SIZE
    )
    # 3) layout: [logo] [channel name] gap [fragment lines] gap [CTA], all vertically centered
    lines: list[tuple[str, str, int]] = []
    if settings.CHANNEL_NAME:
        lines.append((settings.CHANNEL_NAME.strip(), "0xF5C542", 50))  # gold brand lockup
        lines.append(("", "white", 34))  # spacer
    lines += [
        (ln, "white", 76)
        for frag in card_copy.split("\n")
        for ln in (textwrap.wrap(frag, 20) or [""])
    ]
    lines.append(("", "white", 40))  # spacer
    lines.append(("Full story on the channel", "white", 52))
    has_logo = _CHANNEL_AVATAR.exists()
    logo_block = (_LOGO_PX + 56) if has_logo else 0
    total = logo_block + sum(int(fs * 1.32) for _, _, fs in lines)
    y = (h - total) // 2

    cmd = ["ffmpeg", "-y", "-i", str(moving.resolve()),
           "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    graph_head = ""
    vin = "[0:v]"
    if has_logo:
        cmd += ["-i", str(_CHANNEL_AVATAR.resolve())]
        r = _LOGO_PX // 2
        # circle-crop the square avatar via a per-pixel alpha mask
        graph_head = (
            f"[2:v]scale={_LOGO_PX}:{_LOGO_PX},format=rgba,"
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            f"a='if(lte((X-{r})*(X-{r})+(Y-{r})*(Y-{r}),{r * r}),alpha(X,Y),0)'[logo];"
            f"[0:v][logo]overlay=(W-{_LOGO_PX})/2:{y}[vlogo];"
        )
        vin = "[vlogo]"
        y += logo_block

    font = branding._drawtext_font()
    draws = []
    for i, (text, color, fs) in enumerate(lines):
        if text:
            txt_file = work / f"endcard_line_{i}.txt"
            txt_file.write_text(text, encoding="utf-8")
            draws.append(
                f"drawtext=fontfile='{font}':textfile={txt_file.name}:fontcolor={color}:"
                f"fontsize={fs}:borderw=2:bordercolor=black:x=(w-text_w)/2:y={y}"
            )
        y += int(fs * 1.32)
    cmd += [
        "-filter_complex", f"{graph_head}{vin}{','.join(draws)}[vout]",
        "-map", "[vout]", "-map", "1:a", "-t", f"{END_CARD_SECONDS}",
        *ffmpeg_encode.video_encode_args(), "-r", str(kenburns_ffmpeg.FPS),
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        str(out.resolve()),
    ]
    _run_ffmpeg(cmd, cwd=work)
    return out


def _run_ffmpeg(cmd: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({' '.join(cmd[:4])}...): {result.stderr[-800:]}")


