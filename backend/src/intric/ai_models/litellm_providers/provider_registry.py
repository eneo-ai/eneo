from typing import Optional

from .base_provider import BaseLiteLLMProvider
from .berget_provider import BergetProvider
from .infinity_provider import InfinityProvider


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
    def get_provider_for_model(cls, litellm_model_name: Optional[str]) -> BaseLiteLLMProvider:
        """
        Get provider by examining litellm_model_name prefix.
        This handles cases where models need custom provider configuration
        based on litellm_model_name prefix.
        """
        # Check for Berget models by litellm_model_name prefix
        if litellm_model_name and litellm_model_name.startswith("berget/"):
            return BergetProvider()
        
        # Check for Infinity models by litellm_model_name prefix
        if litellm_model_name and litellm_model_name.startswith("infinity/"):
            return InfinityProvider()
        
        # Default provider for standard LiteLLM-supported providers
        return cls._default_provider