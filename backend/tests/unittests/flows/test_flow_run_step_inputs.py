from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_models import FileContentVariant, FileMetadata, FileType
from eneo.files.file_repo import FileRepository
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.enums import FlowRuntimeInputFormat
from eneo.flows.flow_input_limits import FlowInputLimits
from eneo.flows.flow_run_step_inputs import (
    FlowRunStepInputFiles,
    aggregate_runtime_file_limit,
    build_runtime_step_input_specs,
    normalize_step_inputs_payload,
    primary_runtime_input_format,
    validate_submitted_step_inputs,
)
from eneo.flows.principal import FlowPrincipal
from eneo.main.config import get_settings
from eneo.main.exceptions import BadRequestException


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_format,inline_ceiling,binary_ceiling,expected_kind",
    [
        ("document", 10, 1000, "inline_text"),
        ("document", 1000, 100, "binary"),
        ("document", 20, 1000, None),
        ("audio", 10, 100, "binary"),
    ],
)
async def test_admission_measures_all_steps_from_metadata(
    monkeypatch, input_format, inline_ceiling, binary_ceiling, expected_kind
):
    monkeypatch.setattr(get_settings(), "flow_max_inline_text_bytes", inline_ceiling)
    steps = [
        replace(
            _runtime_step_with_order(order),
            input_config={
                "runtime_input": {
                    "enabled": True,
                    "input_format": input_format,
                    "max_files": 2,
                }
            },
        )
        for order in (1, 2)
    ]
    file_ids = [uuid4(), uuid4()]
    audio = input_format == "audio"
    files = [
        SimpleNamespace(
            id=file_id,
            size=80,
            name="source",
            file_type=FileType.AUDIO if audio else FileType.DOCUMENT,
            mimetype="audio/mpeg" if audio else "application/pdf",
        )
        for file_id in file_ids
    ]
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_owner.return_value = files
    file_repo.get_infos_with_references_by_ids.return_value = (files, [])
    file_repo.get_content_references.return_value = [
        SimpleNamespace(file_id=file_id, variant=variant, size_bytes=size)
        for file_id in file_ids
        for variant, size in (
            [(FileContentVariant.ORIGINAL, 80)]
            if audio
            else [
                (FileContentVariant.ORIGINAL, 80),
                (FileContentVariant.EXTRACTED_TEXT, 6),
            ]
        )
    ]
    file_repo.get_infos_with_references_by_ids.return_value = (
        file_repo.get_infos_with_references_by_ids.return_value[0],
        file_repo.get_content_references.return_value,
    )
    upload_repo = AsyncMock()
    upload_repo.list_bound_file_ids_for_owner.return_value = set(file_ids)
    kwargs = dict(
        flow_id=uuid4(),
        steps=steps,
        specs=build_runtime_step_input_specs(
            steps=steps,
            limits=FlowInputLimits(
                file_max_size_bytes=binary_ceiling,
                audio_max_size_bytes=binary_ceiling,
            ),
        ),
        normalized_step_inputs={
            step.step_id: [file_id] for step, file_id in zip(steps, file_ids)
        },
        file_repo=file_repo,
        runtime_upload_repo=upload_repo,
        principal=_principal(uuid4()),
        tenant_id=uuid4(),
    )
    if expected_kind is None:
        await validate_submitted_step_inputs(**kwargs)
    else:
        with pytest.raises(BadRequestException) as error:
            await validate_submitted_step_inputs(**kwargs)
        assert error.value.code == "flow_run_input_exceeds_limit"
        assert error.value.context == {
            "kind": expected_kind,
            "measured": 12 if expected_kind == "inline_text" else 160,
            "ceiling": inline_ceiling
            if expected_kind == "inline_text"
            else binary_ceiling,
        }
    file_repo.get_legacy_content.assert_not_awaited()


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "original_bytes,selected_bytes,error_code",
    [
        (40, 120, "flow_run_input_exceeds_limit"),
        (120, 40, "flow_run_step_input_file_too_large"),
    ],
)
async def test_admission_bounds_selected_image_and_original_upload_separately(
    original_bytes, selected_bytes, error_code
):
    step = _runtime_step()
    file_id = uuid4()
    file = SimpleNamespace(
        id=file_id,
        size=selected_bytes,
        mimetype="image/png",
        file_type=FileType.IMAGE,
    )
    file_repo = AsyncMock()
    file_repo.get_list_by_id_and_owner.return_value = [file]
    file_repo.get_infos_with_references_by_ids.return_value = ([file], [])
    file_repo.get_content_references.return_value = [
        SimpleNamespace(file_id=file_id, variant=variant, size_bytes=size)
        for variant, size in (
            (FileContentVariant.ORIGINAL, original_bytes),
            (FileContentVariant.MODEL_INPUT, selected_bytes),
        )
    ]
    file_repo.get_infos_with_references_by_ids.return_value = (
        file_repo.get_infos_with_references_by_ids.return_value[0],
        file_repo.get_content_references.return_value,
    )
    upload_repo = AsyncMock()
    upload_repo.list_bound_file_ids_for_owner.return_value = {file_id}
    specs = build_runtime_step_input_specs(
        steps=[step],
        limits=FlowInputLimits(file_max_size_bytes=100, audio_max_size_bytes=100),
    )
    specs[step.step_id] = replace(specs[step.step_id], accepted_mimetypes=["image/png"])
    with pytest.raises(BadRequestException) as error:
        await validate_submitted_step_inputs(
            flow_id=uuid4(),
            steps=[step],
            specs=specs,
            normalized_step_inputs={step.step_id: [file_id]},
            file_repo=file_repo,
            runtime_upload_repo=upload_repo,
            principal=_principal(uuid4()),
            tenant_id=uuid4(),
        )
    assert error.value.code == error_code
    if original_bytes < 100:
        assert error.value.context == {
            "kind": "binary",
            "measured": 120,
            "ceiling": 100,
        }
    file_repo.get_legacy_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_admission_reuses_projected_content_references():
    owner_id, tenant_id, file_id = uuid4(), uuid4(), uuid4()
    metadata = FileMetadata(
        id=file_id,
        name="source.pdf",
        file_type=FileType.TEXT,
        mimetype="application/pdf",
        owner_type=PrincipalType.USER,
        owner_user_id=owner_id,
        tenant_id=tenant_id,
    )
    repo = FileRepository(session=AsyncMock())
    repo.get_by_ids = AsyncMock(return_value=[metadata])
    repo.get_list_by_id_and_owner = AsyncMock(return_value=[metadata])
    repo.get_legacy_infos = AsyncMock(return_value=[])
    repo.get_content_references = AsyncMock(
        return_value=[
            SimpleNamespace(
                file_id=file_id,
                variant=variant,
                size_bytes=size,
                sha256=b"x" * 32,
                media_type=media_type,
            )
            for variant, size, media_type in (
                (FileContentVariant.ORIGINAL, 80, "application/pdf"),
                (FileContentVariant.EXTRACTED_TEXT, 6, "text/plain"),
            )
        ]
    )
    upload_repo = AsyncMock()
    upload_repo.list_bound_file_ids_for_owner.return_value = {file_id}
    step = _runtime_step()
    await validate_submitted_step_inputs(
        flow_id=uuid4(),
        steps=[step],
        specs=build_runtime_step_input_specs(
            steps=[step],
            limits=FlowInputLimits(file_max_size_bytes=100, audio_max_size_bytes=100),
        ),
        normalized_step_inputs={step.step_id: [file_id]},
        file_repo=repo,
        runtime_upload_repo=upload_repo,
        principal=_principal(owner_id),
        tenant_id=tenant_id,
    )
    repo.get_content_references.assert_awaited_once_with([file_id])


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
    file_repo.get_list_by_id_and_owner.return_value = [SimpleNamespace(id=file_id)]
    file_repo.get_infos_with_references_by_ids.return_value = (
        [
            SimpleNamespace(
                id=file_id,
                file_type=FileType.DOCUMENT,
                mimetype="application/pdf",
                size=1024,
            )
        ],
        [],
    )
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

    file_repo.get_list_by_id_and_owner.assert_awaited_once_with(
        ids=[file_id],
        owner=_principal(user_id).file_owner(tenant_id=tenant_id),
    )
    file_repo.get_infos_with_references_by_ids.assert_awaited_once_with([file_id])


@pytest.mark.asyncio
async def test_validate_step_inputs_rejects_file_without_durable_content() -> None:
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
    file_repo.get_list_by_id_and_owner.return_value = [SimpleNamespace(id=file_id)]
    file_repo.get_infos_with_references_by_ids.return_value = ([], [])

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

    assert exc_info.value.code == "flow_run_file_not_accessible"
    assert exc_info.value.context == {
        "step_id": str(step.step_id),
        "file_ids": [str(file_id)],
    }
    runtime_upload_repo.list_bound_file_ids_for_owner.assert_not_awaited()


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
    file_repo.get_list_by_id_and_owner.return_value = [SimpleNamespace(id=file_id)]
    file_repo.get_infos_with_references_by_ids.return_value = (
        [
            SimpleNamespace(
                id=file_id,
                file_type=FileType.DOCUMENT,
                mimetype="application/pdf",
                size=1024,
            )
        ],
        [],
    )
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
    file_repo.get_list_by_id_and_owner.return_value = [SimpleNamespace(id=file_id)]
    file_repo.get_infos_with_references_by_ids.return_value = (
        [
            SimpleNamespace(
                id=file_id,
                file_type=FileType.DOCUMENT,
                mimetype="application/pdf",
                size=101,
            )
        ],
        [],
    )
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
    file_repo.get_list_by_id_and_owner.return_value = [SimpleNamespace(id=file_id)]
    file_repo.get_infos_with_references_by_ids.return_value = (
        [
            SimpleNamespace(
                id=file_id,
                file_type=FileType.DOCUMENT,
                mimetype="application/pdf",
                size=1024,
            )
        ],
        [],
    )
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

    file_repo.get_list_by_id_and_owner.assert_awaited_once()
    assert file_repo.get_list_by_id_and_owner.await_args.kwargs["ids"] == [file_id]
    file_repo.get_infos_with_references_by_ids.assert_awaited_once_with([file_id])
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
    assert aggregate_runtime_file_limit(specs=unbounded_specs) == 1000


@pytest.mark.asyncio
async def test_null_file_policy_refuses_above_deployment_ceiling_before_lookup():
    step = _unbounded_runtime_step()
    specs = build_runtime_step_input_specs(
        steps=[step],
        limits=FlowInputLimits(
            file_max_size_bytes=10_000,
            audio_max_size_bytes=10_000,
            max_files_per_run=None,
        ),
    )
    file_repo = AsyncMock()
    with pytest.raises(BadRequestException) as error:
        await validate_submitted_step_inputs(
            flow_id=uuid4(),
            steps=[step],
            specs=specs,
            normalized_step_inputs={step.step_id: [uuid4() for _ in range(1001)]},
            file_repo=file_repo,
            runtime_upload_repo=AsyncMock(),
            principal=_principal(uuid4()),
            tenant_id=uuid4(),
        )
    assert error.value.code == "flow_run_step_input_max_files_exceeded"
    assert error.value.context["max_files"] == 1000
    assert "1000" in str(error.value)
    file_repo.get_list_by_id_and_owner.assert_not_awaited()


@pytest.mark.asyncio
async def test_sum_of_step_limits_is_capped_before_metadata_lookup():
    steps = [_unbounded_runtime_step(), _unbounded_runtime_step()]
    specs = build_runtime_step_input_specs(
        steps=steps,
        limits=FlowInputLimits(file_max_size_bytes=10_000, audio_max_size_bytes=10_000),
    )
    file_repo = AsyncMock()
    with pytest.raises(BadRequestException) as error:
        await validate_submitted_step_inputs(
            flow_id=uuid4(),
            steps=steps,
            specs=specs,
            normalized_step_inputs={
                step.step_id: [uuid4() for _ in range(501)] for step in steps
            },
            file_repo=file_repo,
            runtime_upload_repo=AsyncMock(),
            principal=_principal(uuid4()),
            tenant_id=uuid4(),
        )
    assert error.value.code == "flow_run_aggregate_max_files_exceeded"
    assert error.value.context["aggregate_max_files"] == 1000
    assert "1000" in str(error.value)
    file_repo.get_list_by_id_and_owner.assert_not_awaited()


def test_runtime_step_specs_clamp_per_source_to_published_policy_and_input_minimum() -> (
    None
):
    step = replace(
        _runtime_step(),
        input_config={
            "runtime_input": {
                "enabled": True,
                "input_format": "document",
                "execution_mode": "per_source",
                "max_files": 8,
            }
        },
    )

    specs = build_runtime_step_input_specs(
        steps=[step],
        limits=FlowInputLimits(
            file_max_size_bytes=10_000,
            audio_max_size_bytes=10_000,
            max_files_per_run=6,
        ),
        mapped_policy=FlowMappedExecutionPolicy(max_provider_calls_per_mapped_step=4),
    )

    # Policy ceiling 4 clamps to 3 admitted files: one provider call stays
    # reserved for the native-JSON fallback.
    assert specs[step.step_id].max_files == 3


def test_primary_runtime_input_format_returns_none_for_no_steps() -> None:
    assert primary_runtime_input_format([]) is None


def test_primary_runtime_input_format_returns_none_when_no_step_accepts_input() -> None:
    assert primary_runtime_input_format([None, {"runtime_input": False}]) is None


def test_primary_runtime_input_format_matches_run_contract_input_spec_for_same_step() -> (
    None
):
    """`primary_runtime_input_format` must resolve through the exact per-step
    parser `build_runtime_step_input_specs` uses, so the flow list's derived
    `input_type` cannot diverge from the run contract's `steps_requiring_input`
    for the same step configuration.
    """
    no_input_step = replace(
        _runtime_step_with_order(1),
        input_config=None,
    )
    audio_step = replace(
        _runtime_step_with_order(2),
        input_config={
            "runtime_input": {"enabled": True, "input_format": "audio"},
        },
    )
    document_step = replace(
        _runtime_step_with_order(3),
        input_config={
            "runtime_input": {"enabled": True, "input_format": "document"},
        },
    )
    steps = [no_input_step, audio_step, document_step]

    specs = build_runtime_step_input_specs(
        steps=steps,
        limits=FlowInputLimits(file_max_size_bytes=10_000, audio_max_size_bytes=10_000),
    )

    derived = primary_runtime_input_format([step.input_config for step in steps])

    assert derived == FlowRuntimeInputFormat.AUDIO
    assert derived == specs[audio_step.step_id].runtime_input.input_format
