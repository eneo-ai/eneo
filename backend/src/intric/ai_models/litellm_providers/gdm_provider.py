import os
from typing import Dict, Any

from .base_provider import BaseLiteLLMProvider


class GDMProvider(BaseLiteLLMProvider):
    """
    Configuration for GDM (Swedish AI provider at ai.gdm.se).
    Since GDM is not natively supported by LiteLLM,
    we route it through OpenAI-compatible endpoints.
    """

    def get_model_prefix(self) -> str:
        return "gdm/"

    def get_litellm_model(self, model_name: str) -> str:
        """Convert gdm/model to openai/model for LiteLLM routing"""
        if model_name.startswith(self.get_model_prefix()):
            # Strip 'gdm/' and add 'openai/' for LiteLLM routing
            # gdm/multilingual-e5-large-instruct → openai/multilingual-e5-large-instruct
            actual_model = model_name.replace(self.get_model_prefix(), "")
            return f"openai/{actual_model}"
        return f"openai/{model_name}"

    def get_api_config(self) -> Dict[str, Any]:
        """Return GDM API configuration"""
        api_key = os.getenv("GDM_API_KEY")
        api_base = os.getenv("GDM_API_BASE", "https://ai.gdm.se/api/v1")

        config = {}
        if api_key:
            config["api_key"] = api_key
        if api_base:
            config["api_base"] = api_base

        return config

    def get_env_vars(self) -> Dict[str, str]:
        """Return required environment variable names"""
        return {
            "api_key": "GDM_API_KEY",
            "api_base": "GDM_API_BASE",
        }
