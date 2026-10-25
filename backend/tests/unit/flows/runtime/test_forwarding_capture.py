from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.authentication.principal_types import PrincipalType
from eneo.completion_models.domain.model_kwargs_capabilities import (
    SupportedModelKwargs,
)
from eneo.flows.domain.flow import FlowRun, FlowRunStatus
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep, StepInputValue
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputFlowInputSource,
    FlowResolvedInputJsonPath,
    build_resolved_input_edge,
    build_runtime_file_resolved_input_edge,
    group_resolved_input_edges,
)
from eneo.flows.runtime.forwarding_capture import (
    forwarding_capture_scope,
    hold_attempt_edges,
    record_completed_model_call,
)
from eneo.flows.runtime.output_runtime import TypedOutputProcessingResult
from eneo.flows.runtime.step_execution_runtime import (
    PreparedStepExecution,
    StepExecutionRuntimeDeps,
    complete_step_execution,
    prepare_step_execution,
)
from eneo.flows.variable_resolver import FlowVariableResolver

TRANSCRIPT = " ".join(f"ord{index}" for index in range(400))
SUMMARY = " ".join(f"summering{index}" for index in range(40))


def _run() -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.RUNNING,
        input_payload_json={"text": TRANSCRIPT},
        created_at=now,
        updated_at=now,
    )


def _state() -> RunExecutionState:
    return RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
        step_ref_mapping={},
    )


def _step(*, output_mode: str = "pass_through") -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        user_description=None,
        plan_step_ref=None,
        existing_step_ref=None,
        input_source="flow_input",
        input_bindings=None,
        input_config=None,
        output_mode=output_mode,
        output_config=None,
        output_type="text",
        output_contract=None,
        input_type="text",
        input_contract=None,
    )


def _assistant(*, prompt: str, outputs: list[str]) -> MagicMock:
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = prompt
    assistant.completion_model = SimpleNamespace(
        id=uuid4(),
        litellm_model_name="provider/model",
        name="model",
        provider_type="provider",
        supported_model_kwargs=SupportedModelKwargs(),
    )
    assistant.completion_model_kwargs = ModelKwargs()
    assistant.get_response = AsyncMock(
        side_effect=[
            SimpleNamespace(
                total_token_count=10,
                completion=output,
                usage=SimpleNamespace(prompt_tokens=8, completion_tokens=2),
                model=SimpleNamespace(name="model", provider_type="provider"),
            )
            for output in outputs
        ]
    )
    return assistant


async def _resolve_flow_input_text(**_kwargs: Any) -> StepInputValue:
    # What input resolution does for input_source=flow_input: the edge is
    # built from the text it selects.
    return StepInputValue(
        text=TRANSCRIPT,
        source_text=TRANSCRIPT,
        input_source="flow_input",
        edges=(
            build_resolved_input_edge(
                binding_ref="input_source",
                source=FlowResolvedInputFlowInputSource(
                    kind="flow_input",
                    selector=FlowResolvedInputJsonPath(
                        kind="json_path", path=("text",)
                    ),
                ),
                selected_value=TRANSCRIPT,
            ),
        ),
    )


def _deps(assistant: MagicMock) -> StepExecutionRuntimeDeps:
    return StepExecutionRuntimeDeps(
        max_inline_text_bytes=1_000_000,
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(return_value=assistant),
        resolve_step_input=AsyncMock(side_effect=_resolve_flow_input_text),
        retrieve_rag_chunks=AsyncMock(return_value=([], None, [])),
        process_typed_output=AsyncMock(
            return_value=TypedOutputProcessingResult(
                structured_output=None, artifacts=None, diagnostics=[]
            )
        ),
        apply_output_cap=AsyncMock(side_effect=lambda **kw: (kw["text"], [])),
    )


async def _prepare_and_activate(
    *, step: RuntimeStep, run: FlowRun, state: RunExecutionState, deps: Any
) -> PreparedStepExecution:
    prepared = await prepare_step_execution(
        step=step,
        run=run,
        state=state,
        version_metadata=None,
        requested_file_ids=(),
        deps=deps,
    )
    # Activation records the attempt's aggregate and gives the call its indexes.
    grouping = group_resolved_input_edges(prepared.resolved_input_edges)
    hold_attempt_edges(grouping.aggregate.edges)
    prepared.resolved_input_edge_indexes = grouping.indexes_by_group[0]
    return prepared


async def test_a_model_step_attempt_records_facts_of_what_its_call_received() -> None:
    run, state, step = _run(), _state(), _step()
    # The step reads the transcript as input and again in its prompt.
    assistant = _assistant(
        prompt="Sammanfatta mötet.\n{{flow_input.text}}", outputs=[TRANSCRIPT]
    )
    deps = _deps(assistant)

    with forwarding_capture_scope() as capture:
        prepared = await _prepare_and_activate(
            step=step, run=run, state=state, deps=deps
        )
        await complete_step_execution(
            step=step, run=run, state=state, prepared=prepared, deps=deps
        )

    facts = capture.facts()
    assert facts is not None and facts.measured is True
    size = len(TRANSCRIPT.encode("utf-8"))
    # Edge 0 is the input, edge 1 the prompt read of the same text.
    assert [
        (edge.edge_index, edge.byte_size, edge.repeated_bytes) for edge in facts.edges
    ] == [(0, size, size), (1, size, size)]
    # The model relayed the transcript.
    assert facts.output_verbatim_ratio == 1.0
    assert facts.call_count == 1
    assert TRANSCRIPT.split()[0] not in json.dumps(facts.model_dump(mode="json"))


async def test_a_mapped_attempt_is_measured_on_its_first_call_and_counts_the_rest() -> (
    None
):
    run, state, step = _run(), _state(), _step()
    assistant = _assistant(prompt="", outputs=[SUMMARY, TRANSCRIPT, TRANSCRIPT])
    deps = _deps(assistant)

    with forwarding_capture_scope() as capture:
        prepared = await _prepare_and_activate(
            step=step, run=run, state=state, deps=deps
        )
        for _ in range(3):
            await complete_step_execution(
                step=step, run=run, state=state, prepared=prepared, deps=deps
            )

    facts = capture.facts()
    assert facts is not None
    assert facts.call_count == 3
    # Measured on the first call, whose output shares nothing with the input.
    assert facts.output_verbatim_ratio == 0.0


async def test_a_step_that_calls_no_model_records_no_facts() -> None:
    run, state = _run(), _state()
    step = _step(output_mode="copy_input")
    assistant = _assistant(prompt="{{flow_input.text}}", outputs=[])
    deps = _deps(assistant)

    with forwarding_capture_scope() as capture:
        prepared = await _prepare_and_activate(
            step=step, run=run, state=state, deps=deps
        )

    assert prepared.resolved_input_edges
    assert capture.facts() is None
    assistant.get_response.assert_not_awaited()


def test_edges_without_held_text_are_listed_as_unmeasured() -> None:
    file_edge = build_runtime_file_resolved_input_edge(
        binding_ref="runtime_files[0]",
        input_file_ordinal=0,
        file_id=uuid4(),
        checksum="checksum",
        byte_size=100,
    )
    with forwarding_capture_scope() as capture:
        text_edge = build_resolved_input_edge(
            binding_ref="input_source",
            source=FlowResolvedInputFlowInputSource(
                kind="flow_input",
                selector=FlowResolvedInputJsonPath(kind="json_path", path=("text",)),
            ),
            selected_value=TRANSCRIPT,
        )
        hold_attempt_edges((file_edge, text_edge))
        record_completed_model_call(edge_indexes=(0, 1), output_text=SUMMARY)

    facts = capture.facts()
    assert facts is not None
    assert facts.unmeasured_edge_indexes == (0,)
    assert [edge.edge_index for edge in facts.edges] == [1]


def test_structured_values_are_measured_as_their_canonical_json() -> None:
    value = {"beslut": TRANSCRIPT, "datum": "2026-10-23"}
    with forwarding_capture_scope() as capture:
        edge = build_resolved_input_edge(
            binding_ref="input_source",
            source=FlowResolvedInputFlowInputSource(
                kind="flow_input",
                selector=FlowResolvedInputJsonPath(kind="json_path", path=()),
            ),
            selected_value=value,
        )
        hold_attempt_edges((edge,))
        record_completed_model_call(edge_indexes=(0,), output_text=TRANSCRIPT)

    facts = capture.facts()
    assert facts is not None
    assert facts.edges[0].byte_size == edge.selection.byte_size
    assert facts.output_verbatim_ratio == 1.0


def test_nothing_is_held_or_measured_outside_an_attempt() -> None:
    with forwarding_capture_scope() as capture:
        pass

    build_resolved_input_edge(
        binding_ref="input_source",
        source=FlowResolvedInputFlowInputSource(
            kind="flow_input",
            selector=FlowResolvedInputJsonPath(kind="json_path", path=("text",)),
        ),
        selected_value=TRANSCRIPT,
    )
    hold_attempt_edges(())
    record_completed_model_call(edge_indexes=(0,), output_text=TRANSCRIPT)

    assert capture.facts() is None
