import os
from unittest.mock import patch

from intric.ai_models.litellm_providers.berget_provider import BergetProvider


class TestBergetProvider:

    def setup_method(self):
        self.provider = BergetProvider()

    def test_get_model_prefix(self):
        assert self.provider.get_model_prefix() == "berget/"

    def test_get_litellm_model_with_berget_prefix(self):
        result = self.provider.get_litellm_model("berget/intfloat/multilingual-e5-large")
        assert result == "openai/intfloat/multilingual-e5-large"

    def test_get_litellm_model_without_berget_prefix(self):
        result = self.provider.get_litellm_model("some-model")
        assert result == "openai/some-model"

    def test_get_litellm_model_with_complex_name(self):
        result = self.provider.get_litellm_model("berget/vendor/model-name-v2")
        assert result == "openai/vendor/model-name-v2"

    @patch.dict(os.environ, {"BERGET_API_KEY": "test-key", "BERGET_API_BASE": "https://test.api.com/v1"})
    def test_get_api_config_with_env_vars(self):
        config = self.provider.get_api_config()

        assert config["api_key"] == "test-key"
        assert config["api_base"] == "https://test.api.com/v1"

    @patch.dict(os.environ, {"BERGET_API_KEY": "test-key"}, clear=True)
    def test_get_api_config_with_default_base(self):
        config = self.provider.get_api_config()

        assert config["api_key"] == "test-key"
        assert config["api_base"] == "https://api.berget.ai/v1"

    @patch.dict(os.environ, {}, clear=True)
    def test_get_api_config_without_env_vars(self):
        config = self.provider.get_api_config()

        # Should return empty config when no env vars are set
        assert "api_key" not in config
        assert config["api_base"] == "https://api.berget.ai/v1"

    def test_needs_custom_config_returns_true(self):
        assert self.provider.needs_custom_config() is True

    def test_get_env_vars(self):
        env_vars = self.provider.get_env_vars()

        assert env_vars["api_key"] == "BERGET_API_KEY"
        assert env_vars["api_base"] == "BERGET_API_BASE"
