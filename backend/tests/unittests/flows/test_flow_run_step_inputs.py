from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.flow_input_limits import FlowInputLimits
from eneo.flows.flow_run_step_inputs import (
    FlowRunStepInputFiles,
    aggregate_runtime_file_limit,
    build_runtime_step_input_specs,
    normalize_step_inputs_payload,
    validate_submitted_step_inputs,
)
from eneo.flows.principal import FlowPrincipal
from eneo.main.exceptions import BadRequestException


def _runtime_step() -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description="Read source document.",
        input_source="flow_input",
        input_bindings=None,
        input_config={
            "runtime_input": {
                "enabled": True,
                "input_format": "document",
                "max_files": 2,
            }
        },
        output_mode="pass_through",
        output_config=None,
        output_type="json",
    )


def _runtime_step_with_order(step_order: int) -> RuntimeStep:
    return replace(_runtime_step(), step_id=uuid4(), step_order=step_order)


def _unbounded_runtime_step() -> RuntimeStep:
    return replace(
        _runtime_step(),
        step_id=uuid4(),
        input_config={
            "runtime_input": {
                "enabled": True,
                "input_format": "document",
            }
        },
    )


def _principal(user_id):
    return FlowPrincipal(
        principal_type=PrincipalType.USER,
        principal_user_id=user_id,
    )


@pytest.mark.asyncio
async def test_validate_step_inputs_runs_owner_lookup_for_any_submitted_file_id() -> (
    None
):
    flow_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    file_id = uuid4()
    step = _runtime_step()
    specs = build_runtime_step_input_specs(
        steps=[step],
        limits=FlowInputLimits(
            file_max_size_bytes=10_000,
            audio_max_size_bytes=10_000,
        ),
    )
    file_repo = AsyncMock()
    runtime_upload_repo = AsyncMock()
    file_repo.get_list_by_id_for_owner.return_value = [
        SimpleNamespace(id=file_id, mimetype="application/pdf", size=1024)
    ]
    runtime_upload_repo.list_bound_file_ids_for_owner.return_value = {file_id}

    await validate_submitted_step_inputs(
        flow_id=flow_id,
        steps=[step],
        specs=specs,
        normalized_step_inputs=normalize_step_inputs_payload(
            {step.step_id: FlowRunStepInputFiles(file_ids=(file_id,))}
        ),
        file_repo=file_repo,
        runtime_upload_repo=runtime_upload_repo,
        principal=_principal(user_id),
        tenant_id=tenant_id,
    )

    file_repo.get_list_by_id_for_owner.assert_awaited_once_with(
        ids=[file_id],
        owner_type="user",
        owner_user_id=user_id,
        owner_service_id=None,
        tenant_id=tenant_id,
        include_transcription=False,
    )


@pytest.mark.asyncio
async def test_validate_step_inputs_rejects_owner_file_not_bound_to_flow() -> None:
    flow_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    file_id = uuid4()
    step = _runtime_step()
    specs = build_runtime_step_input_specs(
        steps=[step],
        limits=FlowInputLimits(
            file_max_size_bytes=10_000,
            audio_max_size_bytes=10_000,
        ),
    )
    file_repo = AsyncMock()
    runtime_upload_repo = AsyncMock()
    file_repo.get_list_by_id_for_owner.return_value = [
        SimpleNamespace(id=file_id, mimetype="application/pdf", size=1024)
    ]
    runtime_upload_repo.list_bound_file_ids_for_owner.return_value = set()

    with pytest.raises(BadRequestException) as exc_info:
        await validate_submitted_step_inputs(
            flow_id=flow_id,
            steps=[step],
            specs=specs,
            normalized_step_inputs=normalize_step_inputs_payload(
                {step.step_id: FlowRunStepInputFiles(file_ids=(file_id,))}
            ),
            file_repo=file_repo,
            runtime_upload_repo=runtime_upload_repo,
            principal=_principal(user_id),
            tenant_id=tenant_id,
        )

    assert exc_info.value.code == "flow_run_file_not_bound_to_flow"
    assert exc_info.value.context == {
        "step_id": str(step.step_id),
        "file_ids": [str(file_id)],
    }
    runtime_upload_repo.list_bound_file_ids_for_owner.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_step_inputs_rejects_unknown_step_with_context() -> None:
    flow_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    known_step = _runtime_step()
    unknown_step_id = uuid4()
    specs = build_runtime_step_input_specs(
        steps=[known_step],
        limits=FlowInputLimits(
            file_max_size_bytes=10_000,
            audio_max_size_bytes=10_000,
        ),
    )

    with pytest.raises(BadRequestException) as exc_info:
        await validate_submitted_step_inputs(
            flow_id=flow_id,
            steps=[known_step],
            specs=specs,
            normalized_step_inputs={unknown_step_id: []},
            file_repo=AsyncMock(),
            runtime_upload_repo=AsyncMock(),
            principal=_principal(user_id),
            tenant_id=tenant_id,
        )

    assert exc_info.value.code == "flow_run_unknown_step_input"
    assert exc_info.value.context == {"step_id": str(unknown_step_id)}


@pytest.mark.asyncio
async def test_validate_step_inputs_rejects_file_above_current_limit() -> None:
    flow_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    file_id = uuid4()
    step = _runtime_step()
    specs = build_runtime_step_input_specs(
        steps=[step],
        limits=FlowInputLimits(
            file_max_size_bytes=100,
            audio_max_size_bytes=10_000,
        ),
    )
    file_repo = AsyncMock()
    runtime_upload_repo = AsyncMock()
    file_repo.get_list_by_id_for_owner.return_value = [
        SimpleNamespace(id=file_id, mimetype="application/pdf", size=101)
    ]
    runtime_upload_repo.list_bound_file_ids_for_owner.return_value = {file_id}

    with pytest.raises(BadRequestException) as exc_info:
        await validate_submitted_step_inputs(
            flow_id=flow_id,
            steps=[step],
            specs=specs,
            normalized_step_inputs=normalize_step_inputs_payload(
                {step.step_id: FlowRunStepInputFiles(file_ids=(file_id,))}
            ),
            file_repo=file_repo,
            runtime_upload_repo=runtime_upload_repo,
            principal=_principal(user_id),
            tenant_id=tenant_id,
        )

    assert exc_info.value.code == "flow_run_step_input_file_too_large"
    assert exc_info.value.context == {
        "step_id": str(step.step_id),
        "file_id": str(file_id),
        "size_bytes": 101,
        "max_file_size_bytes": 100,
    }


@pytest.mark.asyncio
async def test_validate_step_inputs_allows_same_flow_file_for_multiple_steps() -> None:
    flow_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    file_id = uuid4()
    step_one = _runtime_step()
    step_two = _runtime_step_with_order(2)
    steps = [step_one, step_two]
    specs = build_runtime_step_input_specs(
        steps=steps,
        limits=FlowInputLimits(
            file_max_size_bytes=10_000,
            audio_max_size_bytes=10_000,
        ),
    )
    file_repo = AsyncMock()
    runtime_upload_repo = AsyncMock()
    file_repo.get_list_by_id_for_owner.return_value = [
        SimpleNamespace(id=file_id, mimetype="application/pdf", size=1024)
    ]
    runtime_upload_repo.list_bound_file_ids_for_owner.return_value = {file_id}

    await validate_submitted_step_inputs(
        flow_id=flow_id,
        steps=steps,
        specs=specs,
        normalized_step_inputs=normalize_step_inputs_payload(
            {
                step_one.step_id: FlowRunStepInputFiles(file_ids=(file_id,)),
                step_two.step_id: FlowRunStepInputFiles(file_ids=(file_id,)),
            }
        ),
        file_repo=file_repo,
        runtime_upload_repo=runtime_upload_repo,
        principal=_principal(user_id),
        tenant_id=tenant_id,
    )

    file_repo.get_list_by_id_for_owner.assert_awaited_once()
    assert file_repo.get_list_by_id_for_owner.await_args.kwargs["ids"] == [file_id]
    runtime_upload_repo.list_bound_file_ids_for_owner.assert_awaited_once()


def test_aggregate_runtime_file_limit_uses_runtime_step_specs() -> None:
    bounded_specs = build_runtime_step_input_specs(
        steps=[_runtime_step(), _runtime_step_with_order(2)],
        limits=FlowInputLimits(
            file_max_size_bytes=10_000,
            audio_max_size_bytes=10_000,
        ),
    )
    unbounded_specs = build_runtime_step_input_specs(
        steps=[_unbounded_runtime_step()],
        limits=FlowInputLimits(
            file_max_size_bytes=10_000,
            audio_max_size_bytes=10_000,
            max_files_per_run=None,
        ),
    )

    assert aggregate_runtime_file_limit(specs={}) == 0
    assert aggregate_runtime_file_limit(specs=bounded_specs) == 4
    assert aggregate_runtime_file_limit(specs=unbounded_specs) is None
