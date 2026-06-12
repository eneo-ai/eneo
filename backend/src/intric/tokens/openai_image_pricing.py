"""OpenAI-specific image token pricing.

Mirrors OpenAI's documented vision cost rules, which differ per model family:

- Patch-based models (gpt-4.1-mini/nano, gpt-5-mini/nano, o4-mini) count
  32×32 pixel patches capped at 1536, multiplied by a per-model factor.
- Tile-based models (gpt-4o, gpt-4.1, gpt-4.5, gpt-5, o1/o3, gpt-4o-mini)
  scale the image into 2048², then the short side to 768px, and charge a
  base cost plus a per-512px-tile cost at detail "high".

Maintenance contract: this is the only place that tracks OpenAI's vision
pricing. The drift alarm in token_utils (estimate vs provider-reported
prompt_tokens) surfaces staleness. Unknown models fall back to the classic
85 + 170/tile formula.
"""

import math

_PATCH_PX = 32
_PATCH_BUDGET = 1536
# Longest/most specific marker first — "gpt-5-mini" must match before the
# tile-based "gpt-5".
_PATCH_MULTIPLIERS: tuple[tuple[str, float], ...] = (
    ("gpt-5.4-mini", 1.62),
    ("gpt-5.4-nano", 2.46),
    ("gpt-5-mini", 1.62),
    ("gpt-5-nano", 2.46),
    ("gpt-4.1-mini", 1.62),
    ("gpt-4.1-nano", 2.46),
    ("o4-mini", 1.72),
)

_TILE_PX = 512
_FIT_EDGE = 2048
_SHORT_EDGE = 768
# (base tokens, tokens per tile); most specific marker first.
_TILE_COSTS: tuple[tuple[str, tuple[int, int]], ...] = (
    ("gpt-4o-mini", (2833, 5667)),
    ("computer-use-preview", (65, 129)),
    ("o1", (75, 150)),
    ("o3", (75, 150)),
    ("gpt-5", (70, 140)),
)
_DEFAULT_TILE_COST = (85, 170)  # gpt-4o, gpt-4.1, gpt-4.5, unknown models


def _patch_based_tokens(width: int, height: int, multiplier: float) -> int:
    """OpenAI's documented patch cost: 32×32 patches, scaled down to fit the
    1536-patch budget on whole-patch boundaries, times the model factor."""
    patches = math.ceil(width / _PATCH_PX) * math.ceil(height / _PATCH_PX)
    if patches > _PATCH_BUDGET:
        shrink = math.sqrt(_PATCH_PX**2 * _PATCH_BUDGET / (width * height))
        shrink *= min(
            math.floor(width * shrink / _PATCH_PX) / (width * shrink / _PATCH_PX),
            math.floor(height * shrink / _PATCH_PX) / (height * shrink / _PATCH_PX),
        )
        width = int(width * shrink)
        height = int(height * shrink)
        patches = math.ceil(width / _PATCH_PX) * math.ceil(height / _PATCH_PX)
    return math.ceil(patches * multiplier)


def _tile_based_tokens(width: int, height: int, base: int, per_tile: int) -> int:
    """OpenAI's documented high-detail tile cost: fit in 2048², short side to
    768px, then base + per-tile for each 512px tile."""
    scale = min(1.0, _FIT_EDGE / max(width, height))
    scaled_w, scaled_h = width * scale, height * scale
    scale = min(1.0, _SHORT_EDGE / min(scaled_w, scaled_h))
    scaled_w, scaled_h = scaled_w * scale, scaled_h * scale
    tiles = math.ceil(scaled_w / _TILE_PX) * math.ceil(scaled_h / _TILE_PX)
    return base + per_tile * tiles


def openai_image_tokens(width: int, height: int, model_name: str = "") -> int:
    """OpenAI's documented image cost for the given pixel dimensions."""
    name = model_name.lower()
    for marker, multiplier in _PATCH_MULTIPLIERS:
        if marker in name:
            return _patch_based_tokens(width, height, multiplier)
    base, per_tile = next(
        (cost for marker, cost in _TILE_COSTS if marker in name),
        _DEFAULT_TILE_COST,
    )
    return _tile_based_tokens(width, height, base, per_tile)
