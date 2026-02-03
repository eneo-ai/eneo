import os
from typing import Dict, Any

from .base_provider import BaseLiteLLMProvider


class KlangProvider(BaseLiteLLMProvider):
    """
    Configuration for Klang.ai OpenAI-compatible API.
    Klang.ai uses custom headers for authentication:
    - X-KLANG-API-KEY
    - X-KLANG-API-SECRET
    """

    def get_model_prefix(self) -> str:
        return "klang/"

    def get_litellm_model(self, model_name: str) -> str:
        """Convert klang/model to openai/model for LiteLLM routing"""
        if model_name.startswith(self.get_model_prefix()):
            # Strip 'klang/' and add 'openai/' for LiteLLM routing
            actual_model = model_name.replace(self.get_model_prefix(), "")
            return f"openai/{actual_model}"
        return f"openai/{model_name}"

    def get_api_config(self) -> Dict[str, Any]:
        """Return Klang API configuration with custom headers"""
        api_key = os.getenv("KLANG_API_KEY")
        api_secret = os.getenv("KLANG_API_SECRET")
        api_base = os.getenv("KLANG_API_BASE", "https://api.klang.ai/api/v1")

        config = {}

        # Klang requires custom headers instead of Authorization: Bearer
        if api_key and api_secret:
            config["extra_headers"] = {
                "X-KLANG-API-KEY": api_key,
                "X-KLANG-API-SECRET": api_secret,
            }
            # Use a dummy api_key since LiteLLM requires one
            config["api_key"] = "klang-auth-via-headers"

        if api_base:
            config["api_base"] = api_base

        return config

    def get_env_vars(self) -> Dict[str, str]:
        """Return required environment variable names"""
        return {
            "api_key": "KLANG_API_KEY",
            "api_secret": "KLANG_API_SECRET",
            "api_base": "KLANG_API_BASE",
        }
