"""Image generation as a discoverable model mode.

Image models are surfaced through the same provider discovery path as the
other model types: LiteLLM's ``image_generation`` mode maps to ``image``,
unknown names are classified by well-known fragments, per-image prices are
read from whichever cost key the provider uses, and the paid validation
probe is skipped.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from eneo.model_providers.domain import model_provider_service
from eneo.model_providers.domain.model_provider_service import (
    LITELLM_MODE_TO_OUR_MODE,
    ModelProviderService,
    per_image_cost,
)


class TestModeMapping:
    def test_image_generation_maps_to_image(self):
        assert LITELLM_MODE_TO_OUR_MODE["image_generation"] == "image"

    def test_provider_hint_recognises_image_models(self):
        assert model_provider_service._extract_mode_hint({"model_type": "image"}) == (
            "image"
        )
        assert model_provider_service._extract_mode_hint(
            {"model_type": "image_generation"}
        ) == ("image")

    @pytest.mark.parametrize(
        "name",
        [
            "gpt-image-1",
            "dall-e-3",
            "imagen-4.0-generate-001",
            "stable-diffusion-3.5",
            "sdxl-turbo",
            "FLUX.1-dev",
            "qwen-image",
        ],
    )
    def test_known_image_name_fragments_classify_as_image(self, name):
        assert model_provider_service._infer_mode_from_name(name) == "image"

    def test_speech_and_moderation_names_are_still_dropped(self):
        assert model_provider_service._infer_mode_from_name("tts-1-hd") is None
        assert (
            model_provider_service._infer_mode_from_name("omni-moderation-latest")
            is None
        )


class TestPerImageCost:
    def test_prefers_output_cost_per_image(self):
        assert per_image_cost({"output_cost_per_image": 0.04}) == 0.04

    def test_falls_back_to_input_cost_per_image(self):
        assert per_image_cost({"input_cost_per_image": 0.02}) == 0.02

    def test_token_priced_models_have_no_flat_price(self):
        assert per_image_cost({"output_cost_per_image_token": 0.00004}) is None

    def test_ignores_non_numeric_values(self):
        assert per_image_cost({"output_cost_per_image": "0.04"}) is None
        assert per_image_cost({"output_cost_per_image": True}) is None


class TestValidateModel:
    async def test_image_validation_is_skipped(self):
        service = ModelProviderService(repository=AsyncMock(), encryption=MagicMock())

        result = await service.validate_model(MagicMock(), "gpt-image-1", "image")

        assert result["success"] is True
        assert "image" in result["message"]
        service.repository.get_by_id.assert_not_awaited()
