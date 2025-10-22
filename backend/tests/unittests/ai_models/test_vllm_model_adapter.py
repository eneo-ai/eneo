from unittest.mock import patch

from intric.ai_models.completion_models.completion_model import Context, Message
from intric.completion_models.infrastructure.adapters.vllm_model_adapter import (
    VLMMModelAdapter,
)
from intric.main.config import Settings
from tests.fixtures import TEST_MODEL_GPT4


def test_get_logging_details():
    # Mock settings to provide vLLM API key
    mock_settings = Settings(vllm_api_key="test-vllm-key", vllm_model_url="http://test-vllm")
    with patch("intric.completion_models.infrastructure.adapters.vllm_model_adapter.get_settings", return_value=mock_settings):
        vllm = VLMMModelAdapter(TEST_MODEL_GPT4)
        context = Context(input="I have a question", prompt="You are a pirate")

        logging_details = vllm.get_logging_details(context)

        assert isinstance(logging_details.context, str)


def test_get_logging_details_with_more_questions():
    # Mock settings to provide vLLM API key
    mock_settings = Settings(vllm_api_key="test-vllm-key", vllm_model_url="http://test-vllm")
    with patch("intric.completion_models.infrastructure.adapters.vllm_model_adapter.get_settings", return_value=mock_settings):
        vllm = VLMMModelAdapter(TEST_MODEL_GPT4)
        previous_questions = [
            Message(
                question=f"test_question_{i}",
                answer=f"test_answer_{i}",
            )
            for i in range(5)
        ]
        context = Context(
            input="I have a question",
            prompt="You are a pirate",
            messages=previous_questions,
        )

        logging_details = vllm.get_logging_details(context)

        assert isinstance(logging_details.context, str)
