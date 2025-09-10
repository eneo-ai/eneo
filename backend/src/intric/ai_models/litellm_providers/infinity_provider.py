import os
from typing import Dict, Any

from .base_provider import BaseLiteLLMProvider


class InfinityProvider(BaseLiteLLMProvider):
    """
    Configuration for Infinity embedding server.
    Routes infinity/ models to use OpenAI-compatible endpoints with custom base URL.
    """

    def get_model_prefix(self) -> str:
        return "infinity/"

    def get_litellm_model(self, model_name: str) -> str:
        """Convert infinity/model to openai/model for LiteLLM routing"""
        return f"{model_name}"

    def get_api_config(self) -> Dict[str, Any]:
        """Return Infinity API configuration"""
        api_base = os.getenv("INFINITY_API_BASE")

        config = {}
        if api_base:
            config["api_base"] = api_base

        return config

    def get_env_vars(self) -> Dict[str, str]:
        """Return required environment variable names"""
        return {
            "api_base": "INFINITY_API_BASE",
        }
