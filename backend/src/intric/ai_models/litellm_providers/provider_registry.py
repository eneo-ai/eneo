from typing import Optional

from .base_provider import BaseLiteLLMProvider
from .berget_provider import BergetProvider
from .gdm_provider import GDMProvider


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

        if litellm_model_name.startswith("azure/"):
            return "azure"
        elif litellm_model_name.startswith("anthropic/"):
            return "anthropic"
        elif litellm_model_name.startswith("berget/"):
            return "berget"
        elif litellm_model_name.startswith("gdm/"):
            return "gdm"
        elif litellm_model_name.startswith("mistral/"):
            return "mistral"
        elif litellm_model_name.startswith("ovhcloud/"):
            return "ovhcloud"
        elif litellm_model_name.startswith("vllm/"):
            return "vllm"
        else:
            # Default to OpenAI for unprefixed models
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

        # Default provider for standard LiteLLM-supported providers
        return cls._default_provider