"""Tests for the Anthropic-specific image pricing module.

Deletable together with anthropic_image_pricing.py if the special handling
is ever dropped.
"""

import math

from intric.tokens.anthropic_image_pricing import (
    anthropic_image_tokens,
    is_anthropic_model,
)


def test_anthropic_image_tokens_match_documented_table():
    # Reference values from Anthropic's vision docs: one token per 28x28
    # patch after resizing to fit 1568px long edge AND 1568 tokens.
    assert anthropic_image_tokens(200, 200) == 64
    assert anthropic_image_tokens(1000, 1000) == 1296
    assert anthropic_image_tokens(1092, 1092) == 1521
    assert anthropic_image_tokens(1920, 1080) == 1560  # -> 1456x819
    assert anthropic_image_tokens(2000, 1500) == 1564  # -> 1270x952
    assert anthropic_image_tokens(3840, 2160) == 1560  # -> 1456x819
    # The A4 example: token budget binds before the edge limit.
    assert anthropic_image_tokens(1075, 1520) == 1551  # -> 924x1307


def test_anthropic_image_tokens_never_exceed_per_image_cap():
    # Token-budget cap: huge images cost at most ~1568 tokens, not (w*h)-scaled.
    assert anthropic_image_tokens(2048, 1024) == 1568  # -> 1568x784
    assert anthropic_image_tokens(1536, 2048) <= 1568
    assert anthropic_image_tokens(8000, 8000) <= 1568


def test_anthropic_high_res_models_use_larger_limits():
    # Opus 4.7+ family prices at native resolution up to 2576px / 4784 tokens.
    assert anthropic_image_tokens(2048, 1024, "anthropic/claude-opus-4-8") == math.ceil(
        2048 / 28
    ) * math.ceil(1024 / 28)
    # Documented 4K example: downscaled to 2576x1449 -> 4784 tokens.
    assert anthropic_image_tokens(3840, 2160, "claude-opus-4-7") == 4784


def test_is_anthropic_model_matches_claude_behind_any_provider():
    # Claude served through openai-compatible or bedrock-style routes must
    # still get Anthropic image pricing.
    assert is_anthropic_model("anthropic/claude-3-5-haiku-20241022")
    assert is_anthropic_model("claude-3-5-sonnet")
    assert is_anthropic_model("openai/claude-3-5-sonnet")
    assert is_anthropic_model("azure/my-claude-deployment")
    assert is_anthropic_model("bedrock/anthropic.claude-v2")
    assert not is_anthropic_model("openai/gpt-4o")
    assert not is_anthropic_model("gpt-4o")
    assert not is_anthropic_model("")
