from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, cast
from uuid import UUID

from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.flow_step_attempt_input import (
    ITEM_MAP_EXECUTION_MODE,
    ITEM_MAP_EXECUTION_MODE_KEY,
)
from eneo.flows.domain.mapped_execution_policy import (
    FlowMappedExecutionPolicy,
    effective_mapped_cardinality,
)
from eneo.flows.domain.rag_evidence_policy import FlowRagEvidencePolicy
from eneo.flows.domain.runtime import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
    StepInputValue,
)
from eneo.flows.domain.runtime_invariant_exceptions import FlowRuntimeInvariantError
from eneo.flows.domain.step_item_map import build_step_item_map_config
from eneo.flows.domain.step_mapped_execution import single_mapped_array_key
from eneo.flows.enums import FlowStepPhase
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputJsonPath,
    FlowResolvedInputStepResultSource,
    MappedProviderCallProvenance,
    build_resolved_input_edge,
    sum_complete_token_counts,
)
from eneo.flows.input_binding_contract_rules import has_explicit_underlag
from eneo.flows.runtime.step_deadline import (
    record_step_phase,
    record_step_progress,
    require_step_budget,
)
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.step_execution_runtime import (
    StepExecutionRuntimeDeps,
    attach_typed_failure_context,
    complete_step_execution,
    preview_step_execution_context,
    resolve_json_response_format_plan,
)
from eneo.flows.runtime.step_failure_evidence import (
    attach_failure_evidence,
    failure_evidence,
)
from eneo.flows.runtime.step_handlers.base import (
    ActivatePreparedAssistantStepsFn,
    PreparedAssistantStep,
    PreviewAssistantStepFn,
)
from eneo.flows.runtime.step_handlers.mapped_outputs import (
    MappedCallEvidence,
    carry_call_evidence,
    mapped_admission_payload,
    mapped_output_diagnostics,
)
from eneo.flows.runtime.structured_output_budget import (
    StructuredOutputBudget,
    ensure_structured_output_allowed,
    structured_output_json,
)
from eneo.flows.source_identity import (
    runtime_source_identity_fields_for_array_items,
    without_runtime_source_identity_json_fields,
)
from eneo.main.exceptions import TypedIOValidationException

PER_ITEM_METADATA_PREVIEW_CHARS = 2000


@dataclass(frozen=True)
class PerItemMapCall:
    """What assembly reads of one completed item call.

    Kept instead of the call's output, so a mapped step holds each item's
    structured result until assembly, not its completion text, prompt and
    parameters.
    """

    item_number: int
    input_array_key: str
    source_label: str | None
    source_file_id: str | None
    elapsed_ms: int
    input_text_length: int
    input_text_preview: str
    structured_output: dict[str, Any]
    diagnostics: tuple[StepDiagnostic, ...]
    tool_calls_metadata: list[dict[str, Any]] | dict[str, Any] | None
    rag_metadata: dict[str, Any] | None
    num_tokens_input: int | None
    num_tokens_output: int | None


@dataclass(frozen=True)
class PerItemAssemblyContext:
    """What the assembled output takes from the step's first item call."""

    input_source: str
    used_question_binding: bool
    effective_prompt: str
    model_parameters_json: dict[str, Any]
    requested_model: str | None
    response_model: str | None
    provider: str | None
    finish_reason: str | None
    contract_validation: dict[str, Any] | None
    deps: StepExecutionRuntimeDeps


async def execute_per_item_map(
    *,
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    version_metadata: dict[str, object] | None,
    attempt_no: int,
    preview_assistant_step: PreviewAssistantStepFn,
    activate_prepared_assistant_steps: ActivatePreparedAssistantStepsFn,
    mapped_execution_policy: FlowMappedExecutionPolicy,
    rag_evidence_policy: FlowRagEvidencePolicy,
) -> StepExecutionResult:
    output_array_key = single_mapped_array_key(step.output_contract)
    if output_array_key is None:
        raise TypedIOValidationException(
            "Per-item map execution requires a JSON output contract shaped as "
            "exactly one top-level array of objects.",
            code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
        )
    if has_explicit_underlag(step.input_bindings):
        raise TypedIOValidationException(
            f"Step {step.step_order}: item_map reads the previous step's items; "
            "explicit input_bindings are not supported on a mapped step.",
            code=FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value,
        )
    input_array_key = single_mapped_array_key(step.input_contract)
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

    source_step_id, source_attempt_no, input_items = _previous_items(
        step=step,
        state=state,
        input_array_key=input_array_key,
    )
    item_map = build_step_item_map_config(step.input_config)
    if item_map.max_items is None:
        raise TypedIOValidationException(
            f"Step {step.step_order}: per-item map requires a published max_items ceiling.",
            code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
        )
    effective_max_items = effective_mapped_cardinality(
        published_max=item_map.max_items,
        mapped_policy=mapped_execution_policy,
    )
    if len(input_items) > effective_max_items:
        raise TypedIOValidationException(
            f"Step {step.step_order}: per-item map received {len(input_items)} items, "
            f"exceeding the effective max_items ceiling of {effective_max_items}.",
            code=FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value,
        )
    if not input_items:
        raise TypedIOValidationException(
            f"Step {step.step_order}: per-item map requires at least one previous "
            f"{input_array_key}[] item.",
            code=FlowApiErrorCode.TYPED_IO_EMPTY_EXTRACTION.value,
        )

    record_step_progress(
        f"0 of {len(input_items)} items completed",
        completed_items=0,
        total_items=len(input_items),
    )
    estimates: list[int] = []
    prepared_items: list[tuple[int, dict[str, Any], PreparedAssistantStep]] = []
    native_json_fallback_possible = False
    for item_number, input_item in enumerate(input_items, start=1):
        preview_step = await preview_assistant_step(
            step=per_call_step,
            run=run,
            state=state,
            version_metadata=version_metadata,
            attempt_no=attempt_no,
            requested_file_ids_override=(),
            step_input_override=_step_input_for_item(
                item_number=item_number,
                input_array_key=input_array_key,
                input_item=input_item,
                source_step_id=source_step_id,
                source_attempt_no=source_attempt_no,
            ),
        )
        prepared_items.append((item_number, input_item, preview_step))
        estimates.append(
            await preview_step_execution_context(
                step=per_call_step,
                state=state,
                prepared=preview_step.prepared,
                deps=preview_step.deps,
            )
        )
        if len(estimates) == 1:
            # The response-format plan is loop-invariant for this step.
            native_json_fallback_possible = resolve_json_response_format_plan(
                step=per_call_step,
                assistant=preview_step.prepared.assistant,
                state=state,
            ).fallback_call_possible
    state.mapped_admission_by_step[step.step_id] = mapped_admission_payload(
        execution_mode="per_item",
        estimates=estimates,
        native_json_fallback_possible=native_json_fallback_possible,
        policy=mapped_execution_policy,
    )
    activated_steps = await activate_prepared_assistant_steps(
        run,
        step,
        state,
        attempt_no,
        tuple(prepared for _, _, prepared in prepared_items),
    )
    total_items = len(prepared_items)
    # Every call is prepared and activated before the first one runs; once a
    # call has run, nothing reads its preparation again.
    pending_items = deque(
        (item_number, input_item, activated_step)
        for (item_number, input_item, _), activated_step in zip(
            prepared_items,
            activated_steps,
            strict=True,
        )
    )
    del prepared_items, activated_steps

    mapped_evidence = MappedCallEvidence(
        policy=rag_evidence_policy,
        execution_mode="per_item",
        collection_key="items",
    )
    item_calls: list[PerItemMapCall] = []
    assembly_context: PerItemAssemblyContext | None = None
    output_budget = StructuredOutputBudget(
        array_key=output_array_key,
        ceiling_bytes=pending_items[0][2].deps.max_inline_text_bytes,
        total_items=total_items,
    )
    identity_fields = runtime_source_identity_fields_for_array_items(
        step.output_contract, output_array_key
    )
    try:
        while pending_items:
            item_number, input_item, prepared_step = pending_items.popleft()
            # The next item is external work: refuse it, with what completed,
            # once the attempt's budget is spent.
            record_step_phase(FlowStepPhase.MAPPED_ITEM)
            require_step_budget(
                prepared_step.deps.deadline,
                step_order=step.step_order,
                phase=f"mapped item {item_number} of {total_items}",
                completed=f"{len(item_calls)} of {total_items} items completed",
            )
            item_call, assembly_context = await _execute_one_item(
                item_number=item_number,
                input_array_key=input_array_key,
                input_item=input_item,
                step=per_call_step,
                run=run,
                state=state,
                prepared_step=prepared_step,
                assembly_context=assembly_context,
            )
            # Bound this call before the next one runs, so the step never holds
            # more passage text than its budget allows.
            mapped_evidence.admit(item_call.rag_metadata)
            output_budget.admit(
                _call_output_items(
                    item_call,
                    output_array_key=output_array_key,
                    identity_fields=identity_fields,
                ),
                completed_items=item_number,
            )
            item_calls.append(item_call)
            record_step_progress(
                f"{len(item_calls)} of {total_items} items completed",
                completed_items=len(item_calls),
                total_items=total_items,
            )

        record_step_phase(FlowStepPhase.FINALIZATION)
        if assembly_context is None:
            raise FlowRuntimeInvariantError(
                "Per-item map assembly has no completed item call."
            )
        return StepExecutionResult(
            output=await _assemble_per_item_output(
                step=step,
                run=run,
                input_array_key=input_array_key,
                output_array_key=output_array_key,
                item_calls=item_calls,
                assembly_context=assembly_context,
                mapped_rag_metadata=mapped_evidence.payload(),
            )
        )
    except BaseException as exc:
        output_budget.set_failure_progress(exc, completed_items=len(item_calls) + 1)
        # The calls that completed really did retrieve; publish them as a
        # partial envelope so the failed attempt records what it read. Also
        # for the executor's backstop cancellation, which carries the
        # cancellation as the cause of its typed timeout.
        mapped_evidence.admit(failure_evidence(exc).rag_metadata)
        partial = mapped_evidence.partial_payload()
        if partial is not None:
            attach_failure_evidence(exc, rag_metadata=partial)
        raise


async def _execute_one_item(
    *,
    item_number: int,
    input_array_key: str,
    input_item: dict[str, Any],
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    prepared_step: PreparedAssistantStep,
    assembly_context: PerItemAssemblyContext | None,
) -> tuple[PerItemMapCall, PerItemAssemblyContext]:
    """The call's record, and the assembly context: the given one, or this
    call's when it is the step's first."""
    started = time.perf_counter()
    output = await complete_step_execution(
        step=step,
        run=run,
        state=state,
        prepared=prepared_step.prepared,
        deps=replace(
            prepared_step.deps,
            mapped_call_context=MappedProviderCallProvenance(
                execution_mode="per_item",
                item_index=item_number,
                source_id=_optional_string(input_item.get("source_file_id")),
            ),
        ),
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    try:
        _raise_if_item_output_is_not_object(
            output=output,
            step_order=step.step_order,
            item_number=item_number,
        )
    except Exception as exc:
        # This call retrieved before it failed validation, so its evidence
        # travels with the error rather than dying with the local output.
        carry_call_evidence(exc, output.rag_metadata)
        raise
    if assembly_context is None:
        assembly_context = PerItemAssemblyContext(
            input_source=output.input_source,
            used_question_binding=output.used_question_binding,
            effective_prompt=output.effective_prompt,
            model_parameters_json=output.model_parameters_json,
            requested_model=output.requested_model,
            response_model=output.response_model,
            provider=output.provider,
            finish_reason=output.finish_reason,
            contract_validation=output.contract_validation,
            deps=prepared_step.deps,
        )
    return (
        PerItemMapCall(
            item_number=item_number,
            input_array_key=input_array_key,
            source_label=_optional_string(input_item.get("source_label")),
            source_file_id=_optional_string(input_item.get("source_file_id")),
            elapsed_ms=elapsed_ms,
            input_text_length=len(output.input_text),
            input_text_preview=output.input_text[:PER_ITEM_METADATA_PREVIEW_CHARS],
            structured_output=cast(dict[str, Any], output.structured_output),
            diagnostics=tuple(output.diagnostics),
            tool_calls_metadata=output.tool_calls_metadata,
            rag_metadata=output.rag_metadata,
            num_tokens_input=output.num_tokens_input,
            num_tokens_output=output.num_tokens_output,
        ),
        assembly_context,
    )


async def _assemble_per_item_output(
    *,
    step: RuntimeStep,
    run: FlowRun,
    input_array_key: str,
    output_array_key: str,
    item_calls: list[PerItemMapCall],
    assembly_context: PerItemAssemblyContext,
    mapped_rag_metadata: dict[str, Any] | None,
) -> StepExecutionOutput:
    first_deps = assembly_context.deps
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
    full_text = structured_output_json(assembled_structured)
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
        "input_source": assembly_context.input_source,
        "used_question_binding": assembly_context.used_question_binding,
        "runtime_input": item_map_metadata,
    }
    try:
        typed_output = await first_deps.process_typed_output(
            full_text=full_text,
            step=step,
            run=run,
        )
        ensure_structured_output_allowed(
            typed_output.structured_output,
            ceiling_bytes=first_deps.max_inline_text_bytes,
            completed_items=len(item_calls),
            total_items=len(item_calls),
        )
    except TypedIOValidationException as exc:
        raise attach_typed_failure_context(
            exc,
            input_payload_for_result=input_payload_for_result,
            effective_prompt=assembly_context.effective_prompt,
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
        *mapped_output_diagnostics(item_calls),
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
        input_source=assembly_context.input_source,
        used_question_binding=assembly_context.used_question_binding,
        full_text=full_text,
        persisted_text=persisted_text,
        generated_file_ids=generated_file_ids,
        tool_calls_metadata=_item_map_tool_metadata(item_calls),
        num_tokens_input=sum_complete_token_counts(
            call.num_tokens_input for call in item_calls
        ),
        num_tokens_output=sum_complete_token_counts(
            call.num_tokens_output for call in item_calls
        ),
        effective_prompt=assembly_context.effective_prompt,
        model_parameters_json={
            **assembly_context.model_parameters_json,
            ITEM_MAP_EXECUTION_MODE_KEY: ITEM_MAP_EXECUTION_MODE,
            "per_item_call_count": len(item_calls),
        },
        requested_model=assembly_context.requested_model,
        response_model=assembly_context.response_model,
        provider=assembly_context.provider,
        finish_reason=assembly_context.finish_reason,
        provider_response_id=None,
        contract_validation=assembly_context.contract_validation,
        structured_output=final_structured_output,
        diagnostics=diagnostics,
        artifacts=typed_output.artifacts,
        rag_metadata=mapped_rag_metadata,
        runtime_input_metadata=item_map_metadata,
    )


def _step_input_for_item(
    *,
    item_number: int,
    input_array_key: str,
    input_item: dict[str, Any],
    source_step_id: UUID,
    source_attempt_no: int,
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
        edges=(
            build_resolved_input_edge(
                binding_ref="input",
                source=FlowResolvedInputStepResultSource(
                    kind="step_result",
                    source_step_id=source_step_id,
                    source_attempt_no=source_attempt_no,
                    selector=FlowResolvedInputJsonPath(
                        kind="json_path",
                        path=(
                            "output",
                            "structured",
                            input_array_key,
                            item_number - 1,
                        ),
                    ),
                ),
                selected_value=input_item,
            ),
        ),
    )


def _previous_items(
    *,
    step: RuntimeStep,
    state: RunExecutionState,
    input_array_key: str,
) -> tuple[UUID, int, list[dict[str, Any]]]:
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
    if previous_result.current_attempt_no is None:
        raise TypedIOValidationException(
            f"Step {step.step_order}: per-item map requires exact source attempt identity.",
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
    return previous_result.step_id, previous_result.current_attempt_no, result


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
    raw_items = call.structured_output.get(output_array_key)
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
    return {
        "item_number": call.item_number,
        "source_label": call.source_label,
        "source_file_id": call.source_file_id,
        "elapsed_ms": call.elapsed_ms,
        "input_text_length": call.input_text_length,
        "input_text_preview": call.input_text_preview,
        "num_tokens_input": call.num_tokens_input,
        "num_tokens_output": call.num_tokens_output,
        "diagnostics": [
            {
                "code": diagnostic.code,
                "message": diagnostic.message,
                "severity": diagnostic.severity,
            }
            for diagnostic in call.diagnostics
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
                "tool_calls": call.tool_calls_metadata,
            }
            for call in item_calls
        ],
    }


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
