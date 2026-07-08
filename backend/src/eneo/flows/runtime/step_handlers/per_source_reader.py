from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, cast
from uuid import UUID

from eneo.flows.domain.flow import FlowRun
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.runtime.models import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
)
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.step_execution_runtime import (
    StepExecutionRuntimeDeps,
    complete_step_execution,
)
from eneo.flows.runtime.step_handlers.base import (
    ListStepInputFileIdsFn,
    PrepareAssistantStepFn,
)
from eneo.flows.runtime.step_handlers.mapped_outputs import (
    mapped_output_diagnostics,
    mapped_rag_metadata,
    sum_optional_token_counts,
)
from eneo.flows.runtime_input import build_runtime_input_config
from eneo.flows.source_identity import without_runtime_source_identity_json_fields
from eneo.main.exceptions import TypedIOValidationException

logger = logging.getLogger(__name__)

# ponytail: this executor owns one AsyncSession; raise only after per-source
# calls get isolated session ownership.
PER_SOURCE_READER_CONCURRENCY = 1
PER_SOURCE_METADATA_PREVIEW_CHARS = 2000
PER_SOURCE_SOURCE_LABEL_MAX_CHARS = 120


@dataclass(frozen=True)
class PerSourceReaderCall:
    source_number: int
    file_id: UUID
    source_label: str
    output: StepExecutionOutput
    deps: StepExecutionRuntimeDeps
    elapsed_ms: int


def should_execute_per_source_reader(step: RuntimeStep) -> bool:
    runtime_input = build_runtime_input_config(step.input_config)
    return (
        runtime_input.enabled
        and runtime_input.execution_mode == "per_source"
        and step.input_source == "flow_input"
        and step.input_type in {"document", "file"}
        and step.output_type == "json"
    )


async def execute_per_source_reader(
    *,
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    version_metadata: dict[str, object] | None,
    attempt_no: int,
    prepare_assistant_step: PrepareAssistantStepFn,
    list_step_input_file_ids: ListStepInputFileIdsFn,
) -> StepExecutionResult:
    file_ids = await list_step_input_file_ids(
        step=step,
        run=run,
        attempt_no=attempt_no,
    )
    if _documents_item_schema(step.output_contract) is None:
        raise TypedIOValidationException(
            "Per-source document readers require a JSON output contract shaped "
            "as exactly one top-level documents[] array.",
            code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
        )
    per_call_step = replace(
        step,
        output_contract=without_runtime_source_identity_json_fields(
            step.output_contract
        ),
    )
    if not file_ids:
        prepared_step = await prepare_assistant_step(
            step=per_call_step,
            run=run,
            state=state,
            version_metadata=version_metadata,
            attempt_no=attempt_no,
            requested_file_ids_override=(),
        )
        output = await complete_step_execution(
            step=per_call_step,
            run=run,
            state=state,
            prepared=prepared_step.prepared,
            deps=prepared_step.deps,
        )
        return StepExecutionResult(output=output)

    per_source_calls: list[PerSourceReaderCall] = []
    for source_number, file_id in enumerate(file_ids, start=1):
        per_source_calls.append(
            await _execute_one_source(
                source_number=source_number,
                file_id=file_id,
                step=step,
                per_call_step=per_call_step,
                run=run,
                state=state,
                version_metadata=version_metadata,
                attempt_no=attempt_no,
                prepare_assistant_step=prepare_assistant_step,
            )
        )
    per_source_calls = _with_deduped_source_labels(per_source_calls)
    return StepExecutionResult(
        output=await _assemble_per_source_output(
            step=step,
            run=run,
            per_source_calls=per_source_calls,
        )
    )


async def _execute_one_source(
    *,
    source_number: int,
    file_id: UUID,
    step: RuntimeStep,
    per_call_step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    version_metadata: dict[str, object] | None,
    attempt_no: int,
    prepare_assistant_step: PrepareAssistantStepFn,
) -> PerSourceReaderCall:
    started = time.perf_counter()
    prepared_step = await prepare_assistant_step(
        step=per_call_step,
        run=run,
        state=state,
        version_metadata=version_metadata,
        attempt_no=attempt_no,
        requested_file_ids_override=(file_id,),
    )
    output = await complete_step_execution(
        step=per_call_step,
        run=run,
        state=state,
        prepared=prepared_step.prepared,
        deps=prepared_step.deps,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _raise_if_per_source_output_is_not_object(
        output=output,
        step_order=step.step_order,
        source_number=source_number,
    )
    return PerSourceReaderCall(
        source_number=source_number,
        file_id=file_id,
        source_label=_raw_source_label(source_number, output.runtime_input_metadata),
        output=output,
        deps=prepared_step.deps,
        elapsed_ms=elapsed_ms,
    )


async def _assemble_per_source_output(
    *,
    step: RuntimeStep,
    run: FlowRun,
    per_source_calls: list[PerSourceReaderCall],
) -> StepExecutionOutput:
    if not per_source_calls:
        raise TypedIOValidationException(
            f"Step {step.step_order}: per-source reader requires at least one source.",
            code=FlowApiErrorCode.TYPED_IO_EMPTY_EXTRACTION.value,
        )
    first_output = per_source_calls[0].output
    documents = [
        document
        for call in sorted(per_source_calls, key=lambda item: item.source_number)
        for document in _source_document_items(call)
    ]
    assembled_structured = {"documents": documents}
    full_text = json.dumps(assembled_structured, ensure_ascii=False)
    runtime_metadata = _per_source_runtime_metadata(per_source_calls)
    input_text = _per_source_input_text_summary(per_source_calls)
    first_deps = per_source_calls[0].deps
    input_payload_for_result: dict[str, Any] = {
        "text": input_text,
        "source_text": "",
        "input_source": first_output.input_source,
        "used_question_binding": first_output.used_question_binding,
        "runtime_input": runtime_metadata,
    }
    try:
        typed_output = await first_deps.process_typed_output(
            full_text=full_text,
            step=step,
            run=run,
        )
    except TypedIOValidationException as exc:
        raise first_deps.attach_typed_failure_context(
            exc,
            input_payload_for_result=input_payload_for_result,
            effective_prompt=first_output.effective_prompt,
        ) from exc
    persisted_text, generated_file_ids = await first_deps.apply_output_cap(
        text=full_text,
        run=run,
        step=step,
    )
    diagnostics = [
        StepDiagnostic(
            code="runtime_input_per_source_reader",
            message=(
                f"Step {step.step_order}: executed document reader once per "
                f"source ({len(per_source_calls)} source calls)."
            ),
            severity="info",
        ),
        *mapped_output_diagnostics(call.output for call in per_source_calls),
        *typed_output.diagnostics,
    ]
    final_structured_output: dict[str, Any] | list[Any] | None = (
        typed_output.structured_output
    )
    if final_structured_output is None:
        final_structured_output = assembled_structured
    return StepExecutionOutput(
        input_text=input_text,
        source_text="",
        input_source=first_output.input_source,
        used_question_binding=first_output.used_question_binding,
        full_text=full_text,
        persisted_text=persisted_text,
        generated_file_ids=generated_file_ids,
        tool_calls_metadata=_per_source_tool_metadata(per_source_calls),
        num_tokens_input=sum_optional_token_counts(
            call.output.num_tokens_input for call in per_source_calls
        ),
        num_tokens_output=sum_optional_token_counts(
            call.output.num_tokens_output for call in per_source_calls
        ),
        effective_prompt=first_output.effective_prompt,
        model_parameters_json={
            **first_output.model_parameters_json,
            "runtime_input_execution_mode": "per_source",
            "per_source_call_count": len(per_source_calls),
        },
        requested_model=first_output.requested_model,
        response_model=first_output.response_model,
        provider=first_output.provider,
        finish_reason=first_output.finish_reason,
        provider_response_id=None,
        contract_validation=first_output.contract_validation,
        structured_output=final_structured_output,
        diagnostics=diagnostics,
        artifacts=typed_output.artifacts,
        rag_metadata=_per_source_rag_metadata(per_source_calls),
        transcription_metadata=None,
        runtime_input_metadata=runtime_metadata,
        raw_completion_text=None,
    )


def _documents_item_schema(output_contract: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(output_contract, Mapping):
        return None
    properties = output_contract.get("properties")
    if not isinstance(properties, Mapping):
        return None
    typed_properties = cast(Mapping[str, object], properties)
    if tuple(typed_properties.keys()) != ("documents",):
        return None
    documents_schema = typed_properties["documents"]
    if not isinstance(documents_schema, Mapping):
        return None
    typed_documents_schema = cast(Mapping[str, object], documents_schema)
    if typed_documents_schema.get("type") != "array":
        return None
    item_schema = typed_documents_schema.get("items")
    if not isinstance(item_schema, Mapping):
        return None
    typed_item_schema = cast(Mapping[str, object], item_schema)
    if typed_item_schema.get("type") != "object":
        return None
    return dict(typed_item_schema)


def _raise_if_per_source_output_is_not_object(
    *,
    output: StepExecutionOutput,
    step_order: int,
    source_number: int,
) -> None:
    if isinstance(output.structured_output, dict):
        return
    raise TypedIOValidationException(
        f"Step {step_order}: per-source reader source {source_number} returned "
        "non-object JSON.",
        code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
    )


def _source_document_items(call: PerSourceReaderCall) -> list[dict[str, Any]]:
    structured_output = cast(dict[str, Any], call.output.structured_output)
    documents = structured_output.get("documents")
    if not isinstance(documents, list):
        raise TypedIOValidationException(
            f"Step output for source {call.source_number} must contain documents[].",
            code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
        )
    items: list[dict[str, Any]] = []
    for index, raw_item in enumerate(cast(list[object], documents), start=1):
        if not isinstance(raw_item, dict):
            raise TypedIOValidationException(
                f"Step output for source {call.source_number} documents[{index}] "
                "must be an object.",
                code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
            )
        item = dict(cast(dict[str, Any], raw_item))
        item["source_label"] = call.source_label
        item["source_file_id"] = str(call.file_id)
        items.append(item)
    return items


def _raw_source_label(
    source_number: int,
    runtime_input_metadata: dict[str, Any] | None,
) -> str:
    file_metadata = _first_runtime_file_metadata(runtime_input_metadata)
    if file_metadata is not None:
        raw_name = file_metadata.get("name")
        if isinstance(raw_name, str):
            printable_name = "".join(
                char if char.isprintable() else " " for char in raw_name
            )
            file_name = " ".join(printable_name.split())
            if file_name:
                return _cap_source_label(file_name, source_number=source_number)
    return f"Källa {source_number}"


def _cap_source_label(label: str, *, source_number: int) -> str:
    if len(label) <= PER_SOURCE_SOURCE_LABEL_MAX_CHARS:
        return label
    logger.info(
        "flow_per_source_reader_source_label_truncated",
        extra={
            "source_number": source_number,
            "source_label_chars": len(label),
            "display_char_cap": PER_SOURCE_SOURCE_LABEL_MAX_CHARS,
        },
    )
    return f"{label[: PER_SOURCE_SOURCE_LABEL_MAX_CHARS - 3].rstrip()}..."


def _with_deduped_source_labels(
    per_source_calls: list[PerSourceReaderCall],
) -> list[PerSourceReaderCall]:
    counts: dict[str, int] = {}
    deduped_calls: list[PerSourceReaderCall] = []
    for call in per_source_calls:
        count = counts.get(call.source_label, 0) + 1
        counts[call.source_label] = count
        source_label = (
            call.source_label if count == 1 else f"{call.source_label} ({count})"
        )
        deduped_calls.append(replace(call, source_label=source_label))
    return deduped_calls


def _first_runtime_file_metadata(
    runtime_input_metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(runtime_input_metadata, dict):
        return None
    files = runtime_input_metadata.get("files")
    if not isinstance(files, list) or not files:
        return None
    first_file = cast(list[object], files)[0]
    return cast(dict[str, Any], first_file) if isinstance(first_file, dict) else None


def _per_source_runtime_metadata(
    per_source_calls: list[PerSourceReaderCall],
) -> dict[str, Any]:
    files = [
        metadata
        for call in per_source_calls
        if (metadata := _first_runtime_file_metadata(call.output.runtime_input_metadata))
        is not None
    ]
    source_headers = [
        header
        for call in per_source_calls
        for header in _runtime_source_headers(call.output.runtime_input_metadata)
    ]
    return {
        "text": _per_source_input_text_summary(per_source_calls),
        "file_ids": [str(call.file_id) for call in per_source_calls],
        "files_count": len(per_source_calls),
        "files": files,
        "source_headers": source_headers,
        "total_file_size": sum(
            metadata["size"]
            for metadata in files
            if isinstance(metadata.get("size"), int)
        ),
        "extracted_text_length": sum(
            _runtime_text_length(call.output.runtime_input_metadata)
            for call in per_source_calls
        ),
        "input_format": _per_source_input_format(per_source_calls),
        "capture_mode": "runtime_input_per_source",
        "execution_mode": "per_source",
        "concurrency": PER_SOURCE_READER_CONCURRENCY,
        "per_source_calls": [
            _per_source_call_metadata(call) for call in per_source_calls
        ],
    }


def _runtime_source_headers(
    runtime_input_metadata: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(runtime_input_metadata, dict):
        return []
    headers = runtime_input_metadata.get("source_headers")
    if not isinstance(headers, list):
        return []
    return [
        cast(dict[str, Any], header)
        for header in cast(list[object], headers)
        if isinstance(header, dict)
    ]


def _runtime_text_length(runtime_input_metadata: dict[str, Any] | None) -> int:
    if not isinstance(runtime_input_metadata, dict):
        return 0
    value = runtime_input_metadata.get("extracted_text_length")
    return value if isinstance(value, int) else 0


def _per_source_input_format(per_source_calls: list[PerSourceReaderCall]) -> str:
    for call in per_source_calls:
        metadata = call.output.runtime_input_metadata
        if not isinstance(metadata, dict):
            continue
        input_format = metadata.get("input_format")
        if isinstance(input_format, str) and input_format:
            return input_format
    return "document"


def _per_source_call_metadata(call: PerSourceReaderCall) -> dict[str, Any]:
    runtime_input_metadata = call.output.runtime_input_metadata
    input_text = (
        runtime_input_metadata.get("text")
        if runtime_input_metadata is not None
        else None
    )
    input_text_value = input_text if isinstance(input_text, str) else call.output.input_text
    return {
        "source_number": call.source_number,
        "file_id": str(call.file_id),
        "source_label": call.source_label,
        "elapsed_ms": call.elapsed_ms,
        "input_text_length": len(input_text_value),
        "input_text_preview": input_text_value[:PER_SOURCE_METADATA_PREVIEW_CHARS],
        "num_tokens_input": call.output.num_tokens_input,
        "num_tokens_output": call.output.num_tokens_output,
        "diagnostics": [
            {
                "code": diagnostic.code,
                "message": diagnostic.message,
                "severity": diagnostic.severity,
            }
            for diagnostic in call.output.diagnostics
        ],
    }


def _per_source_input_text_summary(per_source_calls: list[PerSourceReaderCall]) -> str:
    return (
        f"[per-source runtime input: {len(per_source_calls)} source calls; "
        "see runtime_input.per_source_calls for model input previews]"
    )


def _per_source_tool_metadata(
    per_source_calls: list[PerSourceReaderCall],
) -> dict[str, Any]:
    return {
        "execution_mode": "per_source",
        "sources": [
            {
                "source_number": call.source_number,
                "file_id": str(call.file_id),
                "source_label": call.source_label,
                "tool_calls": call.output.tool_calls_metadata,
            }
            for call in per_source_calls
        ],
    }


def _per_source_rag_metadata(
    per_source_calls: list[PerSourceReaderCall],
) -> dict[str, Any] | None:
    return mapped_rag_metadata(
        execution_mode="per_source",
        collection_key="sources",
        outputs=(call.output for call in per_source_calls),
    )
