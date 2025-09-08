
from intric.ai_models.litellm_providers.provider_registry import LiteLLMProviderRegistry
from intric.ai_models.litellm_providers.base_provider import BaseLiteLLMProvider
from intric.ai_models.litellm_providers.berget_provider import BergetProvider


class TestLiteLLMProviderRegistry:
    """Test the LiteLLM provider registry."""

    def test_berget_provider_detected_by_prefix(self):
        provider = LiteLLMProviderRegistry.get_provider_for_model(
            "berget/intfloat/multilingual-e5-large"
        )
        assert isinstance(provider, BergetProvider)

    def test_berget_provider_with_different_prefix(self):
        provider = LiteLLMProviderRegistry.get_provider_for_model(
            "berget/some-model"
        )
        assert isinstance(provider, BergetProvider)

    def test_default_provider_for_standard_models(self):
        provider = LiteLLMProviderRegistry.get_provider_for_model(
            "gpt-4"
        )
        assert isinstance(provider, BaseLiteLLMProvider)
        assert not isinstance(provider, BergetProvider)

    def test_default_provider_for_none_model_name(self):
        provider = LiteLLMProviderRegistry.get_provider_for_model(
            None
        )
        assert isinstance(provider, BaseLiteLLMProvider)
        assert not isinstance(provider, BergetProvider)

    def test_default_provider_for_empty_model_name(self):
        provider = LiteLLMProviderRegistry.get_provider_for_model(
            ""
        )
        assert isinstance(provider, BaseLiteLLMProvider)
        assert not isinstance(provider, BergetProvider)

    def test_default_provider_for_azure_model(self):
        provider = LiteLLMProviderRegistry.get_provider_for_model(
            "azure/gpt-4"
        )
        assert isinstance(provider, BaseLiteLLMProvider)
        assert not isinstance(provider, BergetProvider)

    def test_get_provider_returns_default(self):
        provider = LiteLLMProviderRegistry.get_provider()
        assert isinstance(provider, BaseLiteLLMProvider)
        assert not isinstance(provider, BergetProvider)
