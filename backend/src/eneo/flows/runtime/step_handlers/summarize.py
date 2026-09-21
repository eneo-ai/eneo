from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import Any, cast

from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.mapped_execution_policy import SummarizationBudget
from eneo.flows.domain.provider_call import SummarizationCallInput
from eneo.flows.domain.runtime import (
    RunExecutionState,
    RuntimeStep,
    StepExecutionOutput,
)
from eneo.flows.domain.text_processing import (
    SectionManifest,
    SummarizationProvenance,
    TextProcessingRecord,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.runtime.step_deadline import record_step_progress, require_step_budget
from eneo.flows.runtime.step_execution_runtime import complete_step_execution
from eneo.flows.runtime.step_handlers.base import PreparedAssistantStep
from eneo.flows.runtime.step_handlers.text_sections import prepare_text_processing_call
from eneo.flows.runtime.structured_output_budget import (
    StructuredOutputBudget,
    structured_output_json,
)
from eneo.main.exceptions import TypedIOValidationException


def record_bytes(records: list[TextProcessingRecord]) -> int:
    return sum(len(structured_output_json(record.value).encode()) for record in records)


def section_records(
    records: list[dict[str, Any]], outputs: list[StepExecutionOutput]
) -> list[TextProcessingRecord]:
    return [
        TextProcessingRecord(
            id=f"section:{index}",
            round=0,
            section_indexes=(index,),
            value=value,
            citations=tuple(
                source_id
                for source_id in (output.citation_sidecar or {}).get(
                    "cited_source_ids", []
                )
                if isinstance(source_id, str)
            ),
        )
        for index, (value, output) in enumerate(zip(records, outputs, strict=True))
    ]


def admit_round(
    budget: SummarizationBudget, calls: tuple[PreparedAssistantStep, ...]
) -> None:
    tokens = 0
    fallback_tokens = 0
    for call in calls:
        completion = call.prepared.completion_call
        assert completion is not None and completion.preflight is not None
        tokens += completion.preflight.admission_input_reserve_tokens
        if completion.capability_fallback_model_kwargs is not None:
            fallback_tokens = max(
                fallback_tokens, completion.preflight.admission_input_reserve_tokens
            )
    budget.admit(
        calls=len(calls) + int(fallback_tokens > 0),
        input_tokens=tokens + fallback_tokens,
    )


async def fold_section_records(
    *,
    step: RuntimeStep,
    run: FlowRun,
    state: RunExecutionState,
    base: PreparedAssistantStep,
    records: list[TextProcessingRecord],
    manifest: SectionManifest,
    array_key: str,
    budget: SummarizationBudget,
) -> tuple[TextProcessingRecord, list[StepExecutionOutput], SummarizationProvenance]:
    lineage = list(records)
    outputs: list[StepExecutionOutput] = []
    round_no = 0
    while len(records) > 1:
        budget.rounds = round_no
        budget.records = len(records)
        budget.bytes = record_bytes(records)
        before_bytes = budget.bytes
        groups: list[tuple[list[TextProcessingRecord], PreparedAssistantStep]] = []
        start = 0
        while start < len(records):
            require_step_budget(
                base.deps.deadline,
                step_order=step.step_order,
                phase="summarization grouping",
            )
            low, high = start, len(records)
            best: PreparedAssistantStep | None = None
            end = high
            while end > low:
                try:
                    call, _ = await prepare_text_processing_call(
                        step=step,
                        run=run,
                        state=state,
                        base=base,
                        section_text=structured_output_json(
                            {array_key: [record.value for record in records[start:end]]}
                        ),
                    )
                except TypedIOValidationException as exc:
                    if (
                        exc.code
                        != FlowApiErrorCode.TYPED_IO_INPUT_EXCEEDS_MODEL_WINDOW.value
                    ):
                        raise
                    high = end - 1
                else:
                    low, best = end, call
                if low >= high:
                    break
                end = (low + high + 1) // 2
            if best is None:
                raise budget.refusal()
            groups.append((records[start:low], best))
            start = low
        if len(groups) >= len(records):
            raise budget.refusal()
        admit_round(budget, tuple(call for _, call in groups))
        round_no += 1
        next_records: list[TextProcessingRecord] = []
        output_budget = StructuredOutputBudget(
            array_key=array_key,
            ceiling_bytes=base.deps.max_inline_text_bytes,
            total_items=len(groups),
        )
        record_step_progress(
            f"Summarization round {round_no}",
            completed_items=0,
            total_items=len(groups),
        )
        for index, (parents, call) in enumerate(groups):
            require_step_budget(
                call.deps.deadline, step_order=step.step_order, phase="summarization"
            )
            inherited = tuple(
                dict.fromkeys(
                    citation for parent in parents for citation in parent.citations
                )
            )
            composed_input = structured_output_json(
                {array_key: [parent.value for parent in parents]}
            ).encode("utf-8")
            call.prepared.summarization_input = SummarizationCallInput(
                round=round_no,
                group_index=index,
                record_ids=tuple(parent.id for parent in parents),
                input_bytes=len(composed_input),
                input_sha256=sha256(composed_input).hexdigest(),
                reserved_calls=budget.provider_calls + 1,
                reserved_input_tokens=budget.input_tokens,
                max_provider_calls=budget.max_provider_calls,
                max_input_tokens=budget.max_input_tokens,
            )
            output = await complete_step_execution(
                step=step,
                run=run,
                state=state,
                prepared=call.prepared,
                deps=replace(call.deps, summarization_budget=budget),
            )
            value = output.structured_output
            raw_items: object = (
                value.get(array_key) if isinstance(value, dict) else None
            )
            items = cast(list[object], raw_items) if isinstance(raw_items, list) else []
            if len(items) != 1 or not isinstance(items[0], dict):
                raise TypedIOValidationException(
                    "Each summarization group must produce exactly one record.",
                    code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
                )
            record_value = cast(dict[str, Any], items[0])
            output_budget.admit([record_value], completed_items=index + 1)
            record = TextProcessingRecord(
                id=f"round:{round_no}:{index}",
                round=round_no,
                parents=tuple(parent.id for parent in parents),
                section_indexes=tuple(
                    i for parent in parents for i in parent.section_indexes
                ),
                citations=inherited,
                value=record_value,
            )
            next_records.append(record)
            lineage.append(record)
            output = replace(
                output,
                citation_sidecar={
                    "citation_tracked": True,
                    "citation_context_kind": "inherited" if inherited else "none",
                    "cited_source_ids": list(inherited),
                    "cited_source_count": len(inherited),
                    "direct_cited_source_ids": [],
                    "inherited_cited_source_ids": list(inherited),
                    "unknown_citation_ids": [],
                },
            )
            outputs.append(output)
            record_step_progress(
                f"Summarization round {round_no}",
                completed_items=index + 1,
                total_items=len(groups),
            )
        budget.rounds = round_no
        budget.records = len(next_records)
        budget.bytes = record_bytes(next_records)
        if len(next_records) >= len(records) or budget.bytes >= before_bytes:
            raise budget.refusal()
        records = next_records
    return (
        records[0],
        outputs,
        SummarizationProvenance(
            rounds=round_no, sources=manifest.sources, records=tuple(lineage)
        ),
    )
