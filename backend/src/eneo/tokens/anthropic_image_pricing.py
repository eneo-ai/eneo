"""Anthropic-specific image token pricing.

Mirrors the reference implementation in Anthropic's vision documentation:
one token per 28×28 pixel patch, after resizing the image to fit both a
long-edge limit and a per-image token budget. litellm prices all images with
OpenAI's tile formula, which over/undercounts Claude — this module is the
correction.

Maintenance contract: this is the only place that tracks Anthropic's vision
pricing. The drift alarm in token_utils (estimate vs provider-reported
prompt_tokens) surfaces staleness. To drop the special handling entirely,
delete this module, its test file, and the single dispatch branch in
token_utils.count_image_tokens — Claude images then price with the generic
OpenAI tile formula (roughly 30–40% off for large images).
"""

import math

_PATCH_PX = 28
_MAX_EDGE = 1568
_MAX_TOKENS = 1568
_HIGH_RES_MAX_EDGE = 2576
_HIGH_RES_MAX_TOKENS = 4784
# Models with high-resolution image support (larger native limits). Future
# model families are unknowable here — they fall back to the standard limits
# and the drift alarm surfaces the mismatch.
_HIGH_RES_MARKERS = ("opus-4-7", "opus-4-8", "fable", "mythos")


def is_anthropic_model(model_name: str) -> bool:
    # TenantModelAdapter / preflight pass "<provider_type>/<name>". Claude can
    # also be served through openai-compatible or bedrock-style providers, so
    # match the name segment too — "claude" in the model name means Anthropic
    # image pricing regardless of the route.
    head, _, tail = model_name.partition("/")
    if head.lower() == "anthropic":
        return True
    return "claude" in (tail or head).lower()


def _patch_tokens(width: int, height: int) -> int:
    return math.ceil(width / _PATCH_PX) * math.ceil(height / _PATCH_PX)


def _resized_size(
    width: int, height: int, max_edge: int, max_tokens: int
) -> tuple[int, int]:
    """The size Anthropic resizes an image to before pricing.

    The largest aspect-preserving size whose padded edges stay within
    max_edge AND whose patch cost stays within max_tokens.
    """

    def fits(w: int, h: int) -> bool:
        return (
            math.ceil(w / _PATCH_PX) * _PATCH_PX <= max_edge
            and math.ceil(h / _PATCH_PX) * _PATCH_PX <= max_edge
            and _patch_tokens(w, h) <= max_tokens
        )

    if fits(width, height):
        return (width, height)
    if height > width:
        resized_h, resized_w = _resized_size(height, width, max_edge, max_tokens)
        return (resized_w, resized_h)

    aspect_ratio = width / height
    lo, hi = 1, width  # lo always fits; hi never fits
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if fits(mid, max(round(mid / aspect_ratio), 1)):
            lo = mid
        else:
            hi = mid
    return (lo, max(round(lo / aspect_ratio), 1))


def anthropic_image_tokens(width: int, height: int, model_name: str = "") -> int:
    """Anthropic's documented image cost for the given pixel dimensions."""
    name = model_name.lower()
    if any(marker in name for marker in _HIGH_RES_MARKERS):
        max_edge, max_tokens = _HIGH_RES_MAX_EDGE, _HIGH_RES_MAX_TOKENS
    else:
        max_edge, max_tokens = _MAX_EDGE, _MAX_TOKENS
    return _patch_tokens(*_resized_size(width, height, max_edge, max_tokens))
