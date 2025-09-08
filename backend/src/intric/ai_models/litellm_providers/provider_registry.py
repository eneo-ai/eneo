from typing import Optional

from intric.ai_models.model_enums import ModelFamily

from .base_provider import BaseLiteLLMProvider
from .berget_provider import BergetProvider


class LiteLLMProviderRegistry:
    """
    Registry for LiteLLM provider configurations.
    Detects custom providers based on litellm_model_name prefixes.
    """
    
    _default_provider = BaseLiteLLMProvider()
    
    @classmethod
    def get_provider(cls, family: ModelFamily) -> BaseLiteLLMProvider:
        """
        Get provider configuration by family.
        Returns default provider for standard LiteLLM-supported providers.
        """
        return cls._default_provider
    
    @classmethod
    def get_provider_for_model(cls, family: ModelFamily, litellm_model_name: Optional[str]) -> BaseLiteLLMProvider:
        """
        Get provider by examining litellm_model_name prefix.
        This handles cases where models use standard families (e.g., 'openai', 'e5')
        but need custom provider configuration based on litellm_model_name prefix.
        """
        # Check for Berget models by litellm_model_name prefix
        if litellm_model_name and litellm_model_name.startswith("berget/"):
            return BergetProvider()
        
        # Default provider for standard LiteLLM-supported providers
        return cls._default_provider