"""
Simple token counting utilities for estimating token usage.

These functions provide token counting for different model families,
helping users understand their context window usage without blocking
their ability to send messages.
"""
import logging
from typing import Optional

import tiktoken
from intric.tokens.model_encodings import get_encoding_for_model as get_model_encoding_from_config

logger = logging.getLogger(__name__)


def get_model_encoding(model_name: str) -> str:
    """
    Get the appropriate encoding for a model.

    Why: Different model families use different tokenization schemes.
    We map models to their correct encoding for accurate counting.
    """
    # Try to get encoding directly from tiktoken for known models
    try:
        encoding = tiktoken.encoding_for_model(model_name)
        return encoding.name
    except KeyError:
        # Fall back to our configuration-based encoding selection
        return get_model_encoding_from_config(model_name)


def count_tokens(text: str, model_name: str) -> int:
    """
    Count tokens for text using the appropriate model encoding.

    Why: Accurate token counting helps users understand their
    context usage without surprises when hitting model limits.
    """
    if not text:
        return 0

    try:
        encoding_name = get_model_encoding(model_name)
        encoding = tiktoken.get_encoding(encoding_name)
        tokens = len(encoding.encode(text))

        # Only log in debug mode to avoid spamming logs
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Counted {tokens} tokens for {len(text)} chars using {encoding_name} "
                f"(model: {model_name}, ratio: {len(text)/tokens:.2f} chars/token)"
            )
        return tokens

    except Exception as e:
        # If token counting fails, return a reasonable estimate
        # rather than breaking the user experience
        logger.error(f"Token counting failed for model {model_name}: {e}")
        estimated = len(text) // 4  # Fallback approximation
        logger.debug(f"Using fallback estimate: {estimated} tokens for {len(text)} chars")
        return estimated


def estimate_file_tokens(file_text: str, model_name: str) -> int:
    """
    Estimate token count for a file's extracted text.

    Why: Files need accurate token counting at upload time
    so users can immediately see their context usage.
    """
    return count_tokens(file_text, model_name)


def count_assistant_prompt_tokens(prompt: Optional[str], model_name: str) -> int:
    """
    Count tokens in an assistant's prompt.

    Why: Prompts consume context that users need to account for
    when adding files and composing messages.
    """
    if not prompt:
        return 0

    return count_tokens(prompt, model_name)