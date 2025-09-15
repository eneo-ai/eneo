from typing import Dict, Any


class BaseLiteLLMProvider:
    """
    Base provider that handles standard LiteLLM-supported providers.
    Only override methods if you need custom behavior.
    """
    
    def get_model_prefix(self) -> str:
        """
        Return the prefix for this provider.
        Default: returns empty string (no prefix modification needed)
        """
        return ""
    
    def get_litellm_model(self, model_name: str) -> str:
        """
        Convert provider model name to LiteLLM format.
        Default: returns the model name as-is (for natively supported providers)
        """
        return model_name
    
    def get_api_config(self) -> Dict[str, Any]:
        """
        Return API configuration (base URL, headers, etc.)
        Default: empty dict (LiteLLM handles it automatically)
        """
        return {}
    
    def get_env_vars(self) -> Dict[str, str]:
        """
        Return required environment variable names.
        Default: empty dict
        """
        return {}
    
    def needs_custom_config(self) -> bool:
        """
        Check if this provider needs custom configuration.
        Default: False (for standard LiteLLM providers)
        """
        return bool(self.get_api_config() or self.get_model_prefix())