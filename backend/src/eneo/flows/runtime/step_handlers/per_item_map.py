from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, cast

from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.runtime import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
    StepInputValue,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.runtime.output_formats import JSON_OUTPUT_FORMAT, resolve_format_spec
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.step_execution_runtime import (
    StepExecutionRuntimeDeps,
    complete_step_execution,
)
from eneo.flows.runtime.step_handlers.base import PrepareAssistantStepFn
from eneo.flows.runtime.step_handlers.mapped_outputs import (
    mapped_output_diagnostics,
    mapped_rag_metadata,
    sum_optional_token_counts,
)
from eneo.flows.source_identity import (
    runtime_source_identity_fields_for_array_items,
    without_runtime_source_identity_json_fields,
)
from eneo.flows.step_item_map import build_step_item_map_config
from eneo.main.exceptions import TypedIOValidationException

PER_ITEM_METADATA_PREVIEW_CHARS = 2000


@dataclass(frozen=True)
class PerItemMapCall:
    item_number: int
    input_array_key: str
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
        and resolve_format_spec(step.output_type) is JSON_OUTPUT_FORMAT
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
    input_array_key = _single_array_key(step.input_contract)
    if input_array_key is None:
        raise TypedIOValidationException(
            "Per-item map execution requires a JSON input contract shaped as "
            "exactly one top-level array of objects.",
            code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
        )
    per_call_step = replace(
        step,
        output_contract=without_runtime_source_identity_json_fields(
            step.output_contract
        ),
    )

    input_items = _previous_items(
        step=step,
        state=state,
        input_array_key=input_array_key,
    )
    if not input_items:
        raise TypedIOValidationException(
            f"Step {step.step_order}: per-item map requires at least one previous "
            f"{input_array_key}[] item.",
            code=FlowApiErrorCode.TYPED_IO_EMPTY_EXTRACTION.value,
        )

    item_calls: list[PerItemMapCall] = []
    for item_number, input_item in enumerate(input_items, start=1):
        item_calls.append(
            await _execute_one_item(
                item_number=item_number,
                input_array_key=input_array_key,
                input_item=input_item,
                step=per_call_step,
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
            input_array_key=input_array_key,
            output_array_key=output_array_key,
            item_calls=item_calls,
        )
    )


async def _execute_one_item(
    *,
    item_number: int,
    input_array_key: str,
    input_item: dict[str, Any],
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    version_metadata: dict[str, object] | None,
    attempt_no: int,
    prepare_assistant_step: PrepareAssistantStepFn,
) -> PerItemMapCall:
    started = time.perf_counter()
    step_input = _step_input_for_item(
        item_number=item_number,
        input_array_key=input_array_key,
        input_item=input_item,
    )
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
        input_array_key=input_array_key,
        source_label=_optional_string(input_item.get("source_label")),
        source_file_id=_optional_string(input_item.get("source_file_id")),
        output=output,
        deps=prepared_step.deps,
        elapsed_ms=elapsed_ms,
    )


async def _assemble_per_item_output(
    *,
    step: RuntimeStep,
    run: FlowRun,
    input_array_key: str,
    output_array_key: str,
    item_calls: list[PerItemMapCall],
) -> StepExecutionOutput:
    first_output = item_calls[0].output
    first_deps = item_calls[0].deps
    output_items = [
        item
        for call in sorted(item_calls, key=lambda value: value.item_number)
        for item in _call_output_items(
            call,
            output_array_key=output_array_key,
            identity_fields=runtime_source_identity_fields_for_array_items(
                step.output_contract,
                output_array_key,
            ),
        )
    ]
    assembled_structured = {output_array_key: output_items}
    full_text = json.dumps(assembled_structured, ensure_ascii=False)
    item_map_metadata = _item_map_metadata(
        item_calls=item_calls,
        input_array_key=input_array_key,
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
                f"Step {step.step_order}: executed once per previous "
                f"{input_array_key}[] "
                f"item ({len(item_calls)} item calls)."
            ),
            severity="info",
        ),
        *mapped_output_diagnostics(call.output for call in item_calls),
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
        num_tokens_input=sum_optional_token_counts(
            call.output.num_tokens_input for call in item_calls
        ),
        num_tokens_output=sum_optional_token_counts(
            call.output.num_tokens_output for call in item_calls
        ),
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


def _step_input_for_item(
    *,
    item_number: int,
    input_array_key: str,
    input_item: dict[str, Any],
) -> StepInputValue:
    structured = {input_array_key: [input_item]}
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
            "input_array": input_array_key,
            "source_label": _optional_string(input_item.get("source_label")),
            "source_file_id": _optional_string(input_item.get("source_file_id")),
            "input_text_length": len(text),
        },
    )


def _previous_items(
    *,
    step: RuntimeStep,
    state: RunExecutionState,
    input_array_key: str,
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
    input_items = typed_structured.get(input_array_key)
    if not isinstance(input_items, list):
        raise TypedIOValidationException(
            f"Step {step.step_order}: per-item map requires previous "
            f"{input_array_key}[].",
            code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
        )
    result: list[dict[str, Any]] = []
    for index, raw_item in enumerate(cast(list[object], input_items), start=1):
        if not isinstance(raw_item, dict):
            raise TypedIOValidationException(
                f"Step {step.step_order}: previous {input_array_key}[{index}] must "
                "be an object.",
                code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
            )
        result.append(dict(cast(dict[str, Any], raw_item)))
    return result


def _single_output_array_key(output_contract: dict[str, Any] | None) -> str | None:
    return _single_array_key(output_contract)


def _single_array_key(contract: dict[str, Any] | None) -> str | None:
    if not isinstance(contract, Mapping):
        return None
    properties = contract.get("properties")
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
    identity_fields: frozenset[str],
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
        item = dict(cast(dict[str, Any], raw_item))
        if "source_label" in identity_fields and call.source_label is not None:
            item["source_label"] = call.source_label
        if "source_file_id" in identity_fields and call.source_file_id is not None:
            item["source_file_id"] = call.source_file_id
        items.append(item)
    return items


def _item_map_metadata(
    *,
    item_calls: list[PerItemMapCall],
    input_array_key: str,
    output_array_key: str,
    source_step_order: int,
) -> dict[str, Any]:
    return {
        "text": _item_map_input_text_summary(item_calls),
        "capture_mode": "previous_step_item_map",
        "execution_mode": "per_item",
        "source_step_order": source_step_order,
        "input_array": input_array_key,
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
    input_array_key = item_calls[0].input_array_key if item_calls else "items"
    return (
        f"[per-item map input: {len(item_calls)} {input_array_key}[] item calls; "
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
    return mapped_rag_metadata(
        execution_mode="per_item",
        collection_key="items",
        outputs=(call.output for call in item_calls),
    )


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
