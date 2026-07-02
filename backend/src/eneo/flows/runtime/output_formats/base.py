from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.output_processing import (
    StructuredOutputValue,
    prune_extras_to_strict_schema,
)
from eneo.flows.runtime.models import StepDiagnostic

_MAX_DROPPED_PATHS_REPORTED = 20
_MAX_DROPPED_PATH_LENGTH = 200
_MAX_DROPPED_PATHS_MESSAGE_LENGTH = 1600


class ParseJsonOutputFn(Protocol):
    def __call__(self, raw_text: str, /) -> StructuredOutputValue: ...


class ValidateAgainstContractFn(Protocol):
    def __call__(
        self,
        data: object,
        schema: FlowPersistedJsonObject,
        *,
        label: str,
    ) -> None: ...


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
        data: StructuredOutputValue,
        output_type: str,
        *,
        step_order: int,
        schema: FlowPersistedJsonObject | None = None,
    ) -> tuple[bytes, str, str]: ...


class EnsureSourceWithinLimitsFn(Protocol):
    def __call__(self, text: str) -> None: ...


@dataclass(frozen=True, slots=True)
class RenderedOutputArtifact:
    blob: bytes
    mimetype: str
    filename: str


@dataclass(frozen=True, slots=True)
class OutputFormatProcessingResult:
    structured_output: StructuredOutputValue | None = None
    artifact: RenderedOutputArtifact | None = None
    diagnostics: tuple[StepDiagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class OutputFormatProcessingContext:
    parse_json_output: ParseJsonOutputFn
    validate_against_contract: ValidateAgainstContractFn
    render_document: RenderDocumentFn
    render_structured_document: RenderStructuredDocumentFn
    ensure_source_within_limits: EnsureSourceWithinLimitsFn
    # JSON preserves the existing compiled-validator gate; document contracts validate directly.
    json_contract_validation_enabled: bool


class OutputFormatSpec(Protocol):
    def prompt_instructions(
        self, output_contract: FlowPersistedJsonObject | None
    ) -> tuple[str, ...]: ...

    def should_request_native_json_object_mode(
        self, output_contract: FlowPersistedJsonObject | None
    ) -> bool: ...

    def process_model_output(
        self,
        full_text: str,
        *,
        step_order: int,
        output_contract: FlowPersistedJsonObject | None,
        context: OutputFormatProcessingContext,
    ) -> OutputFormatProcessingResult: ...


def append_output_format_instructions(prompt: str, instructions: Sequence[str]) -> str:
    if not instructions:
        return prompt
    suffix = "\n".join(instructions)
    return f"{prompt}\n\n{suffix}" if prompt.strip() else suffix


def schema_yields_top_level_object(schema: FlowPersistedJsonObject) -> bool:
    raw_type = schema.get("type")
    if isinstance(raw_type, str):
        return raw_type == "object"
    if isinstance(raw_type, list):
        declared = {
            item for item in cast(list[object], raw_type) if isinstance(item, str)
        }
        return "object" in declared and "array" not in declared
    if isinstance(schema.get("properties"), dict):
        return True
    if "items" in schema:
        return False
    return False


def json_schema_instructions(
    output_contract: FlowPersistedJsonObject | None,
) -> tuple[str, ...]:
    instructions = (
        "Return ONLY valid JSON.",
        "Do not include markdown code fences, commentary, or any surrounding text.",
        "The top-level JSON value must be an object or array.",
    )
    if output_contract is None:
        return instructions
    schema_json = json.dumps(output_contract, ensure_ascii=False, sort_keys=True)
    return (
        *instructions,
        "Follow this JSON Schema exactly:",
        schema_json,
    )


def document_prompt_instructions(
    *, artifact_name: str, output_contract: FlowPersistedJsonObject | None
) -> tuple[str, ...]:
    if output_contract is None:
        return (
            f"The system will render your answer into a {artifact_name} file after you respond.",
            "Return only the document body as Markdown/plain text content.",
            "Do not output binary file contents, base64, XML/ZIP internals, or PDF object syntax.",
            "For PDF output specifically, do not start the response with %PDF-.",
        )
    schema_json = json.dumps(output_contract, ensure_ascii=False, sort_keys=True)
    return (
        f"The system will validate your JSON and render it into a {artifact_name} file after you respond.",
        "Return ONLY valid JSON.",
        "Do not include markdown code fences, commentary, or any surrounding text.",
        "The top-level JSON value must be an object or array.",
        "Use plain text for JSON string values; do not include Markdown formatting markers inside strings.",
        "Follow this JSON Schema exactly:",
        schema_json,
    )


def document_prefers_native_json_object_mode(
    output_contract: FlowPersistedJsonObject | None,
) -> bool:
    if output_contract is None:
        return False
    return schema_yields_top_level_object(output_contract)


def prune_model_output_extras(
    structured_output: StructuredOutputValue,
    output_contract: FlowPersistedJsonObject,
) -> tuple[StepDiagnostic, ...]:
    result = prune_extras_to_strict_schema(structured_output, output_contract)
    if not result.dropped_paths:
        return ()
    return (
        StepDiagnostic(
            code="typed_output_extra_properties_dropped",
            message=_format_dropped_paths_message(result.dropped_paths),
            severity="warning",
        ),
    )


def process_structured_document_output(
    full_text: str,
    *,
    output_type: str,
    step_order: int,
    output_contract: FlowPersistedJsonObject,
    context: OutputFormatProcessingContext,
) -> OutputFormatProcessingResult:
    structured_output = context.parse_json_output(full_text)
    diagnostics = prune_model_output_extras(structured_output, output_contract)
    context.validate_against_contract(
        structured_output,
        output_contract,
        label=f"Step {step_order} output",
    )
    blob, mimetype, filename = context.render_structured_document(
        structured_output,
        output_type,
        step_order=step_order,
        schema=output_contract,
    )
    return OutputFormatProcessingResult(
        structured_output=structured_output,
        artifact=RenderedOutputArtifact(
            blob=blob,
            mimetype=mimetype,
            filename=filename,
        ),
        diagnostics=diagnostics,
    )


def render_document_output(
    full_text: str,
    *,
    output_type: str,
    step_order: int,
    context: OutputFormatProcessingContext,
) -> OutputFormatProcessingResult:
    blob, mimetype, filename = context.render_document(
        full_text,
        output_type,
        step_order=step_order,
    )
    return OutputFormatProcessingResult(
        artifact=RenderedOutputArtifact(
            blob=blob,
            mimetype=mimetype,
            filename=filename,
        )
    )


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
