from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from intric.files.file_models import File
from intric.flows.flow_input_limits import FlowInputLimits, effective_runtime_max_files
from intric.flows.principal import FlowPrincipal
from intric.flows.runtime.models import RuntimeStep
from intric.flows.runtime_input import (
    build_runtime_input_config,
    runtime_input_accept_mimetypes,
)
from intric.main.exceptions import BadRequestException

FLOW_RUN_ORCHESTRATION_INPUT_KEYS = frozenset(
    {"expected_flow_version", "file_ids", "step_inputs"}
)


class _FileRepositoryProtocol(Protocol):
    async def get_list_by_id_and_user(
        self,
        ids: list[UUID],
        user_id: UUID,
        include_transcription: bool = True,
    ) -> list[File]: ...

    async def get_list_by_id_for_owner(
        self,
        *,
        ids: list[UUID],
        owner_type: str,
        owner_user_id: UUID | None = None,
        owner_api_key_id: UUID | None = None,
        include_transcription: bool = True,
    ) -> list[File]: ...


@dataclass(frozen=True)
class RuntimeStepInputSpec:
    step: RuntimeStep
    accepted_mimetypes: list[str]
    max_files: int | None


def build_runtime_step_input_specs(
    *,
    steps: list[RuntimeStep],
    limits: FlowInputLimits,
) -> dict[UUID, RuntimeStepInputSpec]:
    specs: dict[UUID, RuntimeStepInputSpec] = {}
    for step in steps:
        runtime_input = build_runtime_input_config(step.input_config)
        if not runtime_input.enabled:
            continue
        specs[step.step_id] = RuntimeStepInputSpec(
            step=step,
            accepted_mimetypes=runtime_input_accept_mimetypes(runtime_input),
            max_files=effective_runtime_max_files(
                input_type=runtime_input.input_format,
                step_max_files=runtime_input.max_files,
                limits=limits,
            ),
        )
    return specs


def normalize_step_inputs_payload(
    raw_step_inputs: Mapping[UUID, object] | None,
) -> dict[UUID, list[UUID]]:
    normalized: dict[UUID, list[UUID]] = {}
    if raw_step_inputs is None:
        return normalized

    for step_id, payload in raw_step_inputs.items():
        if not isinstance(payload, dict):
            raise BadRequestException(
                "Each step_inputs entry must be an object.",
                code="flow_run_invalid_step_inputs",
            )
        payload_dict = cast(dict[str, object], payload)
        file_ids = payload_dict.get("file_ids")
        if file_ids is None:
            normalized[step_id] = []
            continue
        if not isinstance(file_ids, list):
            raise BadRequestException(
                "Each step_inputs.file_ids value must be an array of UUIDs.",
                code="flow_run_invalid_step_inputs",
            )
        normalized_ids: list[UUID] = []
        for file_id in cast(list[object], file_ids):
            try:
                normalized_ids.append(UUID(str(file_id)))
            except (TypeError, ValueError) as exc:
                raise BadRequestException(
                    "Each step_inputs.file_ids value must be a UUID.",
                    code="flow_run_invalid_step_inputs",
                ) from exc
        normalized[step_id] = sorted(set(normalized_ids), key=str)

    return dict(sorted(normalized.items(), key=lambda item: str(item[0])))


async def validate_submitted_step_inputs(
    *,
    steps: list[RuntimeStep],
    specs: dict[UUID, RuntimeStepInputSpec],
    normalized_step_inputs: dict[UUID, list[UUID]],
    file_repo: _FileRepositoryProtocol | None,
    user_id: UUID,
    principal: FlowPrincipal | None = None,
) -> None:
    step_by_id = {step.step_id: step for step in steps}
    aggregate_count = 0

    for step_id, requested_file_ids in normalized_step_inputs.items():
        step = step_by_id.get(step_id)
        if step is None:
            raise BadRequestException(
                "Unknown step id in step_inputs.",
                code="flow_run_unknown_step_input",
                context={"step_id": str(step_id)},
            )

        runtime_input = build_runtime_input_config(step.input_config)
        if not runtime_input.enabled:
            raise BadRequestException(
                "Runtime input is disabled for the requested step.",
                code="flow_run_runtime_input_disabled",
                context={"step_id": str(step_id)},
            )

        spec = specs[step_id]
        if spec.max_files is not None and len(requested_file_ids) > spec.max_files:
            raise BadRequestException(
                "Too many files were submitted for this step.",
                code="flow_run_step_input_max_files_exceeded",
                context={
                    "step_id": str(step_id),
                    "max_files": spec.max_files,
                    "file_count": len(requested_file_ids),
                },
            )
        aggregate_count += len(requested_file_ids)

        if file_repo is None or not requested_file_ids:
            continue

        if principal is not None and principal.is_service_key:
            files = await file_repo.get_list_by_id_for_owner(
                ids=requested_file_ids,
                owner_type=principal.principal_type.value,
                owner_user_id=principal.principal_user_id,
                owner_api_key_id=principal.principal_api_key_id,
                include_transcription=False,
            )
        else:
            files = await file_repo.get_list_by_id_and_user(
                ids=requested_file_ids,
                user_id=user_id,
                include_transcription=False,
            )
        resolved_ids = {file.id for file in files}
        missing_ids = [
            str(file_id)
            for file_id in requested_file_ids
            if file_id not in resolved_ids
        ]
        if missing_ids:
            raise BadRequestException(
                "One or more submitted runtime files are missing or not accessible.",
                code="flow_run_file_not_accessible",
                context={"step_id": str(step_id), "file_ids": missing_ids},
            )

        if spec.accepted_mimetypes:
            allowed = {mimetype.lower() for mimetype in spec.accepted_mimetypes}
            for file in files:
                mimetype = (file.mimetype or "").split(";", 1)[0].strip().lower()
                if mimetype and mimetype in allowed:
                    continue
                raise BadRequestException(
                    "One or more submitted runtime files use a rejected MIME type.",
                    code="flow_run_step_input_mimetype_rejected",
                    context={
                        "step_id": str(step_id),
                        "file_id": str(file.id),
                        "mimetype": mimetype or "missing",
                    },
                )

    required_missing = [
        str(step_id)
        for step_id, spec in specs.items()
        if build_runtime_input_config(spec.step.input_config).required
        and len(normalized_step_inputs.get(step_id, [])) == 0
    ]
    if required_missing:
        raise BadRequestException(
            "Required runtime input files are missing.",
            code="flow_run_required_step_input_missing",
            context={"step_ids": required_missing},
        )

    aggregate_limit = aggregate_runtime_file_limit(specs=specs)
    if aggregate_limit is not None and aggregate_count > aggregate_limit:
        raise BadRequestException(
            "Submitted runtime files exceed the aggregate file limit for this flow.",
            code="flow_run_aggregate_max_files_exceeded",
            context={
                "aggregate_max_files": aggregate_limit,
                "file_count": aggregate_count,
            },
        )


def serialize_step_inputs_payload(
    step_inputs: dict[UUID, list[UUID]],
) -> dict[str, dict[str, list[str]]]:
    return {
        str(step_id): {
            "file_ids": [str(file_id) for file_id in file_ids],
        }
        for step_id, file_ids in step_inputs.items()
    }


def aggregate_runtime_file_limit(
    *, specs: dict[UUID, RuntimeStepInputSpec]
) -> int | None:
    aggregate = 0
    for spec in specs.values():
        if spec.max_files is None:
            return None
        aggregate += spec.max_files
    return aggregate
