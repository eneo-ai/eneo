import os
from typing import Dict, Any

from .base_provider import BaseLiteLLMProvider


class OpenRouterProvider(BaseLiteLLMProvider):
    """
    Configuration for OpenRouter API.
    OpenRouter provides access to multiple LLM providers through a single API.
    Uses standard OpenAI-compatible endpoints.
    """

    def get_model_prefix(self) -> str:
        return "openrouter/"

    def get_litellm_model(self, model_name: str) -> str:
        """Convert openrouter/model to openai/model for LiteLLM routing"""
        if model_name.startswith(self.get_model_prefix()):
            # Strip 'openrouter/' and add 'openai/' for LiteLLM routing
            actual_model = model_name.replace(self.get_model_prefix(), "")
            return f"openai/{actual_model}"
        return f"openai/{model_name}"

    def get_api_config(self) -> Dict[str, Any]:
        """Return OpenRouter API configuration"""
        api_key = os.getenv("OPENROUTER_API_KEY")
        api_base = os.getenv("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")

        config = {}
        if api_key:
            config["api_key"] = api_key
        if api_base:
            config["api_base"] = api_base

        return config

    def get_env_vars(self) -> Dict[str, str]:
        """Return required environment variable names"""
        return {
            "api_key": "OPENROUTER_API_KEY",
            "api_base": "OPENROUTER_API_BASE",
        }
