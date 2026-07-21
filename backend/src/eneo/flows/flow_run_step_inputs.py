from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, TypedDict
from uuid import UUID

from eneo.files.file_models import File
from eneo.flows.domain.flow import FlowRuntimeInputConfig
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_input_limits import (
    FlowInputLimits,
    effective_flow_input_limit,
    effective_runtime_max_files,
)
from eneo.flows.principal import FlowPrincipal
from eneo.flows.runtime_input import (
    build_runtime_input_config,
    runtime_input_accept_mimetypes,
)


class _FileRepositoryProtocol(Protocol):
    async def get_list_by_id_for_owner(
        self,
        *,
        ids: list[UUID],
        owner_type: str,
        owner_user_id: UUID | None = None,
        owner_service_id: UUID | None = None,
        tenant_id: UUID | None = None,
        include_transcription: bool = True,
    ) -> list[File]: ...


class _RuntimeUploadRepositoryProtocol(Protocol):
    async def list_bound_file_ids_for_owner(
        self,
        *,
        file_ids: list[UUID],
        flow_id: UUID,
        tenant_id: UUID,
        principal: FlowPrincipal,
        lock_for_binding: bool = False,
    ) -> set[UUID]: ...


@dataclass(frozen=True)
class RuntimeStepInputSpec:
    step: RuntimeStep
    runtime_input: FlowRuntimeInputConfig
    accepted_mimetypes: list[str]
    max_files: int | None
    max_file_size_bytes: int


@dataclass(frozen=True)
class FlowRunStepInputFiles:
    file_ids: tuple[UUID, ...] = ()


class FlowRunStepInputFileProjection(TypedDict):
    step_id: UUID
    step_order: int
    file_ids: Sequence[UUID]


FlowRunStepInputs = Mapping[UUID, FlowRunStepInputFiles]


def runtime_file_not_bound_to_flow_error(
    *, step_id: UUID, file_ids: Sequence[UUID]
) -> FlowBadRequestException:
    return FlowBadRequestException(
        "One or more submitted runtime files were not uploaded for this flow.",
        code=FlowApiErrorCode.RUN_FILE_NOT_BOUND_TO_FLOW,
        context={
            "step_id": str(step_id),
            "file_ids": [str(file_id) for file_id in file_ids],
        },
    )


def build_runtime_step_input_specs(
    *,
    steps: Sequence[RuntimeStep],
    limits: FlowInputLimits,
) -> dict[UUID, RuntimeStepInputSpec]:
    specs: dict[UUID, RuntimeStepInputSpec] = {}
    for step in steps:
        runtime_input = build_runtime_input_config(step.input_config)
        if not runtime_input.enabled:
            continue
        specs[step.step_id] = RuntimeStepInputSpec(
            step=step,
            runtime_input=runtime_input,
            accepted_mimetypes=runtime_input_accept_mimetypes(runtime_input),
            max_files=effective_runtime_max_files(
                input_type=runtime_input.input_format,
                step_max_files=runtime_input.max_files,
                limits=limits,
            ),
            max_file_size_bytes=effective_flow_input_limit(
                input_type=runtime_input.input_format,
                limits=limits,
            ),
        )
    return specs


def normalize_step_inputs_payload(
    raw_step_inputs: FlowRunStepInputs | None,
) -> dict[UUID, list[UUID]]:
    normalized: dict[UUID, list[UUID]] = {}
    if raw_step_inputs is None:
        return normalized

    for step_id, payload in raw_step_inputs.items():
        normalized_ids: list[UUID] = []
        for file_id in payload.file_ids:
            try:
                normalized_ids.append(UUID(str(file_id)))
            except (TypeError, ValueError) as exc:
                raise FlowBadRequestException(
                    "Each step_inputs.file_ids value must be a UUID.",
                    code=FlowApiErrorCode.RUN_INVALID_STEP_INPUTS,
                ) from exc
        normalized[step_id] = list(dict.fromkeys(normalized_ids))

    return normalized


async def validate_submitted_step_inputs(
    *,
    flow_id: UUID,
    steps: list[RuntimeStep],
    specs: dict[UUID, RuntimeStepInputSpec],
    normalized_step_inputs: dict[UUID, list[UUID]],
    file_repo: _FileRepositoryProtocol,
    runtime_upload_repo: _RuntimeUploadRepositoryProtocol,
    principal: FlowPrincipal,
    tenant_id: UUID,
) -> None:
    step_by_id = {step.step_id: step for step in steps}
    aggregate_count = 0
    requested_ids_by_step: dict[UUID, list[UUID]] = {}

    for step_id, requested_file_ids in normalized_step_inputs.items():
        step = step_by_id.get(step_id)
        if step is None:
            raise FlowBadRequestException(
                "Unknown step id in step_inputs.",
                code=FlowApiErrorCode.RUN_UNKNOWN_STEP_INPUT,
                context={"step_id": str(step_id)},
            )

        spec = specs.get(step_id)
        if spec is None or not spec.runtime_input.enabled:
            raise FlowBadRequestException(
                "Runtime input is disabled for the requested step.",
                code=FlowApiErrorCode.RUN_RUNTIME_INPUT_DISABLED,
                context={"step_id": str(step_id)},
            )

        if spec.max_files is not None and len(requested_file_ids) > spec.max_files:
            raise FlowBadRequestException(
                "Too many files were submitted for this step.",
                code=FlowApiErrorCode.RUN_STEP_INPUT_MAX_FILES_EXCEEDED,
                context={
                    "step_id": str(step_id),
                    "max_files": spec.max_files,
                    "file_count": len(requested_file_ids),
                },
            )
        aggregate_count += len(requested_file_ids)
        if requested_file_ids:
            requested_ids_by_step[step_id] = requested_file_ids

    if requested_ids_by_step:
        all_requested_file_ids = list(
            dict.fromkeys(
                file_id
                for requested_file_ids in requested_ids_by_step.values()
                for file_id in requested_file_ids
            )
        )
        files = await file_repo.get_list_by_id_for_owner(
            ids=all_requested_file_ids,
            owner_type=principal.principal_type.value,
            owner_user_id=principal.principal_user_id,
            owner_service_id=principal.principal_service_id,
            tenant_id=tenant_id,
            include_transcription=False,
        )
        file_by_id = {file.id: file for file in files}
        resolved_ids = set(file_by_id)

        for step_id, requested_file_ids in requested_ids_by_step.items():
            missing_ids = [
                str(file_id)
                for file_id in requested_file_ids
                if file_id not in resolved_ids
            ]
            if missing_ids:
                raise FlowBadRequestException(
                    "One or more submitted runtime files are missing or not accessible.",
                    code=FlowApiErrorCode.RUN_FILE_NOT_ACCESSIBLE,
                    context={"step_id": str(step_id), "file_ids": missing_ids},
                )

        bound_ids = await runtime_upload_repo.list_bound_file_ids_for_owner(
            file_ids=all_requested_file_ids,
            flow_id=flow_id,
            tenant_id=tenant_id,
            principal=principal,
            lock_for_binding=True,
        )

        for step_id, requested_file_ids in requested_ids_by_step.items():
            spec = specs[step_id]
            step_files = [file_by_id[file_id] for file_id in requested_file_ids]

            unbound_ids = [
                file_id for file_id in requested_file_ids if file_id not in bound_ids
            ]
            if unbound_ids:
                raise runtime_file_not_bound_to_flow_error(
                    step_id=step_id,
                    file_ids=unbound_ids,
                )

            for file in step_files:
                if file.size <= spec.max_file_size_bytes:
                    continue
                raise FlowBadRequestException(
                    "One or more submitted runtime files exceed the current flow input size limit.",
                    code=FlowApiErrorCode.RUN_STEP_INPUT_FILE_TOO_LARGE,
                    context={
                        "step_id": str(step_id),
                        "file_id": str(file.id),
                        "size_bytes": file.size,
                        "max_file_size_bytes": spec.max_file_size_bytes,
                    },
                )

            if not spec.accepted_mimetypes:
                continue

            allowed = {mimetype.lower() for mimetype in spec.accepted_mimetypes}
            for file in step_files:
                mimetype = (file.mimetype or "").split(";", 1)[0].strip().lower()
                if mimetype and mimetype in allowed:
                    continue
                raise FlowBadRequestException(
                    "One or more submitted runtime files use a rejected MIME type.",
                    code=FlowApiErrorCode.RUN_STEP_INPUT_MIMETYPE_REJECTED,
                    context={
                        "step_id": str(step_id),
                        "file_id": str(file.id),
                        "mimetype": mimetype or "missing",
                    },
                )

    required_missing = [
        str(step_id)
        for step_id, spec in specs.items()
        if spec.runtime_input.required
        and len(normalized_step_inputs.get(step_id, [])) == 0
    ]
    if required_missing:
        raise FlowBadRequestException(
            "Required runtime input files are missing.",
            code=FlowApiErrorCode.RUN_REQUIRED_STEP_INPUT_MISSING,
            context={"step_ids": required_missing},
        )

    aggregate_limit = aggregate_runtime_file_limit(specs=specs)
    if aggregate_limit is not None and aggregate_count > aggregate_limit:
        raise FlowBadRequestException(
            "Submitted runtime files exceed the aggregate file limit for this flow.",
            code=FlowApiErrorCode.RUN_AGGREGATE_MAX_FILES_EXCEEDED,
            context={
                "aggregate_max_files": aggregate_limit,
                "file_count": aggregate_count,
            },
        )


def aggregate_runtime_file_limit(
    *, specs: dict[UUID, RuntimeStepInputSpec]
) -> int | None:
    aggregate = 0
    for spec in specs.values():
        if spec.max_files is None:
            return None
        aggregate += spec.max_files
    return aggregate
