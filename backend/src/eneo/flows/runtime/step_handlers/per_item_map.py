from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from eneo.flows.domain.flow import FlowRun
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.runtime.models import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
    StepInputValue,
)
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.step_execution_runtime import (
    StepExecutionRuntimeDeps,
    complete_step_execution,
)
from eneo.flows.runtime.step_handlers.base import PrepareAssistantStepFn
from eneo.flows.step_item_map import build_step_item_map_config
from eneo.main.exceptions import TypedIOValidationException

PER_ITEM_METADATA_PREVIEW_CHARS = 2000


@dataclass(frozen=True)
class PerItemMapCall:
    item_number: int
    source_label: str | None
    source_file_id: str | None
    output: StepExecutionOutput
    deps: StepExecutionRuntimeDeps
    elapsed_ms: int


def should_execute_per_item_map(step: RuntimeStep) -> bool:
    item_map = build_step_item_map_config(step.input_config)
    return (
        item_map.enabled
        and step.input_source == "previous_step"
        and step.input_type == "json"
        and step.output_type == "json"
    )


async def execute_per_item_map(
    *,
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    version_metadata: dict[str, object] | None,
    attempt_no: int,
    prepare_assistant_step: PrepareAssistantStepFn,
) -> StepExecutionResult:
    output_array_key = _single_output_array_key(step.output_contract)
    if output_array_key is None:
        raise TypedIOValidationException(
            "Per-item map execution requires a JSON output contract shaped as "
            "exactly one top-level array of objects.",
            code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
        )

    documents = _previous_documents(step=step, state=state)
    if not documents:
        raise TypedIOValidationException(
            f"Step {step.step_order}: per-item map requires at least one previous "
            "documents[] item.",
            code=FlowApiErrorCode.TYPED_IO_EMPTY_EXTRACTION.value,
        )

    item_calls: list[PerItemMapCall] = []
    for item_number, document in enumerate(documents, start=1):
        item_calls.append(
            await _execute_one_item(
                item_number=item_number,
                document=document,
                step=step,
                run=run,
                state=state,
                version_metadata=version_metadata,
                attempt_no=attempt_no,
                prepare_assistant_step=prepare_assistant_step,
            )
        )

    return StepExecutionResult(
        output=await _assemble_per_item_output(
            step=step,
            run=run,
            output_array_key=output_array_key,
            item_calls=item_calls,
        )
    )


async def _execute_one_item(
    *,
    item_number: int,
    document: dict[str, Any],
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    version_metadata: dict[str, object] | None,
    attempt_no: int,
    prepare_assistant_step: PrepareAssistantStepFn,
) -> PerItemMapCall:
    started = time.perf_counter()
    step_input = _step_input_for_document(item_number=item_number, document=document)
    prepared_step = await prepare_assistant_step(
        step=step,
        run=run,
        state=state,
        version_metadata=version_metadata,
        attempt_no=attempt_no,
        requested_file_ids_override=(),
        step_input_override=step_input,
    )
    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared_step.prepared,
        deps=prepared_step.deps,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _raise_if_item_output_is_not_object(
        output=output,
        step_order=step.step_order,
        item_number=item_number,
    )
    return PerItemMapCall(
        item_number=item_number,
        source_label=_optional_string(document.get("source_label")),
        source_file_id=_optional_string(document.get("source_file_id")),
        output=output,
        deps=prepared_step.deps,
        elapsed_ms=elapsed_ms,
    )


async def _assemble_per_item_output(
    *,
    step: RuntimeStep,
    run: FlowRun,
    output_array_key: str,
    item_calls: list[PerItemMapCall],
) -> StepExecutionOutput:
    first_output = item_calls[0].output
    first_deps = item_calls[0].deps
    output_items = [
        item
        for call in sorted(item_calls, key=lambda value: value.item_number)
        for item in _call_output_items(call, output_array_key=output_array_key)
    ]
    assembled_structured = {output_array_key: output_items}
    full_text = json.dumps(assembled_structured, ensure_ascii=False)
    item_map_metadata = _item_map_metadata(
        item_calls=item_calls,
        output_array_key=output_array_key,
        source_step_order=step.step_order - 1,
    )
    input_text = _item_map_input_text_summary(item_calls)
    input_payload_for_result: dict[str, Any] = {
        "text": input_text,
        "source_text": "",
        "input_source": first_output.input_source,
        "used_question_binding": first_output.used_question_binding,
        "runtime_input": item_map_metadata,
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
            code="previous_step_per_item_map",
            message=(
                f"Step {step.step_order}: executed once per previous documents[] "
                f"item ({len(item_calls)} item calls)."
            ),
            severity="info",
        ),
        *(diagnostic for call in item_calls for diagnostic in call.output.diagnostics),
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
        tool_calls_metadata=_item_map_tool_metadata(item_calls),
        num_tokens_input=_sum_optional(call.output.num_tokens_input for call in item_calls),
        num_tokens_output=_sum_optional(call.output.num_tokens_output for call in item_calls),
        effective_prompt=first_output.effective_prompt,
        model_parameters_json={
            **first_output.model_parameters_json,
            "item_map_execution_mode": "per_item",
            "per_item_call_count": len(item_calls),
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
        rag_metadata=_item_map_rag_metadata(item_calls),
        runtime_input_metadata=item_map_metadata,
    )


def _step_input_for_document(
    *,
    item_number: int,
    document: dict[str, Any],
) -> StepInputValue:
    structured = {"documents": [document]}
    text = json.dumps(structured, ensure_ascii=False)
    return StepInputValue(
        text=text,
        source_text=text,
        structured=structured,
        input_source="previous_step",
        runtime_input_metadata={
            "capture_mode": "previous_step_item",
            "execution_mode": "per_item",
            "item_number": item_number,
            "source_label": _optional_string(document.get("source_label")),
            "source_file_id": _optional_string(document.get("source_file_id")),
            "input_text_length": len(text),
        },
    )


def _previous_documents(
    *,
    step: RuntimeStep,
    state: RunExecutionState,
) -> list[dict[str, Any]]:
    previous_result = state.completed_by_order.get(step.step_order - 1)
    if previous_result is None:
        raise TypedIOValidationException(
            f"Step {step.step_order}: per-item map requires a completed previous step.",
            code=FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value,
        )
    if not isinstance(previous_result.output_payload_json, dict):
        raise TypedIOValidationException(
            f"Step {step.step_order}: per-item map requires a completed previous step.",
            code=FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value,
        )
    structured = previous_result.output_payload_json.get("structured")
    if not isinstance(structured, Mapping):
        raise TypedIOValidationException(
            f"Step {step.step_order}: per-item map requires previous structured output.",
            code=FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value,
        )
    typed_structured = cast(Mapping[str, object], structured)
    documents = typed_structured.get("documents")
    if not isinstance(documents, list):
        raise TypedIOValidationException(
            f"Step {step.step_order}: per-item map requires previous documents[].",
            code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
        )
    result: list[dict[str, Any]] = []
    for index, raw_item in enumerate(cast(list[object], documents), start=1):
        if not isinstance(raw_item, dict):
            raise TypedIOValidationException(
                f"Step {step.step_order}: previous documents[{index}] must be an object.",
                code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
            )
        result.append(dict(cast(dict[str, Any], raw_item)))
    return result


def _single_output_array_key(output_contract: dict[str, Any] | None) -> str | None:
    if not isinstance(output_contract, Mapping):
        return None
    properties = output_contract.get("properties")
    if not isinstance(properties, Mapping):
        return None
    typed_properties = cast(Mapping[str, object], properties)
    keys = tuple(typed_properties.keys())
    if len(keys) != 1:
        return None
    array_key = keys[0]
    array_schema = typed_properties[array_key]
    if not isinstance(array_schema, Mapping):
        return None
    typed_array_schema = cast(Mapping[str, object], array_schema)
    if typed_array_schema.get("type") != "array":
        return None
    item_schema = typed_array_schema.get("items")
    if not isinstance(item_schema, Mapping):
        return None
    typed_item_schema = cast(Mapping[str, object], item_schema)
    if typed_item_schema.get("type") != "object":
        return None
    return array_key


def _raise_if_item_output_is_not_object(
    *,
    output: StepExecutionOutput,
    step_order: int,
    item_number: int,
) -> None:
    if isinstance(output.structured_output, dict):
        return
    raise TypedIOValidationException(
        f"Step {step_order}: per-item map item {item_number} returned non-object JSON.",
        code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
    )


def _call_output_items(
    call: PerItemMapCall,
    *,
    output_array_key: str,
) -> list[dict[str, Any]]:
    structured_output = cast(dict[str, Any], call.output.structured_output)
    raw_items = structured_output.get(output_array_key)
    if not isinstance(raw_items, list):
        raise TypedIOValidationException(
            f"Step output for item {call.item_number} must contain {output_array_key}[].",
            code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
        )
    items: list[dict[str, Any]] = []
    for index, raw_item in enumerate(cast(list[object], raw_items), start=1):
        if not isinstance(raw_item, dict):
            raise TypedIOValidationException(
                f"Step output for item {call.item_number} {output_array_key}[{index}] "
                "must be an object.",
                code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
            )
        items.append(dict(cast(dict[str, Any], raw_item)))
    return items


def _item_map_metadata(
    *,
    item_calls: list[PerItemMapCall],
    output_array_key: str,
    source_step_order: int,
) -> dict[str, Any]:
    return {
        "text": _item_map_input_text_summary(item_calls),
        "capture_mode": "previous_step_item_map",
        "execution_mode": "per_item",
        "source_step_order": source_step_order,
        "input_array": "documents",
        "output_array": output_array_key,
        "item_count": len(item_calls),
        "per_item_calls": [_item_call_metadata(call) for call in item_calls],
    }


def _item_call_metadata(call: PerItemMapCall) -> dict[str, Any]:
    input_text = call.output.input_text
    return {
        "item_number": call.item_number,
        "source_label": call.source_label,
        "source_file_id": call.source_file_id,
        "elapsed_ms": call.elapsed_ms,
        "input_text_length": len(input_text),
        "input_text_preview": input_text[:PER_ITEM_METADATA_PREVIEW_CHARS],
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


def _item_map_input_text_summary(item_calls: list[PerItemMapCall]) -> str:
    return (
        f"[per-item map input: {len(item_calls)} documents[] item calls; "
        "see runtime_input.per_item_calls for model input previews]"
    )


def _item_map_tool_metadata(
    item_calls: list[PerItemMapCall],
) -> dict[str, Any]:
    return {
        "execution_mode": "per_item",
        "items": [
            {
                "item_number": call.item_number,
                "source_label": call.source_label,
                "source_file_id": call.source_file_id,
                "tool_calls": call.output.tool_calls_metadata,
            }
            for call in item_calls
        ],
    }


def _item_map_rag_metadata(
    item_calls: list[PerItemMapCall],
) -> dict[str, Any] | None:
    metadata = [
        call.output.rag_metadata
        for call in item_calls
        if call.output.rag_metadata is not None
    ]
    if not metadata:
        return None
    return {
        "execution_mode": "per_item",
        "items": metadata,
    }


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _sum_optional(values: Any) -> int | None:
    total = 0
    observed = False
    for value in values:
        if isinstance(value, int):
            total += value
            observed = True
    return total if observed else None
