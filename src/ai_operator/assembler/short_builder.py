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
from ..db import InvalidTransition, SessionLocal, VideoState
from ..db.models import Video
from ..logging_setup import get_logger
from . import branding, ffmpeg_encode, kenburns_ffmpeg, srt_writer
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
_PORTRAIT_SUB_STYLE = (
    "FontSize=11,Outline=2,Shadow=0,BorderStyle=1,Alignment=2,MarginV=85,"
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
    # Shorts beats carry no narration_span, so time is split evenly across them.
    per_beat = narration_dur / len(beats)

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
                still, per_beat, work / f"seg_{i:02d}.mp4", zoom_in=(i % 2 == 0), size=SHORT_SIZE
            )
        )

    srt_path = srt_writer.write_srt(transcribe(narration_path), video_dir / "captions.srt")
    base = ffmpeg_encode.concat_copy(segments, video_dir / "base.mp4")
    # Same mood-matched, ducked/swelling bed as mains (picker reads the short's beat moods
    # and writes the CC-BY credit into script.json for the publish description).
    body = ffmpeg_encode.burn_and_mux(
        base, srt_path, narration_path, _resolve_music_path(video_id, video_dir),
        video_dir / "body.mp4", sub_style=_PORTRAIT_SUB_STYLE,
        pre_fx=ffmpeg_encode.ambient_glow_fx(narration_dur, SHORT_SIZE),
        post_fx=_pinned_title_fx(script.get("text_overlay") or "", video_dir),
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
    """Hook title pinned to the top blur band for the WHOLE body — static while the image
    pans underneath (drawtext runs after zoompan), gold with a heavy outline (no box: the
    blur band is the backdrop). One drawtext per line so each line self-centers; wrap is
    wide enough that a 4-6 word hook lands on ~2 lines."""
    if not overlay_text.strip():
        return None
    lines = textwrap.wrap(overlay_text, 18) or [" "]
    draws = []
    for i, line in enumerate(lines):
        # burn_and_mux runs with cwd=video_dir -> textfiles referenced by basename
        txt = video_dir / f"hook_{i}.txt"
        txt.write_text(line, encoding="utf-8")
        draws.append(
            f"drawtext=fontfile='{branding._drawtext_font()}':textfile={txt.name}:"
            f"fontcolor=0xF5C542:borderw=6:bordercolor=black:fontsize=84:"
            f"x=(w-text_w)/2:y={96 + i * 105}"
        )
    return ",".join(draws)


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
        backdrop, END_CARD_SECONDS, work / "endcard_motion.mp4", zoom_in=True, size=SHORT_SIZE
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


