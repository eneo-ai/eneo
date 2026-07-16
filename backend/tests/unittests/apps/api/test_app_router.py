from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.apps.apps.api import app_router
from eneo.apps.apps.api.app_models import (
    AppUpdateRequest,
    InputField,
    InputFieldType,
)
from eneo.audit.domain.action_types import ActionType
from eneo.skills.domain.skill import ResolvedSkillBinding, SkillBindingReference
from eneo.skills.presentation.skill_models import SkillBindingReferenceInput


def _request(*, api_key=None) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": "/apps/test/",
            "headers": [],
        }
    )
    request.state.api_key = api_key
    return request


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
        request=_request(),
        container=container,
    )

    audit_service.log_async.assert_awaited_once()
    metadata_standard.assert_called_once()
    assert service.update_app.await_args.kwargs["skill_references"] is None
    changes = metadata_standard.call_args.kwargs["changes"]
    assert changes["temperature"] == {"old": 0.2, "new": 0.3}
    assert changes["input_fields"] == {
        "old_count": 1,
        "new_count": 1,
        "modified": True,
    }


async def test_update_app_rejects_api_key_skill_facet_before_service_call():
    container = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await app_router.update_app(
            id=uuid4(),
            update_service_req=AppUpdateRequest(skill_bindings=[]),
            request=_request(api_key=MagicMock()),
            container=container,
        )

    assert exc_info.value.status_code == 403
    assert "session token" in str(exc_info.value.detail)
    container.app_service.assert_not_called()


def _binding(*, position: int) -> ResolvedSkillBinding:
    return ResolvedSkillBinding(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        slug=f"skill-{position}",
        revision_number=position + 1,
        display_name=f"Skill {position}",
        description="Description must not enter parent audit evidence",
        instructions="Sensitive instructions must not enter audit evidence",
        content_digest=str(position + 1) * 64,
        position=position,
        is_active=True,
    )


async def test_update_app_folds_ordered_body_free_skills_into_single_parent_audit():
    app_id = uuid4()
    space_id = uuid4()
    model_id = uuid4()
    current_user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        active_api_key=None,
        email="editor@example.com",
        username="editor",
    )
    completion_model = SimpleNamespace(id=model_id, nickname="Model")
    old_app = SimpleNamespace(
        id=app_id,
        name="App",
        description=None,
        prompt=None,
        completion_model=completion_model,
        completion_model_kwargs=ModelKwargs(),
        input_fields=[],
        attachments=[],
        data_retention_days=None,
        transcription_model=None,
        space_id=space_id,
    )
    updated_app = SimpleNamespace(**vars(old_app))
    permissions = MagicMock()
    before = [_binding(position=0)]
    after = [_binding(position=0), _binding(position=1)]
    references = [
        SkillBindingReferenceInput(
            skill_id=binding.skill_id,
            skill_revision_id=binding.skill_revision_id,
        )
        for binding in after
    ]
    service = SimpleNamespace(
        get_app=AsyncMock(return_value=(old_app, permissions)),
        update_app=AsyncMock(return_value=(updated_app, permissions)),
    )
    skill_repo = SimpleNamespace(
        list_app_bindings=AsyncMock(side_effect=[before, after])
    )
    audit_service = SimpleNamespace(log_async=AsyncMock())
    container = SimpleNamespace(
        app_service=lambda: service,
        skill_repo=lambda: skill_repo,
        app_assembler=lambda: SimpleNamespace(
            from_app_to_model=MagicMock(return_value=SimpleNamespace(id=app_id))
        ),
        user=lambda: current_user,
        space_service=lambda: SimpleNamespace(
            get_space=AsyncMock(return_value=SimpleNamespace(id=space_id, name="Space"))
        ),
        audit_service=lambda: audit_service,
    )

    await app_router.update_app(
        id=app_id,
        update_service_req=AppUpdateRequest(skill_bindings=references),
        request=_request(),
        container=container,
    )

    service.update_app.assert_awaited_once()
    assert service.update_app.await_args.kwargs["skill_references"] == [
        SkillBindingReference(
            skill_id=reference.skill_id,
            skill_revision_id=reference.skill_revision_id,
        )
        for reference in references
    ]
    audit_service.log_async.assert_awaited_once()
    audit_call = audit_service.log_async.await_args.kwargs
    assert audit_call["action"] == ActionType.APP_UPDATED
    skills_change = audit_call["metadata"]["changes"]["skills"]
    assert [entry["position"] for entry in skills_change["new"]] == [0, 1]
    assert "instructions" not in str(skills_change)
    assert "description" not in str(skills_change)
