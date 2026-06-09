from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.ai_models.completion_models.completion_model import ModelKwargs
from intric.apps.apps.api import app_router
from intric.apps.apps.api.app_models import (
    AppUpdateRequest,
    InputField,
    InputFieldType,
)


@pytest.mark.asyncio
async def test_update_app_accepts_model_kwargs_when_input_field_changes(monkeypatch):
    """PATCH audit logging must handle ModelKwargs, not dict-only kwargs."""
    app_id = uuid4()
    space_id = uuid4()
    model_id = uuid4()
    current_user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    completion_model = SimpleNamespace(id=model_id, nickname="Model")

    old_app = SimpleNamespace(
        id=app_id,
        name="App",
        description=None,
        prompt=None,
        completion_model=completion_model,
        completion_model_kwargs=ModelKwargs(temperature=0.2, top_p=0.8),
        input_fields=[InputField(type=InputFieldType.TEXT_FIELD)],
        attachments=[],
        data_retention_days=None,
        transcription_model=None,
        space_id=space_id,
    )
    updated_app = SimpleNamespace(
        id=app_id,
        name="App",
        description=None,
        prompt=None,
        completion_model=completion_model,
        completion_model_kwargs=ModelKwargs(temperature=0.3, top_p=0.8),
        input_fields=[InputField(type=InputFieldType.TEXT_UPLOAD)],
        attachments=[],
        data_retention_days=None,
        transcription_model=None,
        space_id=space_id,
    )
    permissions = MagicMock()

    service = SimpleNamespace(
        get_app=AsyncMock(return_value=(old_app, permissions)),
        update_app=AsyncMock(return_value=(updated_app, permissions)),
    )
    assembler = SimpleNamespace(
        from_app_to_model=MagicMock(return_value=SimpleNamespace(id=app_id))
    )
    audit_service = SimpleNamespace(log_async=AsyncMock())
    space_service = SimpleNamespace(get_space=AsyncMock(return_value=SimpleNamespace()))
    container = SimpleNamespace(
        app_service=lambda: service,
        app_assembler=lambda: assembler,
        user=lambda: current_user,
        space_service=lambda: space_service,
        audit_service=lambda: audit_service,
    )
    metadata_standard = MagicMock(return_value={"audit": "metadata"})
    monkeypatch.setattr(app_router.AuditMetadata, "standard", metadata_standard)

    await app_router.update_app(
        id=app_id,
        update_service_req=AppUpdateRequest(
            completion_model_kwargs=ModelKwargs(temperature=0.3, top_p=0.8),
            input_fields=[InputField(type=InputFieldType.TEXT_UPLOAD)],
        ),
        container=container,
    )

    audit_service.log_async.assert_awaited_once()
    metadata_standard.assert_called_once()
    changes = metadata_standard.call_args.kwargs["changes"]
    assert changes["temperature"] == {"old": 0.2, "new": 0.3}
    assert changes["input_fields"] == {
        "old_count": 1,
        "new_count": 1,
        "modified": True,
    }
