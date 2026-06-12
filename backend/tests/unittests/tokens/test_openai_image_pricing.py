"""Tests for the OpenAI-specific image pricing module.

Deletable together with openai_image_pricing.py if the special handling
is ever dropped.
"""

from intric.tokens.openai_image_pricing import openai_image_tokens


def test_default_tile_formula_for_gpt4o_family():
    # Fit in 2048², short side scaled to 768, 85 base + 170 per 512px tile.
    assert openai_image_tokens(512, 512, "openai/gpt-4o") == 85 + 170  # 1 tile
    assert openai_image_tokens(2048, 1024, "gpt-4.1") == 1105  # -> 1536x768, 3x2
    assert openai_image_tokens(4096, 4096) == 85 + 170 * 4  # -> 768x768, 2x2


def test_tile_costs_vary_by_model_family():
    # Same geometry (6 tiles for 2048x1024), different per-model constants.
    assert openai_image_tokens(2048, 1024, "gpt-4o-mini") == 2833 + 6 * 5667
    assert openai_image_tokens(2048, 1024, "azure/o3") == 75 + 6 * 150
    assert openai_image_tokens(2048, 1024, "openai/gpt-5") == 70 + 6 * 140


def test_patch_based_models_use_multiplier():
    # 1024x1024 -> 32x32 = 1024 patches, within the 1536 budget.
    assert openai_image_tokens(1024, 1024, "gpt-4.1-mini") == 1659  # 1024*1.62
    # gpt-5-mini must match the patch table, not the tile-based "gpt-5".
    assert openai_image_tokens(1024, 1024, "azure/gpt-5-mini") == 1659
    assert openai_image_tokens(1024, 1024, "gpt-4.1-nano") == 2520  # 1024*2.46
    assert openai_image_tokens(1024, 1024, "o4-mini") == 1762  # 1024*1.72


def test_gpt54_snapshot_uses_2500_patch_budget():
    # A rendered A4 PDF page at 2048px long edge is patch-priced by GPT-5.4.
    # The old broad "gpt-5" match incorrectly tile-priced this as 910 tokens.
    assert openai_image_tokens(1448, 2048, "openai/gpt-5.4-2026-03-05") == 2478
    assert openai_image_tokens(8000, 8000, "gpt-5.4") == 2500


def test_patch_budget_caps_large_images():
    # A rendered A4 page at 2048px long edge: 46x64 = 2944 raw patches, scaled
    # down to fit the 1536-patch budget -> 32x46 = 1472 patches.
    assert openai_image_tokens(1448, 2048, "gpt-4.1-mini") == 2385  # 1472*1.62
    # The cap holds regardless of input size.
    assert openai_image_tokens(8000, 8000, "gpt-4.1-mini") <= 2489  # 1536*1.62
