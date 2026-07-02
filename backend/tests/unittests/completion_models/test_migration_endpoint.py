"""
Tests for migration validation endpoint schemas and audit logging
for completion model migration.
"""

from uuid import uuid4


from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.category_mappings import CATEGORY_MAPPINGS
from eneo.completion_models.presentation.completion_model_models import (
    ModelMigrationRequest,
    ValidationResult,
)


class TestCompletionModelMigratedActionType:
    def test_completion_model_migrated_exists_in_action_type_enum(self):
        assert hasattr(ActionType, "COMPLETION_MODEL_MIGRATED")
        assert ActionType.COMPLETION_MODEL_MIGRATED.value == "completion_model_migrated"

    def test_completion_model_migrated_mapped_to_user_actions_category(self):
        action_value = ActionType.COMPLETION_MODEL_MIGRATED.value
        assert action_value in CATEGORY_MAPPINGS
        assert CATEGORY_MAPPINGS[action_value] == "user_actions"


class TestValidationResultSchema:
    def test_serializes_with_compatible_true(self):
        result = ValidationResult(
            compatible=True,
            warnings=[],
            requires_confirmation=False,
        )

        assert result.compatible is True
        assert result.warnings == []
        assert result.requires_confirmation is False
        assert result.user_confirmed is False

        data = result.model_dump()
        assert data == {
            "compatible": True,
            "warnings": [],
            "warning_codes": [],
            "requires_confirmation": False,
            "user_confirmed": False,
        }

    def test_serializes_with_compatible_false_and_warnings(self):
        warnings = [
            "Target model has lower context window",
            "Some assistants use features not supported by target model",
        ]
        result = ValidationResult(
            compatible=False,
            warnings=warnings,
            warning_codes=["lower_token_limit:128000", "lacks_vision"],
            requires_confirmation=True,
        )

        assert result.compatible is False
        assert result.warnings == warnings
        assert result.requires_confirmation is True
        assert result.user_confirmed is False

        data = result.model_dump()
        assert data["compatible"] is False
        assert data["warnings"] == warnings
        assert data["requires_confirmation"] is True

    def test_user_confirmed_defaults_to_false(self):
        result = ValidationResult(
            compatible=True,
            warnings=[],
            requires_confirmation=False,
        )
        assert result.user_confirmed is False

    def test_user_confirmed_can_be_set_to_true(self):
        result = ValidationResult(
            compatible=True,
            warnings=[],
            requires_confirmation=False,
            user_confirmed=True,
        )
        assert result.user_confirmed is True


class TestModelMigrationRequestSchema:
    def test_confirm_migration_accepts_boolean(self):
        request = ModelMigrationRequest(
            to_model_id=uuid4(),
            confirm_migration=True,
        )
        assert request.confirm_migration is True

    def test_confirm_migration_defaults_to_false(self):
        request = ModelMigrationRequest(
            to_model_id=uuid4(),
        )
        assert request.confirm_migration is False

    def test_entity_types_defaults_to_none(self):
        request = ModelMigrationRequest(
            to_model_id=uuid4(),
        )
        assert request.entity_types is None

    def test_entity_types_accepts_list(self):
        request = ModelMigrationRequest(
            to_model_id=uuid4(),
            entity_types=["assistant", "app"],
        )
        assert request.entity_types == ["assistant", "app"]
