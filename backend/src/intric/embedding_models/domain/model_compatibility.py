from typing import Dict, List


class ModelCompatibility:
    """
    Handle cross-provider model compatibility for embedding models.
    This allows collections created with one provider to work with
    the same model from a different provider.
    """

    # Map of compatible models across providers
    # Key: canonical identifier, Value: list of compatible model names
    COMPATIBLE_MODELS: Dict[str, List[str]] = {
        "multilingual-e5-large": [
            "multilingual-e5-large",
            "multilingual-e5-large-berget",
        ],
        "text-embedding-3-small": [
            "text-embedding-3-small",
            "text-embedding-3-small-berget",
        ],
        "text-embedding-3-large": [
            "text-embedding-3-large",
            "text-embedding-3-large-azure",
            "text-embedding-3-large-berget",
        ],
        "text-embedding-ada-002": [
            "text-embedding-ada-002",
        ],
    }

    @classmethod
    def get_model_identifier(cls, model_name: str) -> str:
        """
        Get the canonical identifier for a model.

        Args:
            model_name: The name of the model (e.g., "multilingual-e5-large-berget")

        Returns:
            The canonical identifier (e.g., "multilingual-e5-large")
        """
        for identifier, variants in cls.COMPATIBLE_MODELS.items():
            if model_name in variants:
                return identifier
        # If not found in compatibility map, use the model name as identifier
        return model_name

    @classmethod
    def are_models_compatible(cls, model1: str, model2: str) -> bool:
        """
        Check if two models are compatible (can be used interchangeably).

        Args:
            model1: First model name
            model2: Second model name

        Returns:
            True if models are compatible, False otherwise
        """
        return cls.get_model_identifier(model1) == cls.get_model_identifier(model2)

    @classmethod
    def get_compatible_models(cls, model_name: str) -> List[str]:
        """
        Get all models compatible with the given model.

        Args:
            model_name: The model to find compatible models for

        Returns:
            List of compatible model names (including the original)
        """
        identifier = cls.get_model_identifier(model_name)
        return cls.COMPATIBLE_MODELS.get(identifier, [model_name])
