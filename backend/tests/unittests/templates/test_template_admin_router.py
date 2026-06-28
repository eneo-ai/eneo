from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest

from eneo.templates.app_template.api.admin_router import (
    create_template as create_app_template,
)
from eneo.templates.app_template.api.app_template_models import (
    AppTemplateAdminCreate,
    AppTemplateWizard,
)
from eneo.templates.assistant_template.api.admin_router import (
    create_template as create_assistant_template,
)
from eneo.templates.assistant_template.api.assistant_template_models import (
    AssistantTemplateAdminCreate,
    AssistantTemplateWizard,
)


def _build_template(completion_model_id, wizard, *, is_app):
    template = MagicMock()
    template.id = uuid4()
    template.name = "Template"
    template.description = "Description"
    template.category = "Analysis"
    template.prompt_text = "Prompt"
    template.completion_model_kwargs = {}
    completion_model = Mock()
    completion_model.id = completion_model_id
    completion_model.name = "gpt-5.4"
    template.completion_model = completion_model
    template.wizard = wizard
    template.organization = "default"
    template.tenant_id = uuid4()
    template.deleted_at = None
    template.deleted_by_user_id = None
    template.restored_at = None
    template.restored_by_user_id = None
    template.original_snapshot = {}
    template.created_at = MagicMock()
    template.updated_at = MagicMock()
    template.icon_name = None
    template.is_default = False
    if is_app:
        template.input_type = "text-field"
        template.input_description = "Describe input"
    return template


@pytest.mark.asyncio
async def test_app_admin_create_router_passes_completion_model_id():
    completion_model_id = uuid4()
    user = MagicMock(id=uuid4(), tenant_id=uuid4())
    service = AsyncMock()
    audit_service = AsyncMock()

    service.create_template.return_value = _build_template(
        completion_model_id,
        AppTemplateWizard(attachments=None, collections=None),
        is_app=True,
    )

    container = MagicMock()
    container.app_template_service.return_value = service
    container.user.return_value = user
    container.audit_service.return_value = audit_service

    data = AppTemplateAdminCreate(
        name="App template",
        description="Description",
        category="Analysis",
        prompt="Prompt",
        completion_model_id=completion_model_id,
        completion_model_kwargs={},
        wizard=AppTemplateWizard(attachments=None, collections=None),
        input_type="text-field",
        input_description="Describe input",
    )

    await create_app_template(data=data, container=container)

    create_data = service.create_template.call_args.kwargs["data"]
    assert create_data.completion_model_id == completion_model_id


@pytest.mark.asyncio
async def test_assistant_admin_create_router_passes_completion_model_id():
    completion_model_id = uuid4()
    user = MagicMock(id=uuid4(), tenant_id=uuid4())
    service = AsyncMock()
    audit_service = AsyncMock()

    service.create_template.return_value = _build_template(
        completion_model_id,
        AssistantTemplateWizard(attachments=None, collections=None),
        is_app=False,
    )

    container = MagicMock()
    container.assistant_template_service.return_value = service
    container.user.return_value = user
    container.audit_service.return_value = audit_service

    data = AssistantTemplateAdminCreate(
        name="Assistant template",
        description="Description",
        category="Analysis",
        prompt="Prompt",
        completion_model_id=completion_model_id,
        completion_model_kwargs={},
        wizard=AssistantTemplateWizard(attachments=None, collections=None),
    )

    await create_assistant_template(data=data, container=container)

    create_data = service.create_template.call_args.kwargs["data"]
    assert create_data.completion_model_id == completion_model_id
