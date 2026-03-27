"""
Token counting utilities using litellm for accurate per-model tokenization.

Uses litellm.token_counter() which automatically selects the correct
tokenizer for each model (Anthropic, OpenAI, HuggingFace, etc.).
"""
import logging
from typing import Optional

import litellm

logger = logging.getLogger(__name__)


def count_tokens(text: str, model_name: str = "") -> int:
    """Count tokens for text using litellm's model-aware tokenizer."""
    if not text:
        return 0

    try:
        return litellm.token_counter(model=model_name, text=text)
    except Exception as e:
        logger.error(f"Token counting failed for model {model_name}: {e}")
        return len(text) // 4


def count_assistant_prompt_tokens(prompt: Optional[str], model_name: str) -> int:
    """Count tokens in an assistant's prompt."""
    if not prompt:
        return 0

    return count_tokens(prompt, model_name)
