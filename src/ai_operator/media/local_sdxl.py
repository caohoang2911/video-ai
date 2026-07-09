"""Local SDXL image generation on Apple Silicon (M1 Max via MPS).

`torch`/`diffusers` are an opt-in extra (`pip install .[sdxl]`), NOT a base dependency, so
every heavy import is deferred into `_load_pipeline()` -- importing this module (which the
CLI does on every invocation once `visual_fetcher` is wired in) must never require torch to
be installed. The pipeline itself is a module-level singleton: loading SDXL weights takes
tens of seconds, and beats within one video call `generate()` many times.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ..logging_setup import get_logger

log = get_logger("local_sdxl")

MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
INFERENCE_STEPS = 30

# SDXL output must never be mistaken for real documentary footage (compliance + avoids
# convincing-but-fake "stock" b-roll) -- always prepend a non-photorealistic style prompt.
_MAP_STYLE_PREFIX = "hand-drawn historical map, muted 19th-century colors, "
_GENERIC_ILLUSTRATION_PREFIX = "editorial illustration, muted color palette, non-photorealistic, "
_MAX_PROMPT_CHARS = 400

_pipeline = None  # loaded once per process; see module docstring


def _load_pipeline():
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    import torch
    from diffusers import StableDiffusionXLPipeline

    # float32, not float16: SDXL's VAE decode overflows to NaN in fp16 on the MPS backend for
    # some seeds/prompts, producing all-black frames. fp32 is ~2x slower but numerically stable
    # on Apple Silicon (M1 Max 64GB has the headroom); attention slicing keeps peak memory down.
    pipe = StableDiffusionXLPipeline.from_pretrained(MODEL_ID, torch_dtype=torch.float32)
    pipe = pipe.to("mps")
    pipe.enable_attention_slicing()
    _pipeline = pipe
    log.info("SDXL pipeline loaded on mps")
    return _pipeline


def generate(prompt: str, *, is_diagram: bool = True, seed: int | None = None) -> Path:
    """Generate a 1024x1024 image (caller crops/upscales to 16:9). Free -- no budget_guard."""
    pipe = _load_pipeline()
    import torch

    style_prefix = _MAP_STYLE_PREFIX if is_diagram else _GENERIC_ILLUSTRATION_PREFIX
    full_prompt = f"{style_prefix}{prompt}"[:_MAX_PROMPT_CHARS]

    generator = torch.Generator(device="mps").manual_seed(seed) if seed is not None else None
    result = pipe(prompt=full_prompt, num_inference_steps=INFERENCE_STEPS, generator=generator)
    image = result.images[0]

    # Guard against a residual VAE-NaN (all-black) frame silently shipping: fail loudly so the
    # caller can retry/fall back rather than burning a black shot into the render.
    import numpy as np

    if float(np.asarray(image).mean()) < 5.0:
        raise RuntimeError("SDXL produced a near-black frame (VAE numerical instability)")

    fd, path_str = tempfile.mkstemp(suffix=".png", prefix="sdxl_")
    os.close(fd)
    path = Path(path_str)
    image.save(path)
    log.info("sdxl generated %s (diagram=%s, prompt=%r)", path.name, is_diagram, full_prompt)
    return path
