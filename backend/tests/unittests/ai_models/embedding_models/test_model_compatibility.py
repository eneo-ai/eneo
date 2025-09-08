from intric.embedding_models.domain.model_compatibility import ModelCompatibility


class TestModelCompatibility:
    def test_get_model_identifier_for_existing_model(self):
        identifier = ModelCompatibility.get_model_identifier("multilingual-e5-large")
        assert identifier == "multilingual-e5-large"

    def test_get_model_identifier_for_berget_variant(self):
        identifier = ModelCompatibility.get_model_identifier("multilingual-e5-large-berget")
        assert identifier == "multilingual-e5-large"

    def test_get_model_identifier_for_unknown_model(self):
        identifier = ModelCompatibility.get_model_identifier("unknown-model")
        assert identifier == "unknown-model"

    def test_are_models_compatible_same_family(self):
        assert ModelCompatibility.are_models_compatible(
            "multilingual-e5-large",
            "multilingual-e5-large-berget"
        ) is True

    def test_are_models_compatible_reversed_order(self):
        assert ModelCompatibility.are_models_compatible(
            "multilingual-e5-large-berget",
            "multilingual-e5-large"
        ) is True

    def test_are_models_compatible_same_model(self):
        assert ModelCompatibility.are_models_compatible(
            "multilingual-e5-large",
            "multilingual-e5-large"
        ) is True

    def test_are_models_incompatible(self):
        assert ModelCompatibility.are_models_compatible(
            "multilingual-e5-large",
            "unknown-model"
        ) is False

    def test_are_models_incompatible_with_unknown_models(self):
        assert ModelCompatibility.are_models_compatible(
            "unknown-model-1",
            "unknown-model-2"
        ) is False

    def test_get_compatible_models_for_existing_model(self):
        compatible = ModelCompatibility.get_compatible_models("multilingual-e5-large")

        assert "multilingual-e5-large" in compatible
        assert "multilingual-e5-large-berget" in compatible
        assert len(compatible) == 2

    def test_get_compatible_models_for_berget_variant(self):
        compatible = ModelCompatibility.get_compatible_models("multilingual-e5-large-berget")

        assert "multilingual-e5-large" in compatible
        assert "multilingual-e5-large-berget" in compatible
        assert len(compatible) == 2

    def test_get_compatible_models_for_unknown_model(self):
        compatible = ModelCompatibility.get_compatible_models("unknown-model")

        assert compatible == ["unknown-model"]
        assert len(compatible) == 1

    def test_compatibility_map_structure(self):
        compat_map = ModelCompatibility.COMPATIBLE_MODELS

        # Should have at least the multilingual-e5-large family
        assert "multilingual-e5-large" in compat_map

        # Each entry should be a list
        for key, value in compat_map.items():
            assert isinstance(value, list)
            # The key should be in its own compatibility list
            assert key in value
