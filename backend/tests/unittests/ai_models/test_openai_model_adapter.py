from unittest.mock import patch

from intric.ai_models.completion_models.completion_model import Context, Message
from intric.completion_models.infrastructure.adapters.openai_model_adapter import (
    OpenAIModelAdapter,
)
from intric.main.config import Settings
from tests.fixtures import TEST_MODEL_GPT4

TEST_QUESTION = "I have a question"


async def test_create_query_without_session_knowledge_or_prompt():
    # Mock settings to provide OpenAI API key
    mock_settings = Settings(openai_api_key="sk-test-key-123", tenant_credentials_enabled=False)
    with patch("intric.completion_models.infrastructure.adapters.openai_model_adapter.get_settings", return_value=mock_settings):
        model_adapter = OpenAIModelAdapter(TEST_MODEL_GPT4)
        context = Context(input=TEST_QUESTION)

        expected_query = [
            {"role": "system", "content": ""},
            {"role": "user", "content": [{"type": "text", "text": TEST_QUESTION}]},
        ]

        query = model_adapter.create_query_from_context(context=context)

        assert query == expected_query


async def test_create_query_with_prompt_without_session_or_knowledge():
    # Mock settings to provide OpenAI API key
    mock_settings = Settings(openai_api_key="sk-test-key-123", tenant_credentials_enabled=False)
    with patch("intric.completion_models.infrastructure.adapters.openai_model_adapter.get_settings", return_value=mock_settings):
        model_adapter = OpenAIModelAdapter(TEST_MODEL_GPT4)
        context = Context(input=TEST_QUESTION, prompt="You are a pirate on the seven seas")

        expected_query = [
            {"role": "system", "content": context.prompt},
            {"role": "user", "content": [{"type": "text", "text": TEST_QUESTION}]},
        ]

        query = model_adapter.create_query_from_context(context=context)

        assert query == expected_query


async def test_create_query_with_session_without_knowledge():
    # Mock settings to provide OpenAI API key
    mock_settings = Settings(openai_api_key="sk-test-key-123", tenant_credentials_enabled=False)
    with patch("intric.completion_models.infrastructure.adapters.openai_model_adapter.get_settings", return_value=mock_settings):
        model_adapter = OpenAIModelAdapter(TEST_MODEL_GPT4)
        previous_questions = [
            Message(
                question=f"test_question_{i}",
                answer=f"test_answer_{i}",
            )
            for i in range(5)
        ]
        context = Context(
            input=TEST_QUESTION, prompt="You are a pirate", messages=previous_questions
        )

        messages = [
            [
                {"role": "user", "content": [{"type": "text", "text": question.question}]},
                {"role": "assistant", "content": question.answer},
            ]
            for question in previous_questions
        ]
        messages = [item for sublist in messages for item in sublist]

        expected_query = (
            [{"role": "system", "content": context.prompt}]
            + messages
            + [{"role": "user", "content": [{"type": "text", "text": TEST_QUESTION}]}]
        )

        query = model_adapter.create_query_from_context(context=context)

        assert query == expected_query
