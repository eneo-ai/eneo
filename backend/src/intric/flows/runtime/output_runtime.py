from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from intric.files.file_models import FileCreate, FileType
from intric.flows.output_processing import prune_extras_to_strict_schema
from intric.flows.principal import FlowPrincipal
from intric.flows.runtime.document_rendering.limits import (
    DEFAULT_DOCUMENT_RENDER_LIMITS,
    DocumentRenderLimits,
    ensure_source_within_limits,
)
from intric.flows.runtime.models import StepDiagnostic

_MAX_DROPPED_PATHS_REPORTED = 20
_MAX_DROPPED_PATH_LENGTH = 200
_MAX_DROPPED_PATHS_MESSAGE_LENGTH = 1600


class RuntimeOutputStep(Protocol):
    @property
    def step_order(self) -> int: ...

    @property
    def output_type(self) -> str: ...

    @property
    def output_contract(self) -> dict[str, Any] | None: ...


class RuntimeOutputRun(Protocol):
    @property
    def tenant_id(self) -> Any: ...


class ValidateAgainstContractFn(Protocol):
    def __call__(
        self,
        data: Any,
        schema: dict[str, Any],
        *,
        label: str,
    ) -> None: ...


def _is_pdf_bytes_text(text: str) -> bool:
    return text.lstrip().startswith("%PDF-")


def _pdf_bytes_from_text(text: str) -> bytes:
    return text.lstrip().encode("latin-1", errors="replace")


class RenderDocumentFn(Protocol):
    def __call__(
        self,
        text: str,
        output_type: str,
        *,
        step_order: int,
    ) -> tuple[bytes, str, str]: ...


class RenderStructuredDocumentFn(Protocol):
    def __call__(
        self,
        data: dict[str, Any] | list[Any],
        output_type: str,
        *,
        step_order: int,
        schema: dict[str, Any] | None = None,
    ) -> tuple[bytes, str, str]: ...


@dataclass(frozen=True, slots=True)
class TypedOutputProcessingResult:
    structured_output: dict[str, Any] | list[Any] | None
    artifacts: list[dict[str, Any]] | None
    diagnostics: list[StepDiagnostic]


@dataclass(frozen=True)
class OutputRuntimeDeps:
    file_repo: Any
    user_id: Any
    compile_validators: Callable[[list[Any]], dict[tuple[str, int], Any]]
    parse_json_output: Callable[[str], dict[str, Any] | list[Any]]
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
    structured_output: dict[str, Any] | list[Any] | None = None
    artifacts: list[dict[str, Any]] | None = None
    diagnostics: list[StepDiagnostic] = []

    compiled = deps.compile_validators([step])

    if step.output_type == "json":
        structured_output = deps.parse_json_output(full_text)
        validator = compiled.get(("output", step.step_order))
        if validator:
            # Model output only; user inputs and review checkpoint edits stay strict.
            diagnostics.extend(
                _prune_model_output_extras(
                    structured_output,
                    step.output_contract or {},
                )
            )
            deps.validate_against_contract(
                structured_output,
                step.output_contract or {},
                label=f"Step {step.step_order} output",
            )
    elif step.output_type in ("pdf", "docx"):
        if step.output_contract is not None:
            structured_output = deps.parse_json_output(full_text)
            # Model output only; user inputs and review checkpoint edits stay strict.
            diagnostics.extend(
                _prune_model_output_extras(
                    structured_output,
                    step.output_contract,
                )
            )
            deps.validate_against_contract(
                structured_output,
                step.output_contract,
                label=f"Step {step.step_order} output",
            )
            blob, mimetype, filename = deps.render_structured_document(
                structured_output,
                step.output_type,
                step_order=step.step_order,
                schema=step.output_contract,
            )
        elif step.output_type == "pdf" and _is_pdf_bytes_text(full_text):
            ensure_source_within_limits(full_text, limits=deps.document_render_limits)
            blob = _pdf_bytes_from_text(full_text)
            mimetype = "application/pdf"
            filename = f"step_{step.step_order}_output.pdf"
        else:
            blob, mimetype, filename = deps.render_document(
                full_text,
                step.output_type,
                step_order=step.step_order,
            )
        file_record = await deps.file_repo.add(
            FileCreate.model_validate(
                {
                    "file_type": FileType.DOCUMENT,
                    "blob": blob,
                    "name": filename,
                    "mimetype": mimetype,
                    "checksum": hashlib.sha256(blob).hexdigest(),
                    "size": len(blob),
                    **(
                        deps.principal.file_owner_fields()
                        if deps.principal is not None
                        else {"user_id": deps.user_id}
                    ),
                    "tenant_id": run.tenant_id,
                }
            )
        )
        artifacts = [
            {
                "file_id": str(file_record.id),
                "name": filename,
                "mimetype": mimetype,
                "size": len(blob),
                "checksum": hashlib.sha256(blob).hexdigest(),
                "file_type": FileType.DOCUMENT.value,
            }
        ]

    return TypedOutputProcessingResult(
        structured_output=structured_output,
        artifacts=artifacts,
        diagnostics=diagnostics,
    )


def _prune_model_output_extras(
    structured_output: dict[str, Any] | list[Any],
    output_contract: dict[str, Any],
) -> list[StepDiagnostic]:
    result = prune_extras_to_strict_schema(structured_output, output_contract)
    if not result.dropped_paths:
        return []
    return [
        StepDiagnostic(
            code="typed_output_extra_properties_dropped",
            message=_format_dropped_paths_message(result.dropped_paths),
            severity="warning",
        )
    ]


def _format_dropped_paths_message(dropped_paths: tuple[str, ...]) -> str:
    shown_paths = tuple(
        _truncate_path(path) for path in dropped_paths[:_MAX_DROPPED_PATHS_REPORTED]
    )
    suffix = ""
    hidden_count = len(dropped_paths) - len(shown_paths)
    if hidden_count > 0:
        suffix = f"; {hidden_count} more omitted"
    message = (
        f"Dropped {len(dropped_paths)} undeclared field"
        f"{'' if len(dropped_paths) == 1 else 's'}: {', '.join(shown_paths)}{suffix}"
    )
    return message[:_MAX_DROPPED_PATHS_MESSAGE_LENGTH]


def _truncate_path(path: str) -> str:
    if len(path) <= _MAX_DROPPED_PATH_LENGTH:
        return path
    return f"{path[: _MAX_DROPPED_PATH_LENGTH - 3]}..."
