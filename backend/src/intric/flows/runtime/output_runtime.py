from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from intric.files.file_models import FileCreate, FileType
from intric.flows.domain.flow import JsonObject
from intric.flows.output_processing import JsonStructuredValue
from intric.flows.principal import FlowPrincipal
from intric.flows.runtime.document_rendering.limits import (
    DEFAULT_DOCUMENT_RENDER_LIMITS,
    DocumentRenderLimits,
    ensure_source_within_limits,
)
from intric.flows.runtime.models import StepDiagnostic
from intric.flows.runtime.output_formats import resolve_format_spec
from intric.flows.runtime.output_formats.base import (
    OutputFormatProcessingContext,
    ParseJsonOutputFn,
    RenderDocumentFn,
    RenderedOutputArtifact,
    RenderStructuredDocumentFn,
    ValidateAgainstContractFn,
)


class RuntimeOutputStep(Protocol):
    @property
    def step_order(self) -> int: ...

    @property
    def output_type(self) -> str: ...

    @property
    def output_contract(self) -> JsonObject | None: ...


class RuntimeOutputRun(Protocol):
    @property
    def tenant_id(self) -> Any: ...


@dataclass(frozen=True, slots=True)
class TypedOutputProcessingResult:
    structured_output: JsonStructuredValue | None
    artifacts: list[dict[str, Any]] | None
    diagnostics: list[StepDiagnostic]


@dataclass(frozen=True)
class OutputRuntimeDeps:
    file_repo: Any
    user_id: Any
    compile_validators: Callable[[list[Any]], dict[tuple[str, int], Any]]
    parse_json_output: ParseJsonOutputFn
    validate_against_contract: ValidateAgainstContractFn
    render_document: RenderDocumentFn
    render_structured_document: RenderStructuredDocumentFn
    document_render_limits: DocumentRenderLimits = DEFAULT_DOCUMENT_RENDER_LIMITS
    principal: FlowPrincipal | None = None


async def process_typed_output(
    *,
    full_text: str,
    step: RuntimeOutputStep,
    run: RuntimeOutputRun,
    deps: OutputRuntimeDeps,
) -> TypedOutputProcessingResult:
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
    run: RuntimeOutputRun,
    deps: OutputRuntimeDeps,
) -> list[dict[str, str | int]]:
    checksum = hashlib.sha256(artifact.blob).hexdigest()
    file_record = await deps.file_repo.add(
        FileCreate.model_validate(
            {
                "file_type": FileType.DOCUMENT,
                "blob": artifact.blob,
                "name": artifact.filename,
                "mimetype": artifact.mimetype,
                "checksum": checksum,
                "size": len(artifact.blob),
                **(
                    deps.principal.file_owner_fields()
                    if deps.principal is not None
                    else {"user_id": deps.user_id}
                ),
                "tenant_id": run.tenant_id,
            }
        )
    )
    return [
        {
            "file_id": str(file_record.id),
            "name": artifact.filename,
            "mimetype": artifact.mimetype,
            "size": len(artifact.blob),
            "checksum": checksum,
            "file_type": FileType.DOCUMENT.value,
        }
    ]
