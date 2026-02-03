from typing import Optional

from .base_provider import BaseLiteLLMProvider
from .berget_provider import BergetProvider
from .gdm_provider import GDMProvider
from .klang_provider import KlangProvider
from .openrouter_provider import OpenRouterProvider


class LiteLLMProviderRegistry:
    """
    Registry for LiteLLM provider configurations.
    Detects custom providers based on litellm_model_name prefixes.
    """
    
    _default_provider = BaseLiteLLMProvider()
    
    @classmethod
    def get_provider(cls) -> BaseLiteLLMProvider:
        """
        Get default provider configuration.
        Returns default provider for standard LiteLLM-supported providers.
        """
        return cls._default_provider
    
    @classmethod
    def detect_provider_from_model_name(cls, litellm_model_name: Optional[str]) -> str:
        """
        Detect provider from litellm model name.

        Args:
            litellm_model_name: The LiteLLM model name (e.g., 'azure/gpt-4', 'gdm/gemma3-27b-it')

        Returns:
            Provider name (azure, anthropic, berget, gdm, mistral, ovhcloud, vllm, openai)
        """
        if not litellm_model_name:
            return "openai"  # Default

        # If the model name has a "/" prefix, extract the provider from it
        # Examples: "azure/gpt-4" → "azure", "gdm/gemma3-27b-it" → "gdm"
        if "/" in litellm_model_name:
            provider = litellm_model_name.split("/")[0]
            return provider.lower()

        # Default to OpenAI for unprefixed models (e.g., "gpt-4", "gpt-3.5-turbo")
        return "openai"

    @classmethod
    def get_provider_for_model(cls, litellm_model_name: Optional[str]) -> BaseLiteLLMProvider:
        """
        Get provider by examining litellm_model_name prefix.
        This handles cases where models need custom provider configuration
        based on litellm_model_name prefix.
        """
        # Check for Berget models by litellm_model_name prefix
        if litellm_model_name and litellm_model_name.startswith("berget/"):
            return BergetProvider()

        # Check for GDM models by litellm_model_name prefix
        if litellm_model_name and litellm_model_name.startswith("gdm/"):
            return GDMProvider()

        # Check for Klang models by litellm_model_name prefix
        if litellm_model_name and litellm_model_name.startswith("klang/"):
            return KlangProvider()

        # Check for OpenRouter models by litellm_model_name prefix
        if litellm_model_name and litellm_model_name.startswith("openrouter/"):
            return OpenRouterProvider()

        # Default provider for standard LiteLLM-supported providers
        return cls._default_provider