"""Unit tests for AppTemplateService tenant-scoped methods."""

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from eneo.main.exceptions import (
    BadRequestException,
    NameCollisionException,
    NotFoundException,
)
from eneo.templates.app_template.api.app_template_models import (
    AppTemplateCreate,
    AppTemplateUpdate,
    AppTemplateWizard,
)
from eneo.templates.app_template.app_template_service import AppTemplateService


@pytest.fixture
def mock_repo():
    return AsyncMock()


@pytest.fixture
def mock_factory():
    return Mock()


@pytest.fixture
def mock_feature_flag_service():
    return AsyncMock()


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.refresh = AsyncMock()
    session.scalar = AsyncMock()
    return session


@pytest.fixture
def mock_user():
    user = Mock()
    user.id = uuid4()
    user.tenant_id = uuid4()
    user.permissions = ["admin"]
    return user


@pytest.fixture
def service(
    mock_repo, mock_factory, mock_feature_flag_service, mock_session, mock_user
):
    return AppTemplateService(
        repo=mock_repo,
        factory=mock_factory,
        feature_flag_service=mock_feature_flag_service,
        session=mock_session,
        user=mock_user,
    )


@pytest.mark.asyncio
async def test_create_template_requires_feature_flag_enabled(
    service,
    mock_feature_flag_service,
):
    tenant_id = uuid4()
    mock_feature_flag_service.check_is_feature_enabled.return_value = False

    data = AppTemplateCreate(
        name="Test",
        description="Test",
        category="Test",
        prompt="Test",
        wizard=AppTemplateWizard(attachments=None, collections=None),
        input_type="text-field",
        input_description=None,
    )

    with pytest.raises(BadRequestException):
        await service.create_template(data=data, tenant_id=tenant_id)


@pytest.mark.asyncio
async def test_create_template_checks_duplicate_name(
    service,
    mock_feature_flag_service,
    mock_repo,
):
    tenant_id = uuid4()
    mock_feature_flag_service.check_is_feature_enabled.return_value = True
    mock_repo.check_duplicate_name.return_value = True

    data = AppTemplateCreate(
        name="Duplicate Name",
        description="Test",
        category="Test",
        prompt="Test",
        wizard=AppTemplateWizard(attachments=None, collections=None),
        input_type="text-field",
        input_description=None,
    )

    with pytest.raises(NameCollisionException):
        await service.create_template(data=data, tenant_id=tenant_id)


@pytest.mark.asyncio
async def test_update_template_validates_ownership(service, mock_repo):
    template_id = uuid4()
    tenant_id = uuid4()
    mock_repo.get_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await service.update_template(
            template_id=template_id,
            data=AppTemplateUpdate(name="Updated"),
            tenant_id=tenant_id,
        )


@pytest.mark.asyncio
async def test_create_template_persists_completion_model_id_and_snapshot(
    service,
    mock_feature_flag_service,
    mock_repo,
    mock_session,
    mock_factory,
):
    tenant_id = uuid4()
    completion_model_id = uuid4()

    mock_feature_flag_service.check_is_feature_enabled.return_value = True
    mock_repo.check_duplicate_name.return_value = False

    template_record = Mock()
    template_record.completion_model = None
    result = Mock()
    result.scalar_one.return_value = template_record
    mock_session.execute.return_value = result
    mock_factory.create_app_template.return_value = Mock()

    data = AppTemplateCreate(
        name="Document analyzer",
        description="Analyze documents",
        category="Analysis",
        prompt="Analyze this",
        completion_model_kwargs={"verbosity": "low"},
        completion_model_id=completion_model_id,
        wizard=AppTemplateWizard(attachments=None, collections=None),
        input_type="text-field",
        input_description="Paste text",
    )

    await service.create_template(data=data, tenant_id=tenant_id)

    stmt = mock_session.execute.call_args.args[0]
    params = stmt.compile().params

    assert params["completion_model_id"] == completion_model_id
    assert params["original_snapshot"]["completion_model_id"] == str(
        completion_model_id
    )


@pytest.mark.asyncio
async def test_rollback_template_restores_completion_model_id(
    service,
    mock_repo,
    mock_session,
    mock_factory,
):
    template_id = uuid4()
    tenant_id = uuid4()
    completion_model_id = uuid4()

    template = Mock()
    template.original_snapshot = {
        "name": "Original",
        "description": "Description",
        "category": "Analysis",
        "prompt_text": "Prompt",
        "completion_model_kwargs": {"verbosity": "medium"},
        "completion_model_id": str(completion_model_id),
        "wizard": {"attachments": None, "collections": None},
        "input_type": "text-field",
        "input_description": "Describe input",
    }
    mock_repo.get_by_id.return_value = template

    restored_record = Mock()
    restored_record.completion_model = None
    result = Mock()
    result.scalar_one.return_value = restored_record
    mock_session.execute.return_value = result
    mock_factory.create_app_template.return_value = Mock()

    await service.rollback_template(template_id=template_id, tenant_id=tenant_id)

    stmt = mock_session.execute.call_args.args[0]
    params = stmt.compile().params

    assert params["completion_model_id"] == completion_model_id
