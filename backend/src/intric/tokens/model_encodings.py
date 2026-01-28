"""
Model encoding configuration for tiktoken.

This module provides encoding mappings for tiktoken based on model name patterns.
Encodings are determined by analyzing the model name to identify the model family.
"""
import logging

logger = logging.getLogger(__name__)


def get_encoding_for_model(model_name: str) -> str:
    """
    Get the appropriate tiktoken encoding for a model.

    Determines encoding based on model name patterns.
    """
    if not model_name:
        return 'cl100k_base'

    model_lower = model_name.lower()

    # OpenAI latest models (GPT-4o, GPT-5, o3, o1)
    if any(x in model_lower for x in ['gpt-5', 'gpt-4o', 'o3-', 'o1-', '-o3', '-o1']):
        return 'o200k_base'

    # OpenAI GPT-4 and GPT-3.5 models
    if any(x in model_lower for x in ['gpt-4', 'gpt-3.5']):
        return 'cl100k_base'

    # Claude models (Anthropic)
    if 'claude' in model_lower:
        return 'cl100k_base'

    # Mistral models
    if 'mistral' in model_lower:
        return 'cl100k_base'

    # Older OpenAI models
    if any(x in model_lower for x in ['gpt-3', 'davinci', 'curie', 'babbage', 'ada']):
        return 'p50k_base'

    # Default to cl100k_base for modern models
    logger.debug(f"Unknown model {model_name}, using cl100k_base encoding")
    return 'cl100k_base'
