import os
from typing import Dict, Any

from .base_provider import BaseLiteLLMProvider


class BergetProvider(BaseLiteLLMProvider):
    """
    Configuration for Berget.ai OpenAI-compatible API.
    Since Berget is not natively supported by LiteLLM, 
    we route it through OpenAI-compatible endpoints.
    """
    
    def get_model_prefix(self) -> str:
        return "berget/"
    
    def get_litellm_model(self, model_name: str) -> str:
        """Convert berget/model to openai/model for LiteLLM routing"""
        if model_name.startswith(self.get_model_prefix()):
            # Strip 'berget/' and add 'openai/' for LiteLLM routing
            # berget/intfloat/multilingual-e5-large → openai/intfloat/multilingual-e5-large
            actual_model = model_name.replace(self.get_model_prefix(), "")
            return f"openai/{actual_model}"
        return f"openai/{model_name}"
    
    def get_api_config(self) -> Dict[str, Any]:
        """Return Berget API configuration"""
        api_key = os.getenv("BERGET_API_KEY")
        api_base = os.getenv("BERGET_API_BASE", "https://api.berget.ai/v1")
        
        config = {}
        if api_key:
            config["api_key"] = api_key
        if api_base:
            config["api_base"] = api_base
            
        return config
    
    def get_env_vars(self) -> Dict[str, str]:
        """Return required environment variable names"""
        return {
            "api_key": "BERGET_API_KEY",
            "api_base": "BERGET_API_BASE",
        }