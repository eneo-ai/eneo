import pytest
from unittest.mock import Mock, patch

from intric.ai_models.completion_models.completion_model import Context, Message, ModelKwargs
from intric.completion_models.infrastructure.adapters.gemini_model_adapter import (
    GeminiModelAdapter,
)
from tests.fixtures import TEST_MODEL_GEMINI_FLASH

TEST_QUESTION = "I have a question"


def test_gemini_adapter_initialization():
    """Test that GeminiModelAdapter initializes correctly with the proper base URL."""
    with patch("intric.main.config.SETTINGS") as mock_settings:
        mock_settings.gemini_api_key = "test-api-key"
        
        adapter = GeminiModelAdapter(TEST_MODEL_GEMINI_FLASH)
        
        assert adapter.model == TEST_MODEL_GEMINI_FLASH
        assert adapter.client.base_url == GeminiModelAdapter.GEMINI_BASE_URL
        assert adapter.extra_headers is None


def test_gemini_adapter_inherits_query_creation():
    """Test that GeminiModelAdapter creates queries identical to OpenAI adapter."""
    with patch("intric.main.config.SETTINGS") as mock_settings:
        mock_settings.gemini_api_key = "test-api-key"
        
        adapter = GeminiModelAdapter(TEST_MODEL_GEMINI_FLASH)
        context = Context(input=TEST_QUESTION, prompt="You are a helpful assistant")
        
        expected_query = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": [{"type": "text", "text": TEST_QUESTION}]},
        ]
        
        query = adapter.create_query_from_context(context=context)
        
        assert query == expected_query


def test_gemini_adapter_thinking_kwargs_for_flash_model():
    """Test that reasoning parameters work correctly for Gemini 2.5 Flash models."""
    with patch("intric.main.config.SETTINGS") as mock_settings:
        mock_settings.gemini_api_key = "test-api-key"
        
        adapter = GeminiModelAdapter(TEST_MODEL_GEMINI_FLASH)
        
        # Test with no model_kwargs provided
        kwargs = adapter._get_kwargs(None)
        assert kwargs == {}  # No reasoning parameters by default
        
        # Test with custom thinking_budget (legacy)
        model_kwargs = ModelKwargs(thinking_budget=1024)
        kwargs = adapter._get_kwargs(model_kwargs)
        assert kwargs.get("reasoning_effort") == "medium"  # 1024 maps to medium
        assert "thinking_budget" not in kwargs  # Internal param filtered out


def test_gemini_adapter_thinking_kwargs_for_pro_model():
    """Test that reasoning parameters work correctly for Gemini 2.5 Pro models."""
    # Create a Pro model for testing
    pro_model = TEST_MODEL_GEMINI_FLASH.model_copy()
    pro_model.name = "gemini-2.5-pro"
    
    with patch("intric.main.config.SETTINGS") as mock_settings:
        mock_settings.gemini_api_key = "test-api-key"
        
        adapter = GeminiModelAdapter(pro_model)
        
        # Test with no model_kwargs provided
        kwargs = adapter._get_kwargs(None)
        assert kwargs == {}  # No reasoning parameters by default


def test_gemini_adapter_no_thinking_for_non_reasoning_model():
    """Test that thinking_budget is not set for non-reasoning models."""
    # Create a non-reasoning model (like 2.0 Flash)
    non_reasoning_model = TEST_MODEL_GEMINI_FLASH.model_copy()
    non_reasoning_model.name = "gemini-2.0-flash"
    non_reasoning_model.reasoning = False
    
    with patch("intric.main.config.SETTINGS") as mock_settings:
        mock_settings.gemini_api_key = "test-api-key"
        
        adapter = GeminiModelAdapter(non_reasoning_model)
        
        kwargs = adapter._get_kwargs(None)
        assert kwargs == {}


def test_gemini_adapter_with_conversation_history():
    """Test that GeminiModelAdapter handles conversation history correctly."""
    with patch("intric.main.config.SETTINGS") as mock_settings:
        mock_settings.gemini_api_key = "test-api-key"
        
        adapter = GeminiModelAdapter(TEST_MODEL_GEMINI_FLASH)
        
        previous_messages = [
            Message(
                question="What is AI?",
                answer="AI stands for Artificial Intelligence.",
            ),
            Message(
                question="How does it work?", 
                answer="AI systems process data to make predictions or decisions.",
            )
        ]
        
        context = Context(
            input=TEST_QUESTION,
            prompt="You are an AI expert",
            messages=previous_messages
        )
        
        query = adapter.create_query_from_context(context=context)
        
        expected_query = [
            {"role": "system", "content": "You are an AI expert"},
            {"role": "user", "content": [{"type": "text", "text": "What is AI?"}]},
            {"role": "assistant", "content": "AI stands for Artificial Intelligence."},
            {"role": "user", "content": [{"type": "text", "text": "How does it work?"}]},
            {"role": "assistant", "content": "AI systems process data to make predictions or decisions."},
            {"role": "user", "content": [{"type": "text", "text": TEST_QUESTION}]},
        ]
        
        assert query == expected_query


def test_gemini_adapter_custom_kwargs_override():
    """Test that custom model kwargs are handled correctly."""
    with patch("intric.main.config.SETTINGS") as mock_settings:
        mock_settings.gemini_api_key = "test-api-key"
        
        adapter = GeminiModelAdapter(TEST_MODEL_GEMINI_FLASH)
        
        # Test with custom kwargs including thinking_budget=0 to disable thinking
        model_kwargs = ModelKwargs(
            thinking_budget=0,
            temperature=0.7,
            top_p=0.9
        )
        
        kwargs = adapter._get_kwargs(model_kwargs)
        
        expected_kwargs = {
            "temperature": 0.7,
            "top_p": 0.9
        }
        
        assert kwargs == expected_kwargs


def test_parameter_filtering_removes_internal_params():
    """Ensure internal params don't leak to API - CRITICAL for stability."""
    with patch("intric.main.config.SETTINGS") as mock_settings:
        mock_settings.gemini_api_key = "test-api-key"
        
        adapter = GeminiModelAdapter(TEST_MODEL_GEMINI_FLASH)
        model_kwargs = ModelKwargs(
            reasoning_level="medium",
            thinking_budget=1024,
            temperature=0.7
        )
        kwargs = adapter._get_kwargs(model_kwargs)
        
        # These should be filtered out
        assert "reasoning_level" not in kwargs
        assert "thinking_budget" not in kwargs
        # This should remain
        assert kwargs["temperature"] == 0.7
        # Reasoning effort should be added for reasoning-capable models
        assert kwargs.get("reasoning_effort") == "medium"


def test_reasoning_effort_mapping_edge_cases():
    """Test edge cases that could break in production."""
    with patch("intric.main.config.SETTINGS") as mock_settings:
        mock_settings.gemini_api_key = "test-api-key"
        
        adapter = GeminiModelAdapter(TEST_MODEL_GEMINI_FLASH)
        
        # Test with None/empty kwargs
        assert adapter._map_reasoning_level_to_effort(ModelKwargs()) == "none"
        
        # Test priority: reasoning_level over thinking_budget
        kwargs = ModelKwargs(reasoning_level="low", thinking_budget=2048)
        assert adapter._map_reasoning_level_to_effort(kwargs) == "low"
        
        # Test None reasoning_level defaults to "none"
        kwargs = ModelKwargs(reasoning_level=None)
        assert adapter._map_reasoning_level_to_effort(kwargs) == "none"


def test_non_reasoning_model_filtering():
    """Ensure non-reasoning models don't get reasoning params."""
    with patch("intric.main.config.SETTINGS") as mock_settings:
        mock_settings.gemini_api_key = "test-api-key"
        
        # Create a non-reasoning model (like 2.0 Flash)
        non_reasoning_model = TEST_MODEL_GEMINI_FLASH.model_copy()
        non_reasoning_model.name = "gemini-2.0-flash"
        adapter = GeminiModelAdapter(non_reasoning_model)
        
        kwargs = adapter._get_kwargs(ModelKwargs(reasoning_level="high"))
        assert "reasoning_effort" not in kwargs