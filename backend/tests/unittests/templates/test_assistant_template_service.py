"""Unit tests for AssistantTemplateService tenant-scoped methods."""

import pytest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
from datetime import datetime, timezone

from intric.templates.assistant_template.assistant_template_service import (
    AssistantTemplateService,
)
from intric.templates.assistant_template.assistant_template import AssistantTemplate
from intric.templates.assistant_template.api.assistant_template_models import (
    AssistantTemplateCreate,
    AssistantTemplateUpdate,
    AssistantTemplateWizard,
)
from intric.main.exceptions import (
    NotFoundException,
    BadRequestException,
    NameCollisionException,
)


@pytest.fixture
def mock_repo():
    """Mock repository."""
    return AsyncMock()


@pytest.fixture
def mock_factory():
    """Mock factory."""
    return Mock()


@pytest.fixture
def mock_feature_flag_service():
    """Mock feature flag service."""
    return AsyncMock()


@pytest.fixture
def mock_session():
    """Mock database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock()
    return session


@pytest.fixture
def service(mock_repo, mock_factory, mock_feature_flag_service, mock_session):
    """Service instance with mocked dependencies."""
    return AssistantTemplateService(
        repo=mock_repo,
        factory=mock_factory,
        feature_flag_service=mock_feature_flag_service,
        session=mock_session,
    )


@pytest.mark.asyncio
async def test_get_templates_returns_empty_when_feature_disabled(service, mock_feature_flag_service, mock_repo):
    """When feature flag is disabled, returns empty list."""
    tenant_id = uuid4()

    # Feature flag returns False
    mock_feature_flag_service.check_is_feature_enabled.return_value = False

    result = await service.get_assistant_templates(tenant_id=tenant_id)

    assert result == []
    mock_feature_flag_service.check_is_feature_enabled.assert_called_once_with(
        feature_name="using_templates",
        tenant_id=tenant_id
    )
    # Should not call repo when feature disabled
    mock_repo.get_assistant_template_list.assert_not_called()


@pytest.mark.asyncio
async def test_get_templates_returns_list_when_feature_enabled(service, mock_feature_flag_service, mock_repo):
    """When feature flag is enabled, returns templates from repo."""
    tenant_id = uuid4()
    mock_templates = [Mock(), Mock()]

    mock_feature_flag_service.check_is_feature_enabled.return_value = True
    mock_repo.get_assistant_template_list.return_value = mock_templates

    result = await service.get_assistant_templates(tenant_id=tenant_id)

    assert result == mock_templates
    mock_repo.get_assistant_template_list.assert_called_once_with(tenant_id=tenant_id)


@pytest.mark.asyncio
async def test_create_template_requires_feature_flag_enabled(service, mock_feature_flag_service):
    """Cannot create template when feature flag is disabled."""
    tenant_id = uuid4()
    mock_feature_flag_service.check_is_feature_enabled.return_value = False

    data = AssistantTemplateCreate(
        name="Test",
        description="Test",
        category="Test",
        prompt="Test",
        wizard=AssistantTemplateWizard(
            attachments=None,
            collections=None
        )
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.create_template(data=data, tenant_id=tenant_id)

    assert "not enabled" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_create_template_checks_duplicate_name(service, mock_feature_flag_service, mock_repo):
    """Raises error when template name already exists in tenant."""
    tenant_id = uuid4()

    mock_feature_flag_service.check_is_feature_enabled.return_value = True
    mock_repo.check_duplicate_name.return_value = True  # Duplicate exists

    data = AssistantTemplateCreate(
        name="Duplicate Name",
        description="Test",
        category="Test",
        prompt="Test",
        wizard=AssistantTemplateWizard(
            attachments=None,
            collections=None
        )
    )

    with pytest.raises(NameCollisionException) as exc_info:
        await service.create_template(data=data, tenant_id=tenant_id)

    assert "already exists" in str(exc_info.value).lower()
    mock_repo.check_duplicate_name.assert_called_once_with(
        name="Duplicate Name",
        tenant_id=tenant_id
    )


@pytest.mark.asyncio
async def test_update_template_validates_ownership(service, mock_repo):
    """Cannot update template that doesn't belong to tenant."""
    template_id = uuid4()
    tenant_id = uuid4()

    # Template not found for this tenant
    mock_repo.get_by_id.return_value = None

    data = AssistantTemplateUpdate(name="Updated Name")

    with pytest.raises(NotFoundException) as exc_info:
        await service.update_template(
            template_id=template_id,
            data=data,
            tenant_id=tenant_id
        )

    assert "does not belong" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_update_template_checks_duplicate_on_rename(service, mock_repo):
    """When renaming, checks if new name already exists."""
    template_id = uuid4()
    tenant_id = uuid4()

    # Existing template
    existing_template = Mock()
    existing_template.name = "Old Name"
    mock_repo.get_by_id.return_value = existing_template

    # Duplicate check returns True
    mock_repo.check_duplicate_name.return_value = True

    data = AssistantTemplateUpdate(name="New Name")

    with pytest.raises(NameCollisionException):
        await service.update_template(
            template_id=template_id,
            data=data,
            tenant_id=tenant_id
        )


@pytest.mark.asyncio
async def test_delete_template_checks_usage(service, mock_repo, mock_session):
    """Cannot delete template that is in use by assistants."""
    template_id = uuid4()
    tenant_id = uuid4()

    # Template exists
    mock_template = Mock()
    mock_template.name = "In Use Template"
    mock_repo.get_by_id.return_value = mock_template

    # Template is in use (count > 0)
    mock_session.scalar.return_value = 3

    with pytest.raises(BadRequestException) as exc_info:
        await service.delete_template(
            template_id=template_id,
            tenant_id=tenant_id
        )

    error_msg = str(exc_info.value).lower()
    assert "used by" in error_msg
    assert "3" in error_msg


@pytest.mark.asyncio
async def test_rollback_template_validates_snapshot_exists(service, mock_repo):
    """Cannot rollback template without original_snapshot."""
    template_id = uuid4()
    tenant_id = uuid4()

    # Template without snapshot
    mock_template = Mock()
    mock_template.original_snapshot = None
    mock_repo.get_by_id.return_value = mock_template

    with pytest.raises(BadRequestException) as exc_info:
        await service.rollback_template(
            template_id=template_id,
            tenant_id=tenant_id
        )

    assert "snapshot not found" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_get_templates_for_tenant_excludes_global(service, mock_repo):
    """Admin list should only show tenant-specific templates."""
    tenant_id = uuid4()
    mock_templates = [Mock(), Mock()]
    mock_repo.get_for_tenant.return_value = mock_templates

    result = await service.get_templates_for_tenant(tenant_id=tenant_id)

    assert result == mock_templates
    mock_repo.get_for_tenant.assert_called_once_with(tenant_id=tenant_id)


@pytest.mark.asyncio
async def test_count_template_usage_returns_zero_when_not_used(service, mock_session):
    """Usage count returns 0 when template not used."""
    template_id = uuid4()
    mock_session.scalar.return_value = 0

    count = await service._count_template_usage(template_id)

    assert count == 0


@pytest.mark.asyncio
async def test_count_template_usage_returns_actual_count(service, mock_session):
    """Usage count returns actual number of assistants using template."""
    template_id = uuid4()
    mock_session.scalar.return_value = 5

    count = await service._count_template_usage(template_id)

    assert count == 5
