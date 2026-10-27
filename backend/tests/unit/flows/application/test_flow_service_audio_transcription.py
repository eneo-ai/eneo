"""A draft written with a step that takes audio has transcription turned on."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from eneo.flows.application.flow_service import FlowService
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.transcription_config import DEFAULT_TRANSCRIPTION_LANGUAGE
from eneo.tenants.tenant import TenantInDB
from eneo.users.user import UserInDB


def _user() -> UserInDB:
    tenant = TenantInDB(id=uuid4(), name="tenant", quota_limit=0, quota_used=0)
    return UserInDB(
        id=uuid4(),
        username="author",
        email="author@example.org",
        salt="salt",
        password="password",
        used_tokens=0,
        tenant_id=tenant.id,
        quota_used=0,
        tenant=tenant,
        state="active",
    )


def _service(user, flow_repo, space=None) -> FlowService:
    service = FlowService(
        user=user,
        flow_repo=flow_repo,
        flow_version_repo=AsyncMock(),
        assistant_service=AsyncMock(),
        template_asset_service=AsyncMock(),
        space_service=None
        if space is None
        else AsyncMock(get_space=AsyncMock(return_value=space)),
    )
    service._validate_assistant_scope_for_steps = AsyncMock()  # type: ignore[method-assign]
    service._validate_step_security_classification_for_steps = AsyncMock()  # type: ignore[method-assign]
    return service


def _saved_flow(user) -> Flow:
    now = datetime.now(timezone.utc)
    return Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Draft",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=now,
        updated_at=now,
        steps=[],
    )


def _step(order: int, *, input_type: str, output_mode: str) -> FlowStep:
    return FlowStep(
        assistant_id=uuid4(),
        step_order=order,
        user_description=f"Step {order}",
        input_source="flow_input" if order == 1 else "previous_step",
        input_type=input_type,
        output_mode=output_mode,
        output_type="text",
    )


async def _written_metadata(service, flow, steps):
    service.flow_repo.update.side_effect = (
        lambda flow, tenant_id, expected_revision=None: flow
    )
    await service.update_flow(flow_id=flow.id, steps=steps)
    service.flow_repo.update.assert_awaited_once()
    call = service.flow_repo.update.await_args
    written = call.kwargs["flow"] if "flow" in call.kwargs else call.args[0]
    return written.metadata_json


async def test_an_audio_step_turns_transcription_on_with_the_spaces_default_model():
    user = _user()
    flow_repo = AsyncMock()
    flow = _saved_flow(user)
    flow_repo.get.return_value = flow
    model_id = uuid4()
    space = SimpleNamespace(
        get_marked_default_transcription_model=lambda: SimpleNamespace(id=model_id),
        default_transcription_service=None,
    )
    service = _service(user, flow_repo, space)

    metadata = await _written_metadata(
        service,
        flow,
        [
            _step(1, input_type="audio", output_mode="transcribe_only"),
            _step(2, input_type="text", output_mode="pass_through"),
        ],
    )

    assert metadata == {
        "wizard": {
            "transcription_enabled": True,
            "transcription_model": {"id": str(model_id)},
            "transcription_language": DEFAULT_TRANSCRIPTION_LANGUAGE,
        }
    }


async def test_an_audio_step_turns_transcription_on_without_a_space_to_ask():
    user = _user()
    flow_repo = AsyncMock()
    flow = _saved_flow(user)
    flow_repo.get.return_value = flow
    service = _service(user, flow_repo)

    metadata = await _written_metadata(
        service, flow, [_step(1, input_type="audio", output_mode="transcribe_only")]
    )

    assert metadata == {
        "wizard": {
            "transcription_enabled": True,
            "transcription_language": DEFAULT_TRANSCRIPTION_LANGUAGE,
        }
    }


async def test_a_draft_without_audio_steps_is_written_as_given():
    user = _user()
    flow_repo = AsyncMock()
    flow = _saved_flow(user)
    flow_repo.get.return_value = flow
    service = _service(user, flow_repo)

    metadata = await _written_metadata(
        service, flow, [_step(1, input_type="text", output_mode="pass_through")]
    )

    assert metadata is None
