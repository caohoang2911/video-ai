"""Narration + background-music mixing.

MoviePy has no native sidechain ducking; a flat volume cut under the narration (the
documented approach for this API) is sufficient here since the music is always an
atmospheric bed, never a lead track competing with the voice.
"""

from __future__ import annotations

from pathlib import Path

from moviepy import AudioFileClip, CompositeAudioClip
from moviepy.audio.fx import AudioFadeIn, AudioFadeOut, AudioLoop

from ..logging_setup import get_logger

log = get_logger("assembler.audio_mixer")

MUSIC_VOLUME = 0.2
FADE_SECONDS = 1.5


def mix(narration: str | Path | AudioFileClip, music_path: str | Path | None) -> AudioFileClip:
    """Composite `narration` with an optional ducked, loop-to-length music bed.

    `narration` accepts a path OR an already-loaded AudioFileClip: the caller (video
    builder) needs the narration's `.duration` before this step anyway, so reusing that
    same clip here avoids re-reading the file mid-pipeline -- a real source of audio/video
    drift on long renders.
    """
    if isinstance(narration, (str, Path)):
        narration = AudioFileClip(str(narration))
    if not music_path:
        return narration

    music = AudioFileClip(str(music_path)).with_effects([AudioLoop(duration=narration.duration)])
    fade = min(FADE_SECONDS, narration.duration / 4)
    music = music.with_volume_scaled(MUSIC_VOLUME).with_effects(
        [AudioFadeIn(fade), AudioFadeOut(fade)]
    )
    return CompositeAudioClip([narration, music])
