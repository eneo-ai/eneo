from unittest.mock import patch

from eneo.model_providers.domain.model_defaults import lookup_model_defaults
from eneo.model_providers.presentation.model_provider_router import get_model_defaults


def test_lookup_model_defaults_exact_match():
    with patch(
        "eneo.model_providers.domain.model_defaults._get_model_cost",
        {
            "gpt-5.4": {
                "max_input_tokens": 1_050_000,
                "max_output_tokens": 128_000,
                "supports_vision": True,
                "supports_function_calling": True,
                "supports_reasoning": True,
            }
        },
    ):
        defaults = lookup_model_defaults("gpt-5.4")

    assert defaults is not None
    assert defaults.max_input_tokens == 1_050_000
    assert defaults.max_output_tokens == 128_000
    assert defaults.supports_reasoning is True


def test_lookup_model_defaults_prefixed_match():
    with patch(
        "eneo.model_providers.domain.model_defaults._get_model_cost",
        {
            "azure/gpt-4o": {
                "max_input_tokens": 128_000,
                "max_output_tokens": 16_384,
                "supports_vision": True,
                "supports_function_calling": True,
                "supports_reasoning": False,
            }
        },
    ):
        defaults = lookup_model_defaults("gpt-4o")

    assert defaults is not None
    assert defaults.max_input_tokens == 128_000
    assert defaults.max_output_tokens == 16_384


async def test_get_model_defaults_endpoint_returns_found_payload():
    with patch(
        "eneo.model_providers.domain.model_defaults._get_model_cost",
        {
            "gpt-5.2": {
                "max_input_tokens": 272_000,
                "max_output_tokens": 128_000,
                "supports_vision": False,
                "supports_function_calling": True,
                "supports_reasoning": True,
            }
        },
    ):
        result = await get_model_defaults(model_name="gpt-5.2")

    assert result == {
        "found": True,
        "max_input_tokens": 272_000,
        "max_output_tokens": 128_000,
        "supports_vision": False,
        "supports_function_calling": True,
        "supports_reasoning": True,
    }
