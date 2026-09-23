from __future__ import annotations

import hashlib
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from uuid import UUID

from eneo.files.file_models import FileInfo, FileType
from eneo.files.file_repo import FileRepository
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.domain.runtime import StepDiagnostic
from eneo.flows.enums import FlowStepPhase
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunRepository,
    flow_run_execution_owner,
)
from eneo.flows.output_processing import StructuredOutputValue
from eneo.flows.runtime.document_rendering.limits import (
    DEFAULT_DOCUMENT_RENDER_LIMITS,
    DocumentRenderLimits,
    ensure_source_within_limits,
)
from eneo.flows.runtime.generated_file_names import GeneratedFileNames
from eneo.flows.runtime.output_formats import resolve_format_spec
from eneo.flows.runtime.output_formats.base import (
    OutputFormatProcessingContext,
    ParseJsonOutputFn,
    RenderDocumentFn,
    RenderedOutputArtifact,
    RenderStructuredDocumentFn,
    ValidateAgainstContractFn,
)
from eneo.flows.runtime.step_deadline import record_step_phase


class RuntimeOutputStep(Protocol):
    @property
    def step_order(self) -> int: ...

    @property
    def output_type(self) -> str: ...

    @property
    def output_contract(self) -> FlowPersistedJsonObject | None: ...


class RuntimeOutputRun(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def tenant_id(self) -> UUID: ...


class RuntimeOutputFileService(Protocol):
    @property
    def repo(self) -> FileRepository: ...

    async def save_generated_file(
        self,
        *,
        payload: bytes,
        name: str,
        mimetype: str,
        file_type: FileType,
    ) -> FileInfo: ...


async def save_generated_flow_file(
    *,
    file_service: RuntimeOutputFileService,
    run: RuntimeOutputRun,
    payload: bytes,
    name: str,
    mimetype: str,
    file_type: FileType,
) -> FileInfo:
    session = (
        file_service.repo.session
        if flow_run_execution_owner.get() is not None
        else None
    )
    async with (
        session.begin()
        if session is not None and not session.in_transaction()
        else nullcontext()
    ):
        if session is not None:
            await FlowRunRepository(session=session).lock_execution_ownership(
                run_id=run.id, tenant_id=run.tenant_id
            )
        return await file_service.save_generated_file(
            payload=payload, name=name, mimetype=mimetype, file_type=file_type
        )


@dataclass(frozen=True, slots=True)
class TypedOutputProcessingResult:
    structured_output: StructuredOutputValue | None
    artifacts: list[dict[str, str | int]] | None
    diagnostics: list[StepDiagnostic]


@dataclass(frozen=True)
class OutputRuntimeDeps:
    file_service: RuntimeOutputFileService
    compile_validators: Callable[[list[Any]], dict[tuple[str, int], Any]]
    parse_json_output: ParseJsonOutputFn
    validate_against_contract: ValidateAgainstContractFn
    render_document: RenderDocumentFn
    render_structured_document: RenderStructuredDocumentFn
    file_names: GeneratedFileNames
    document_render_limits: DocumentRenderLimits = DEFAULT_DOCUMENT_RENDER_LIMITS


async def process_typed_output(
    *,
    full_text: str,
    step: RuntimeOutputStep,
    run: RuntimeOutputRun,
    deps: OutputRuntimeDeps,
) -> TypedOutputProcessingResult:
    record_step_phase(FlowStepPhase.FINALIZATION)
    artifacts: list[dict[str, Any]] | None = None

    compiled = deps.compile_validators([step])
    context = OutputFormatProcessingContext(
        parse_json_output=deps.parse_json_output,
        validate_against_contract=deps.validate_against_contract,
        render_document=deps.render_document,
        render_structured_document=deps.render_structured_document,
        ensure_source_within_limits=lambda text: ensure_source_within_limits(
            text,
            limits=deps.document_render_limits,
        ),
        json_contract_validation_enabled=("output", step.step_order) in compiled,
    )
    format_result = resolve_format_spec(step.output_type).process_model_output(
        full_text,
        step_order=step.step_order,
        output_contract=step.output_contract,
        context=context,
    )
    if format_result.artifact is not None:
        artifacts = await _persist_rendered_artifact(
            artifact=format_result.artifact,
            step=step,
            run=run,
            deps=deps,
        )

    return TypedOutputProcessingResult(
        structured_output=format_result.structured_output,
        artifacts=artifacts,
        diagnostics=list(format_result.diagnostics),
    )


async def _persist_rendered_artifact(
    *,
    artifact: RenderedOutputArtifact,
    step: RuntimeOutputStep,
    run: RuntimeOutputRun,
    deps: OutputRuntimeDeps,
) -> list[dict[str, str | int]]:
    checksum = hashlib.sha256(artifact.blob).hexdigest()
    name = deps.file_names.name(
        step_order=step.step_order, output_type=step.output_type
    )
    file_record = await save_generated_flow_file(
        file_service=deps.file_service,
        run=run,
        payload=artifact.blob,
        name=name,
        mimetype=artifact.mimetype,
        file_type=FileType.DOCUMENT,
    )
    return [
        {
            "file_id": str(file_record.id),
            "name": name,
            "mimetype": artifact.mimetype,
            "size": len(artifact.blob),
            "checksum": checksum,
            "file_type": FileType.DOCUMENT.value,
        }
    ]
