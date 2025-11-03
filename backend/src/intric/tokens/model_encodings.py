"""
Model encoding configuration loader.

This module loads model configurations from ai_models.yml
and provides encoding mappings for tiktoken.
"""
import logging
import yaml
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Cache for model configurations
_model_configs: Optional[Dict[str, dict]] = None


def load_model_configs() -> Dict[str, dict]:
    """
    Load model configurations from ai_models.yml.

    Returns a dictionary mapping model names to their configurations.
    """
    global _model_configs

    if _model_configs is not None:
        return _model_configs

    try:
        config_path = Path(__file__).parent.parent / "server" / "dependencies" / "ai_models.yml"

        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)

        _model_configs = {}

        # Process completion models
        for model in data.get('completion_models', []):
            name = model.get('name')
            if name:
                _model_configs[name] = model
                logger.debug(f"Loaded config for model: {name}")

        logger.info(f"Loaded {len(_model_configs)} model configurations")
        return _model_configs

    except Exception as e:
        logger.error(f"Failed to load model configs: {e}")
        # Return empty dict as fallback
        _model_configs = {}
        return _model_configs


def get_encoding_for_model(model_name: str) -> str:
    """
    Get the appropriate tiktoken encoding for a model.

    Determines encoding based on model family and characteristics
    from the configuration file.
    """
    configs = load_model_configs()
    model_config = configs.get(model_name)

    if model_config:
        family = model_config.get('family', '').lower()

        # Determine encoding based on family and model characteristics
        if family == 'openai':
            # Check for specific OpenAI models
            if 'o3' in model_name.lower() or 'gpt-4o' in model_name.lower() or 'gpt-5' in model_name.lower():
                return 'o200k_base'  # Latest models
            elif 'gpt-4' in model_name.lower() or 'gpt-3.5' in model_name.lower():
                return 'cl100k_base'
            else:
                return 'p50k_base'  # Older models

        elif family == 'azure':
            # Azure models follow OpenAI patterns
            if 'gpt-5' in model_name.lower() or 'gpt-4o' in model_name.lower():
                return 'o200k_base'
            elif 'gpt-4' in model_name.lower():
                return 'cl100k_base'
            else:
                return 'p50k_base'

        elif family in ['claude', 'anthropic']:
            # Claude models use similar encoding to GPT-4
            return 'cl100k_base'

        elif family in ['mistral', 'ovhcloud']:
            # Mistral and similar models
            return 'cl100k_base'

        elif family == 'vllm':
            # Open source models - use recent encoding
            return 'cl100k_base'
        else:
            # Default to GPT-4 encoding for unknown families
            logger.debug(f"Unknown family '{family}' for model {model_name}, using cl100k_base")
            return 'cl100k_base'
    else:
        # Fallback to pattern matching if model not in config
        logger.debug(f"Model {model_name} not in config, guessing encoding")

        model_lower = model_name.lower()
        if any(x in model_lower for x in ['gpt-5', 'gpt-4o', 'o3']):
            return 'o200k_base'
        elif any(x in model_lower for x in ['gpt-4', 'gpt-3.5', 'claude']):
            return 'cl100k_base'
        elif any(x in model_lower for x in ['gpt-3', 'davinci']):
            return 'p50k_base'
        else:
            # Default to a modern encoding
            return 'cl100k_base'