"""CLIP relevance re-ranking of candidate stock previews against a beat's content.

Stock search returns hits ranked by the provider's own keyword match, so the first hit is
often a generic "ocean/ship" clip rather than the one that fits THIS beat. This scores each
candidate's small preview thumbnail against the beat text (CLIP puts image + text in one
embedding space) and reorders best-first, so the montage picks footage that actually tracks
the narration. Lazy-loaded and fully best-effort: any failure (no model, no torch, bad
image) degrades to the original order, so the pipeline never hard-depends on it. Reuses the
transformers/torch stack already installed for local SDXL -- no new dependency.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..logging_setup import get_logger

log = get_logger("clip_reranker")

_MODEL_ID = "openai/clip-vit-base-patch32"  # small (~600MB), CPU-friendly, cached after first load


def available() -> bool:
    """True if the CLIP stack can be imported (model still downloads lazily on first rank)."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


@lru_cache(maxsize=1)
def _model():
    import torch
    from transformers import CLIPModel, CLIPProcessor

    model = CLIPModel.from_pretrained(_MODEL_ID)
    model.eval()
    processor = CLIPProcessor.from_pretrained(_MODEL_ID)
    return model, processor, torch


def rank(text: str, image_paths: list[Path]) -> list[int]:
    """Indices of `image_paths` sorted by CLIP similarity to `text`, most-relevant first.

    Returns the identity order [0, 1, ...] on any failure so callers can use it unconditionally.
    """
    if len(image_paths) <= 1:
        return list(range(len(image_paths)))
    try:
        from PIL import Image

        model, processor, torch = _model()
        images = [Image.open(p).convert("RGB") for p in image_paths]
        inputs = processor(
            text=[text or "documentary footage"], images=images,
            return_tensors="pt", padding=True, truncation=True,
        )
        with torch.no_grad():
            # logits_per_image: [n_images, n_text]; higher = more similar to the text
            scores = model(**inputs).logits_per_image.squeeze(1).tolist()
        return sorted(range(len(image_paths)), key=lambda i: scores[i], reverse=True)
    except Exception as exc:  # noqa: BLE001 - re-rank is best-effort; keep the original order
        log.warning("CLIP rerank failed (%s) -> keeping original order", exc)
        return list(range(len(image_paths)))
