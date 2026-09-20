from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any, cast

from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.domain.rag_evidence_policy import FlowRagEvidencePolicy
from eneo.flows.domain.runtime import (
    RunExecutionState,
    RuntimeStep,
    StepExecutionOutput,
)
from eneo.flows.domain.step_mapped_execution import single_mapped_array_key
from eneo.flows.enums import FlowStepPhase
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_provenance import (
    MappedProviderCallProvenance,
    sum_complete_token_counts,
)
from eneo.flows.runtime.step_deadline import (
    record_step_phase,
    record_step_progress,
    require_step_budget,
)
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.step_execution_runtime import (
    attach_typed_failure_context,
    complete_step_execution,
)
from eneo.flows.runtime.step_handlers.base import (
    ActivatePreparedAssistantStepsFn,
    PreviewAssistantStepFn,
)
from eneo.flows.runtime.step_handlers.mapped_outputs import (
    MappedCallEvidence,
    mapped_output_diagnostics,
)
from eneo.flows.runtime.step_handlers.text_sections import prepare_text_sections
from eneo.flows.runtime.structured_output_budget import (
    StructuredOutputBudget,
    structured_output_json,
)
from eneo.main.exceptions import TypedIOValidationException


async def execute_section_completion(
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
    array_key = single_mapped_array_key(step.output_contract)
    if array_key is None:
        raise TypedIOValidationException(
            "Section processing requires exactly one authored array of objects.",
            code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
        )
    contract = deepcopy(step.output_contract)
    assert contract is not None
    contract["properties"][array_key]["minItems"] = 1
    contract["properties"][array_key]["maxItems"] = 1
    per_call_step = replace(step, output_contract=contract)
    base = await preview_assistant_step(
        step=per_call_step,
        run=run,
        state=state,
        version_metadata=version_metadata,
        attempt_no=attempt_no,
    )
    if base.prepared.assistant.has_knowledge():
        raise TypedIOValidationException(
            "Section processing does not support knowledge retrieval.",
            code=FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value,
        )
    sections = await prepare_text_sections(
        step=per_call_step,
        run=run,
        state=state,
        base=base,
        policy=mapped_execution_policy,
    )
    total = len(sections.calls)
    record_step_progress(
        f"0 of {total} sections completed", completed_items=0, total_items=total
    )
    calls = await activate_prepared_assistant_steps(
        run, step, state, attempt_no, sections.calls
    )
    evidence = MappedCallEvidence(
        policy=rag_evidence_policy, execution_mode="per_item", collection_key="items"
    )
    outputs: list[StepExecutionOutput] = []
    records: list[dict[str, Any]] = []
    output_budget = StructuredOutputBudget(
        array_key=array_key,
        ceiling_bytes=base.deps.max_inline_text_bytes,
        total_items=total,
    )
    try:
        for index, call in enumerate(calls):
            record_step_phase(FlowStepPhase.MAPPED_ITEM)
            require_step_budget(
                call.deps.deadline,
                step_order=step.step_order,
                phase=f"section {index + 1} of {total}",
            )
            output = await complete_step_execution(
                step=per_call_step,
                run=run,
                state=state,
                prepared=call.prepared,
                deps=replace(
                    call.deps,
                    mapped_call_context=MappedProviderCallProvenance(
                        execution_mode="per_item",
                        item_index=index + 1,
                    ),
                ),
            )
            evidence.admit(output.rag_metadata)
            value = output.structured_output
            raw_items: object = (
                value.get(array_key) if isinstance(value, dict) else None
            )
            items = cast(list[object], raw_items) if isinstance(raw_items, list) else []
            if len(items) != 1 or not isinstance(items[0], dict):
                raise TypedIOValidationException(
                    "Each section must produce exactly one record.",
                    code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
                )
            record = cast(dict[str, Any], items[0])
            output_budget.admit([record], completed_items=len(outputs) + 1)
            records.append(record)
            outputs.append(output)
            record_step_progress(
                f"{len(outputs)} of {total} sections completed",
                completed_items=len(outputs),
                total_items=total,
            )
        record_step_phase(FlowStepPhase.FINALIZATION)
        full_text = structured_output_json({array_key: records})
        typed_output = await base.deps.process_typed_output(
            full_text=full_text, step=step, run=run
        )
        persisted_text, generated_file_ids = await base.deps.apply_output_cap(
            text=full_text,
            run=run,
            step=step,
        )
        return StepExecutionResult(
            output=replace(
                outputs[0],
                input_text=base.prepared.step_input.text,
                source_text=base.prepared.step_input.source_text,
                full_text=full_text,
                persisted_text=persisted_text,
                structured_output=typed_output.structured_output,
                generated_file_ids=generated_file_ids,
                artifacts=typed_output.artifacts,
                num_tokens_input=sum_complete_token_counts(
                    o.num_tokens_input for o in outputs
                ),
                num_tokens_output=sum_complete_token_counts(
                    o.num_tokens_output for o in outputs
                ),
                provider_response_id=None,
                raw_completion_text=None,
                diagnostics=[
                    *mapped_output_diagnostics(outputs),
                    *typed_output.diagnostics,
                ],
                rag_metadata=evidence.payload(),
                output_payload_extensions={
                    "section_manifest": sections.manifest.model_dump(mode="json")
                },
            )
        )
    except BaseException as exc:
        completed_items = len(outputs)
        if isinstance(exc, TypedIOValidationException):
            exc.context = {
                **(exc.context or {}),
                "completed_items": len(outputs),
                "total_items": total,
            }
            output_budget.set_failure_progress(exc, completed_items=completed_items + 1)
            completed_items = exc.context["completed_items"]
            attach_typed_failure_context(
                exc,
                input_payload_for_result=base.prepared.input_payload_for_result,
                effective_prompt=base.prepared.effective_prompt,
            )
        setattr(exc, "completed_items", completed_items)
        setattr(exc, "total_items", total)
        evidence.admit(getattr(exc, "rag_metadata", None))
        partial = evidence.partial_payload()
        if partial is not None:
            setattr(exc, "rag_metadata", partial)
        raise
