from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.domain.flow import Flow, FlowStep
from intric.flows.domain.flow_invariant_exceptions import FlowPersistedIdMissingError
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.flow_api_exceptions import FlowBadRequestException
from intric.flows.flow_input_limits import FlowInputLimits
from intric.flows.published_definition import FLOW_DEFINITION_SCHEMA_VERSION
from intric.flows.published_runtime import (
    FlowRuntimePublicationIntent,
    load_published_flow_runtime,
    load_published_runtime_inputs,
)
from intric.main.exceptions import ErrorCodes
from intric.main.models import GeneralError


def _step(*, input_type: str = "document") -> FlowStep:
    input_config = None
    if input_type in {"audio", "document", "file"}:
        input_config = {
            "runtime_input": {
                "enabled": True,
                "required": True,
                "input_format": input_type,
                "max_files": 3,
                "label": "Upload",
            }
        }
    return FlowStep(
        id=uuid4(),
        assistant_id=uuid4(),
        step_order=1,
        input_source="flow_input",
        input_type=input_type,
        input_config=input_config,
        output_mode="pass_through",
        output_type="json",
        mcp_policy="inherit",
    )


def _flow(*, step: FlowStep, published_version: int | None = 1) -> Flow:
    now = datetime.now(timezone.utc)
    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Flow",
        steps=[step],
        published_version=published_version,
        created_at=now,
        updated_at=now,
    )


def _definition_json(*, flow: Flow, step: FlowStep) -> dict[str, object]:
    assert flow.id is not None
    return {
        "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
        "flow_id": str(flow.id),
        "steps": [
            {
                "step_id": str(step.id),
                "step_order": step.step_order,
                "assistant_id": str(step.assistant_id),
                "input_source": step.input_source,
                "input_type": step.input_type,
                "input_config": step.input_config,
                "output_mode": step.output_mode,
                "output_type": step.output_type,
                "mcp_policy": step.mcp_policy,
            }
        ],
    }


@pytest.mark.asyncio
async def test_load_published_flow_runtime_requires_persisted_id_first() -> None:
    flow_service = AsyncMock()
    step = _step()
    flow_service.get_flow.return_value = _flow(step=step).model_copy(
        update={"id": None, "published_version": None}
    )

    with pytest.raises(FlowPersistedIdMissingError):
        await load_published_flow_runtime(
            flow_service=flow_service,
            flow_id=uuid4(),
            intent=FlowRuntimePublicationIntent.RUN_CONTRACT,
        )


@pytest.mark.parametrize(
    ("intent", "message"),
    [
        (
            FlowRuntimePublicationIntent.RUN_CONTRACT,
            "Flow must be published before a run contract can be created.",
        ),
        (
            FlowRuntimePublicationIntent.RUNTIME_UPLOAD,
            "Flow must be published before runtime files can be uploaded.",
        ),
        (
            FlowRuntimePublicationIntent.RUNTIME_DELETE,
            "Flow must be published before runtime files can be deleted.",
        ),
    ],
)
@pytest.mark.asyncio
async def test_load_published_flow_runtime_rejects_unpublished_flow(
    intent: FlowRuntimePublicationIntent,
    message: str,
) -> None:
    flow_service = AsyncMock()
    step = _step()
    flow = _flow(step=step, published_version=None)
    flow_service.get_flow.return_value = flow

    with pytest.raises(FlowBadRequestException) as exc_info:
        await load_published_flow_runtime(
            flow_service=flow_service,
            flow_id=flow.id,
            intent=intent,
        )

    assert exc_info.value.code is FlowApiErrorCode.FLOW_NOT_PUBLISHED
    assert str(exc_info.value) == message


@pytest.mark.asyncio
async def test_load_published_runtime_inputs_builds_published_runtime_specs() -> None:
    flow_service = AsyncMock()
    flow_version_repo = AsyncMock()
    settings_service = AsyncMock()
    step = _step(input_type="audio")
    flow = _flow(step=step, published_version=5)
    assert flow.id is not None
    flow_service.get_flow.return_value = flow
    flow_version_repo.get.return_value = SimpleNamespace(
        version=5,
        definition_json=_definition_json(flow=flow, step=step),
    )
    settings_service.get_flow_input_limits_resolved.return_value = FlowInputLimits(
        file_max_size_bytes=12_000_000,
        audio_max_size_bytes=25_000_000,
        max_files_per_run=5,
        audio_max_files_per_run=2,
    )

    result = await load_published_runtime_inputs(
        flow_service=flow_service,
        flow_version_repo=flow_version_repo,
        settings_source=settings_service,
        flow_id=flow.id,
        intent=FlowRuntimePublicationIntent.RUNTIME_UPLOAD,
    )

    assert result.published.flow is flow
    assert result.published.flow_id == flow.id
    assert result.published.published_version == 5
    assert result.definition.flow_id == flow.id
    assert [runtime_step.step_id for runtime_step in result.steps] == [step.id]
    assert result.limits.audio_max_size_bytes == 25_000_000
    spec = result.input_specs[step.id]
    assert spec.max_files == 2
    assert spec.max_file_size_bytes == 25_000_000
    assert "audio/mpeg" in spec.accepted_mimetypes
    flow_version_repo.get.assert_awaited_once_with(
        flow_id=flow.id,
        version=5,
        tenant_id=flow.tenant_id,
    )


def test_flow_bad_request_exception_code_serializes_to_public_string() -> None:
    exc = FlowBadRequestException(
        "Flow must be published before runtime files can be uploaded.",
        code=FlowApiErrorCode.FLOW_NOT_PUBLISHED,
    )

    payload = GeneralError(
        message=str(exc),
        intric_error_code=ErrorCodes.BAD_REQUEST,
        code=exc.code,
    ).model_dump(mode="json")

    assert payload["code"] == FlowApiErrorCode.FLOW_NOT_PUBLISHED.value
