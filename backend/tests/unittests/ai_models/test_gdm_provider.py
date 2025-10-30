import os
from unittest.mock import patch

from intric.ai_models.litellm_providers.gdm_provider import GDMProvider


class TestGDMProvider:

    def setup_method(self):
        self.provider = GDMProvider()

    def test_get_model_prefix(self):
        assert self.provider.get_model_prefix() == "gdm/"

    def test_get_litellm_model_with_gdm_prefix(self):
        result = self.provider.get_litellm_model("gdm/multilingual-e5-large-instruct")
        assert result == "openai/multilingual-e5-large-instruct"

    def test_get_litellm_model_without_gdm_prefix(self):
        result = self.provider.get_litellm_model("some-model")
        assert result == "openai/some-model"

    def test_get_litellm_model_with_complex_name(self):
        result = self.provider.get_litellm_model("gdm/gemma3-27b-it")
        assert result == "openai/gemma3-27b-it"

    @patch.dict(os.environ, {"GDM_API_KEY": "test-key", "GDM_API_BASE": "https://test.gdm.se/api/v1"})
    def test_get_api_config_with_env_vars(self):
        config = self.provider.get_api_config()

        assert config["api_key"] == "test-key"
        assert config["api_base"] == "https://test.gdm.se/api/v1"

    @patch.dict(os.environ, {"GDM_API_KEY": "test-key"}, clear=True)
    def test_get_api_config_with_default_base(self):
        config = self.provider.get_api_config()

        assert config["api_key"] == "test-key"
        assert config["api_base"] == "https://ai.gdm.se/api/v1"

    @patch.dict(os.environ, {}, clear=True)
    def test_get_api_config_without_env_vars(self):
        config = self.provider.get_api_config()

        # Should return empty config when no env vars are set
        assert "api_key" not in config
        assert config["api_base"] == "https://ai.gdm.se/api/v1"

    def test_needs_custom_config_returns_true(self):
        assert self.provider.needs_custom_config() is True

    def test_get_env_vars(self):
        env_vars = self.provider.get_env_vars()

        assert env_vars["api_key"] == "GDM_API_KEY"
        assert env_vars["api_base"] == "GDM_API_BASE"
