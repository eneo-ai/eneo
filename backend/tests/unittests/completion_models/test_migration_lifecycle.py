"""
Tests for the model lifecycle changes introduced to preserve historical
question attribution during and after model migration.

Core invariants:
- Questions must NOT be migrated (they are historical records)
- Migrated models must have migrated_to_model_id set
- Migrated models return can_access = False
- MIGRATABLE_ENTITY_TYPES must not include 'questions'
"""

from datetime import datetime
from uuid import uuid4


from eneo.completion_models.constants import (
    ENTITY_TABLE_MAP,
    MIGRATABLE_ENTITY_TYPES,
)
from eneo.completion_models.domain.completion_model import CompletionModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _MockUser:
    def __init__(self):
        self.id = uuid4()
        self.tenant_id = uuid4()
        self.tenant = None
        self.modules = []


def _make_model(
    *,
    is_deprecated: bool = False,
    is_org_enabled: bool = True,
    migrated_to_model_id=None,
    deleted_at=None,
) -> CompletionModel:
    user = _MockUser()
    return CompletionModel(
        user=user,
        id=uuid4(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
        nickname="test-model",
        name="test-model",
        max_input_tokens=128_000,
        max_output_tokens=4_096,
        vision=False,
        family="openai",
        hosting="usa",
        org="TestOrg",
        stability="stable",
        open_source=False,
        description=None,
        nr_billion_parameters=None,
        hf_link=None,
        is_deprecated=is_deprecated,
        deployment_name=None,
        is_org_enabled=is_org_enabled,
        is_org_default=False,
        reasoning=False,
        migrated_to_model_id=migrated_to_model_id,
        deleted_at=deleted_at,
    )


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestMigratableEntityTypes:
    """Questions must be excluded from the migratable entity types list."""

    def test_questions_not_in_migratable_types(self):
        assert "questions" not in MIGRATABLE_ENTITY_TYPES

    def test_questions_still_in_entity_table_map(self):
        """Questions must remain in ENTITY_TABLE_MAP for usage counting."""
        assert "questions" in ENTITY_TABLE_MAP

    def test_active_entity_types_are_migratable(self):
        for entity_type in ["assistants", "apps", "services", "spaces"]:
            assert entity_type in MIGRATABLE_ENTITY_TYPES

    def test_templates_are_migratable(self):
        for entity_type in ["assistant_templates", "app_templates"]:
            assert entity_type in MIGRATABLE_ENTITY_TYPES


# ---------------------------------------------------------------------------
# Domain model can_access tests
# ---------------------------------------------------------------------------


class TestMigratedModelCanAccess:
    """Migrated models must return can_access = False."""

    def test_active_model_can_access(self):
        model = _make_model()
        assert model.can_access is True

    def test_migrated_model_cannot_access(self):
        model = _make_model(migrated_to_model_id=uuid4())
        assert model.can_access is False

    def test_migrated_and_deprecated_cannot_access(self):
        model = _make_model(
            is_deprecated=True,
            migrated_to_model_id=uuid4(),
        )
        assert model.can_access is False

    def test_migrated_but_enabled_cannot_access(self):
        """Even if is_org_enabled is True, migration blocks access."""
        model = _make_model(
            is_org_enabled=True,
            migrated_to_model_id=uuid4(),
        )
        assert model.can_access is False

    def test_disabled_model_cannot_access(self):
        model = _make_model(is_org_enabled=False)
        assert model.can_access is False

    def test_deprecated_model_cannot_access(self):
        model = _make_model(is_deprecated=True)
        assert model.can_access is False

    def test_soft_deleted_model_cannot_access(self):
        model = _make_model(deleted_at=datetime.now())
        assert model.can_access is False


# ---------------------------------------------------------------------------
# Pydantic model propagation tests
# ---------------------------------------------------------------------------


class TestPydanticModelMigrationField:
    """migrated_to_model_id must propagate through the pydantic model chain."""

    def test_internal_model_dump_includes_migrated_to_model_id(self):
        from eneo.ai_models.completion_models.completion_model import (
            CompletionModel as CompletionModelAPIModel,
        )

        target_id = uuid4()
        model = CompletionModelAPIModel(
            id=uuid4(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            name="test-model",
            nickname="test-model",
            family="openai",
            max_input_tokens=128_000,
            max_output_tokens=4_096,
            is_deprecated=False,
            vision=False,
            reasoning=False,
            is_org_enabled=True,
            is_org_default=False,
            migrated_to_model_id=target_id,
        )

        assert model.model_dump()["migrated_to_model_id"] == target_id

    def test_from_domain_propagates_migrated_to_model_id(self):
        from eneo.ai_models.completion_models.completion_model import (
            CompletionModelPublic,
        )

        target_id = uuid4()
        model = _make_model(migrated_to_model_id=target_id)

        public = CompletionModelPublic.from_domain(model)

        assert public.migrated_to_model_id == target_id
        assert public.can_access is False

    def test_from_domain_none_when_not_migrated(self):
        from eneo.ai_models.completion_models.completion_model import (
            CompletionModelPublic,
        )

        model = _make_model()

        public = CompletionModelPublic.from_domain(model)

        assert public.migrated_to_model_id is None
        assert public.can_access is True


# ---------------------------------------------------------------------------
# AIModelsService._can_access tests
# ---------------------------------------------------------------------------


class TestAIModelsServiceCanAccess:
    """The duplicate _can_access in AIModelsService must also exclude migrated."""

    def test_can_access_excludes_migrated(self):
        from unittest.mock import MagicMock
        from eneo.ai_models.ai_models_service import AIModelsService

        service = AIModelsService.__new__(AIModelsService)

        model = MagicMock()
        model.is_deprecated = False
        model.is_org_enabled = True
        model.migrated_to_model_id = uuid4()

        assert service._can_access(model) is False

    def test_can_access_allows_normal_model(self):
        from unittest.mock import MagicMock
        from eneo.ai_models.ai_models_service import AIModelsService

        service = AIModelsService.__new__(AIModelsService)

        model = MagicMock()
        model.is_deprecated = False
        model.is_org_enabled = True
        model.migrated_to_model_id = None

        assert service._can_access(model) is True
