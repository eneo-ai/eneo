"""
Tests for the migration validation logic in CompletionModelMigrationService.

Covers _validate_migration_compatibility which checks:
- Deprecated target model
- Token limit reduction
- Model family mismatch
- Vision / reasoning / tool_calling capability loss
- Security classification blockers (cannot be overridden)
- kwargs_reset informational warning (always present)
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.completion_models.application.completion_model_migration_service import (
    CompletionModelMigrationService,
)
from intric.completion_models.domain.completion_model import CompletionModel
from intric.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)

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
    name: str = "test-model",
    family: str = "openai",
    max_input_tokens: int = 128_000,
    max_output_tokens: int = 4_096,
    vision: bool = False,
    reasoning: bool = False,
    supports_tool_calling: bool = False,
    is_deprecated: bool = False,
    security_classification: SecurityClassification | None = None,
    model_id=None,
) -> CompletionModel:
    """Build a minimal CompletionModel domain object for testing."""
    user = _MockUser()
    return CompletionModel(
        user=user,
        id=model_id or uuid4(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
        nickname=name,
        name=name,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        vision=vision,
        family=family,
        hosting="usa",
        org="TestOrg",
        stability="stable",
        open_source=False,
        description=None,
        nr_billion_parameters=None,
        hf_link=None,
        is_deprecated=is_deprecated,
        deployment_name=None,
        is_org_enabled=True,
        is_org_default=False,
        reasoning=reasoning,
        supports_tool_calling=supports_tool_calling,
        security_classification=security_classification,
    )


def _make_security_classification(
    *, name: str = "confidential", security_level: int = 2
) -> SecurityClassification:
    return SecurityClassification(
        tenant_id=uuid4(),
        name=name,
        security_level=security_level,
        id=uuid4(),
    )


def _build_service(
    *, repo_side_effect=None, security_spaces_count: int = 0
) -> CompletionModelMigrationService:
    """Create a service with mocked dependencies.

    ``repo_side_effect`` is a callable (or list) passed to ``AsyncMock(side_effect=...)``.
    ``security_spaces_count`` controls the scalar returned by the SQL query in
    ``_check_security_classification_compatibility``.
    """
    session = AsyncMock()

    # The security classification query returns a single scalar count
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = security_spaces_count
    session.execute.return_value = mock_result

    repo = AsyncMock()
    if repo_side_effect is not None:
        repo.one.side_effect = repo_side_effect

    usage_service = AsyncMock()

    # Patch heavy side-effect constructors that run in __init__
    with (
        patch(
            "intric.completion_models.application.completion_model_migration_service.CompletionModelMigrationHistoryRepo"
        ),
        patch(
            "intric.completion_models.application.completion_model_migration_service.get_event_publisher"
        ),
        patch(
            "intric.completion_models.application.completion_model_migration_service.get_settings"
        ),
    ):
        service = CompletionModelMigrationService(
            session=session,
            completion_model_repo=repo,
            usage_service=usage_service,
        )

    return service


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCompatibleModels:
    """Same family, same capabilities -> compatible with only kwargs_reset."""

    @pytest.mark.asyncio
    async def test_fully_compatible_returns_true(self):
        from_model = _make_model(name="gpt-4o", family="openai")
        to_model = _make_model(name="gpt-4o-mini", family="openai")

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert result.compatible is True
        assert result.requires_confirmation is False
        # Only informational kwargs_reset warning
        assert result.warning_codes == ["kwargs_reset"]


class TestTargetDeprecated:
    @pytest.mark.asyncio
    async def test_deprecated_target_yields_warning(self):
        from_model = _make_model(name="gpt-4o")
        to_model = _make_model(name="gpt-4-0613", is_deprecated=True)

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert result.compatible is False
        assert result.requires_confirmation is True
        assert "target_deprecated" in result.warning_codes
        assert "kwargs_reset" in result.warning_codes


class TestAlreadyMigratedSource:
    @pytest.mark.asyncio
    async def test_validate_migration_rejects_already_migrated_source(self):
        from_model = _make_model(name="gpt-4o")
        from_model.migrated_to_model_id = uuid4()
        to_model = _make_model(name="gpt-4o-mini")

        service = _build_service(repo_side_effect=[from_model, from_model, to_model])

        with pytest.raises(Exception) as exc_info:
            await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert "already been migrated" in str(exc_info.value)


class TestLowerTokenLimit:
    @pytest.mark.asyncio
    async def test_lower_token_limit_yields_warning(self):
        from_model = _make_model(name="big-ctx", max_input_tokens=128_000)
        to_model = _make_model(name="small-ctx", max_input_tokens=32_000)

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert result.compatible is False
        assert result.requires_confirmation is True
        assert "lower_token_limit:32000" in result.warning_codes

    @pytest.mark.asyncio
    async def test_equal_token_limit_no_warning(self):
        from_model = _make_model(max_input_tokens=128_000)
        to_model = _make_model(max_input_tokens=128_000)

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        # No token-limit warning
        assert not any(w.startswith("lower_token_limit") for w in result.warning_codes)

    @pytest.mark.asyncio
    async def test_higher_token_limit_no_warning(self):
        from_model = _make_model(max_input_tokens=32_000)
        to_model = _make_model(max_input_tokens=128_000)

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert not any(w.startswith("lower_token_limit") for w in result.warning_codes)


class TestDifferentFamily:
    @pytest.mark.asyncio
    async def test_family_mismatch_yields_warning(self):
        from_model = _make_model(name="gpt-4o", family="openai")
        to_model = _make_model(name="claude-3", family="anthropic")

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert result.compatible is False
        assert result.requires_confirmation is True
        assert "different_family:openai:anthropic" in result.warning_codes

    @pytest.mark.asyncio
    async def test_same_family_no_warning(self):
        from_model = _make_model(family="openai")
        to_model = _make_model(family="openai")

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert not any(w.startswith("different_family") for w in result.warning_codes)


class TestVisionLoss:
    @pytest.mark.asyncio
    async def test_vision_loss_yields_warning(self):
        from_model = _make_model(name="gpt-4o", vision=True)
        to_model = _make_model(name="gpt-4", vision=False)

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert result.compatible is False
        assert "lacks_vision" in result.warning_codes

    @pytest.mark.asyncio
    async def test_both_have_vision_no_warning(self):
        from_model = _make_model(vision=True)
        to_model = _make_model(vision=True)

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert "lacks_vision" not in result.warning_codes

    @pytest.mark.asyncio
    async def test_gaining_vision_no_warning(self):
        from_model = _make_model(vision=False)
        to_model = _make_model(vision=True)

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert "lacks_vision" not in result.warning_codes


class TestReasoningLoss:
    @pytest.mark.asyncio
    async def test_reasoning_loss_yields_warning(self):
        from_model = _make_model(name="o1", reasoning=True)
        to_model = _make_model(name="gpt-4o", reasoning=False)

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert result.compatible is False
        assert "lacks_reasoning" in result.warning_codes

    @pytest.mark.asyncio
    async def test_both_have_reasoning_no_warning(self):
        from_model = _make_model(reasoning=True)
        to_model = _make_model(reasoning=True)

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert "lacks_reasoning" not in result.warning_codes


class TestToolCallingLoss:
    @pytest.mark.asyncio
    async def test_tool_calling_loss_yields_warning(self):
        from_model = _make_model(supports_tool_calling=True)
        to_model = _make_model(supports_tool_calling=False)

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert result.compatible is False
        assert "lacks_tool_calling" in result.warning_codes

    @pytest.mark.asyncio
    async def test_both_support_tool_calling_no_warning(self):
        from_model = _make_model(supports_tool_calling=True)
        to_model = _make_model(supports_tool_calling=True)

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert "lacks_tool_calling" not in result.warning_codes


class TestKwargsReset:
    """kwargs_reset is always present as an informational warning."""

    @pytest.mark.asyncio
    async def test_kwargs_reset_always_present_when_compatible(self):
        from_model = _make_model()
        to_model = _make_model()

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert "kwargs_reset" in result.warning_codes

    @pytest.mark.asyncio
    async def test_kwargs_reset_present_alongside_other_warnings(self):
        from_model = _make_model(vision=True, reasoning=True, family="openai")
        to_model = _make_model(
            vision=False, reasoning=False, family="anthropic", is_deprecated=True
        )

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert "kwargs_reset" in result.warning_codes


class TestMultipleWarnings:
    @pytest.mark.asyncio
    async def test_multiple_issues_all_reported(self):
        from_model = _make_model(
            name="gpt-4o",
            family="openai",
            max_input_tokens=128_000,
            vision=True,
            reasoning=True,
            supports_tool_calling=True,
        )
        to_model = _make_model(
            name="small-model",
            family="anthropic",
            max_input_tokens=8_000,
            vision=False,
            reasoning=False,
            supports_tool_calling=False,
            is_deprecated=True,
        )

        service = _build_service(repo_side_effect=[from_model, to_model])

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert result.compatible is False
        assert result.requires_confirmation is True

        assert "target_deprecated" in result.warning_codes
        assert "lower_token_limit:8000" in result.warning_codes
        assert "different_family:openai:anthropic" in result.warning_codes
        assert "lacks_vision" in result.warning_codes
        assert "lacks_reasoning" in result.warning_codes
        assert "lacks_tool_calling" in result.warning_codes
        assert "kwargs_reset" in result.warning_codes
        # Total: 6 issues + 1 info
        assert len(result.warning_codes) == 7


class TestSecurityClassificationBlocker:
    """Security classification blockers make compatible=False and cannot be overridden."""

    @pytest.mark.asyncio
    async def test_security_blocker_makes_incompatible(self):
        sec_class = _make_security_classification(name="public", security_level=1)
        from_model = _make_model(name="high-sec-model")
        to_model = _make_model(name="low-sec-model", security_classification=sec_class)

        # 3 spaces have higher security requirement than target
        service = _build_service(
            repo_side_effect=[from_model, to_model],
            security_spaces_count=3,
        )

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert result.compatible is False
        assert result.requires_confirmation is True

        # Should have a security_classification_insufficient warning
        security_warnings = [
            w
            for w in result.warning_codes
            if w.startswith("security_classification_insufficient")
        ]
        assert len(security_warnings) == 1
        assert ":3:" in security_warnings[0]  # 3 spaces affected
        assert "public" in security_warnings[0]

    @pytest.mark.asyncio
    async def test_security_blocker_with_no_classification_on_target(self):
        """Target model without security classification gets level 0 / name 'none'."""
        from_model = _make_model(name="classified-model")
        to_model = _make_model(name="unclassified-model", security_classification=None)

        service = _build_service(
            repo_side_effect=[from_model, to_model],
            security_spaces_count=2,
        )

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert result.compatible is False
        security_warnings = [
            w
            for w in result.warning_codes
            if w.startswith("security_classification_insufficient")
        ]
        assert len(security_warnings) == 1
        assert "none" in security_warnings[0]  # no classification = "none"
        assert ":2:" in security_warnings[0]  # 2 spaces affected

    @pytest.mark.asyncio
    async def test_no_security_blocker_when_zero_affected_spaces(self):
        """When no spaces are affected by security mismatch, no blocker."""
        from_model = _make_model()
        to_model = _make_model()

        service = _build_service(
            repo_side_effect=[from_model, to_model],
            security_spaces_count=0,
        )

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        security_warnings = [
            w
            for w in result.warning_codes
            if w.startswith("security_classification_insufficient")
        ]
        assert len(security_warnings) == 0
        assert result.compatible is True

    @pytest.mark.asyncio
    async def test_security_blocker_combined_with_other_issues(self):
        """Security blocker + other issues: all appear in warnings, compatible=False."""
        sec_class = _make_security_classification(name="restricted", security_level=3)
        from_model = _make_model(
            name="premium",
            family="openai",
            vision=True,
        )
        to_model = _make_model(
            name="basic",
            family="anthropic",
            vision=False,
            is_deprecated=True,
            security_classification=sec_class,
        )

        service = _build_service(
            repo_side_effect=[from_model, to_model],
            security_spaces_count=5,
        )

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        assert result.compatible is False
        assert result.requires_confirmation is True

        # Blocker present
        assert any(
            w.startswith("security_classification_insufficient")
            for w in result.warning_codes
        )
        # Other issues also present
        assert "target_deprecated" in result.warning_codes
        assert "different_family:openai:anthropic" in result.warning_codes
        assert "lacks_vision" in result.warning_codes
        assert "kwargs_reset" in result.warning_codes

    @pytest.mark.asyncio
    async def test_blocker_warnings_come_first(self):
        """Security blockers should be placed before regular issues in the list."""
        sec_class = _make_security_classification(name="high", security_level=5)
        from_model = _make_model(vision=True)
        to_model = _make_model(
            vision=False,
            security_classification=sec_class,
        )

        service = _build_service(
            repo_side_effect=[from_model, to_model],
            security_spaces_count=1,
        )

        result = await service.validate_migration(from_model.id, to_model.id, uuid4())

        # The first warning should be the security blocker
        assert result.warning_codes[0].startswith(
            "security_classification_insufficient"
        )
