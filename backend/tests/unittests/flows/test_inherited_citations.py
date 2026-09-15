from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from eneo.flows.domain.flow import FlowStepResult
from eneo.flows.domain.rag_evidence import build_step_result_citation_state
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep
from eneo.flows.enums import FlowStepResultStatus
from eneo.flows.runtime.inherited_citations import (
    collect_inherited_citation_context,
    inherited_cited_sources,
)


def _completed_grounded_result(
    *,
    step_order: int,
    source_id: str = "11111111-1111-1111-1111-111111111111",
    rag: dict[str, object] | None = None,
) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        input_payload_json={
            "rag": rag
            if rag is not None
            else {
                "status": "success",
                "tracking": {
                    "retrieval_tracked": True,
                    "prompt_context_inclusion_tracked": True,
                    "citation_tracked": False,
                    "material_influence_tracked": False,
                },
                "prompt_context": {
                    "tracked": True,
                    "included_source_ids": [source_id],
                    "included_source_titles": ["Procurement memo"],
                    "included_groups": [
                        {
                            "source_id": source_id,
                            "source_id_short": source_id[:8],
                            "source_title": "Procurement memo",
                            "chunk_count": 1,
                        }
                    ],
                },
                "citation_sources": [
                    {
                        "id": source_id,
                        "id_short": source_id[:8],
                        "title": "Procurement memo",
                        "source_title": "Procurement memo",
                        "source_display_name": "Procurement memo",
                    }
                ],
                "passage_evidence_location": "attempt_provenance",
            }
        },
        effective_prompt=None,
        output_payload_json={"text": "Grounded summary"},
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash=None,
        created_at=now,
        updated_at=now,
    )


def _runtime_step(*, input_bindings: dict[str, object]) -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=2,
        assistant_id=uuid4(),
        user_description="Final report",
        input_source="previous_step",
        input_bindings=input_bindings,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
    )


def _run_state(prior_result: FlowStepResult) -> RunExecutionState:
    return RunExecutionState(
        completed_by_order={1: prior_result},
        prior_results=[prior_result],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
        step_ref_mapping={"step_1": 1},
        step_names_by_order={1: "Grounded summary"},
    )


def test_inherited_citation_context_reads_only_underlag_steps() -> None:
    first = _completed_grounded_result(
        step_order=1, source_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )
    second = _completed_grounded_result(
        step_order=2, source_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=3,
        assistant_id=uuid4(),
        user_description="Final report",
        input_source="all_previous_steps",
        input_bindings={"question": "Samtal: {{ step_2.output.text }}"},
        input_config=None,
        output_mode="pass_through",
        output_config=None,
    )
    state = RunExecutionState(
        completed_by_order={1: first, 2: second},
        prior_results=[first, second],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
        step_ref_mapping={"step_1": 1, "step_2": 2},
        step_names_by_order={1: "Grounded summary", 2: "Second summary"},
    )

    context = collect_inherited_citation_context(
        step=step, state=state, prompt_template=None
    )

    assert context["upstream_step_orders"] == [2]
    assert context["upstream_step_labels"] == ["Second summary"]
    assert context["available_source_ids"] == ["bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"]


def test_prompt_references_join_the_inherited_sources() -> None:
    first = _completed_grounded_result(
        step_order=1, source_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )
    second = _completed_grounded_result(
        step_order=2, source_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )
    step = RuntimeStep(
        step_id=uuid4(),
        step_order=3,
        assistant_id=uuid4(),
        user_description="Final report",
        input_source="previous_step",
        input_bindings={"question": "Samtal: {{ step_2.output.text }}"},
        input_config=None,
        output_mode="pass_through",
        output_config=None,
    )
    state = RunExecutionState(
        completed_by_order={1: first, 2: second},
        prior_results=[first, second],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
        step_ref_mapping={"step_1": 1, "step_2": 2},
        step_names_by_order={1: "Grounded summary", 2: "Second summary"},
    )

    context = collect_inherited_citation_context(
        step=step,
        state=state,
        prompt_template="Bakgrund: {{ step_1.output.text }}",
    )

    assert context["upstream_step_orders"] == [1, 2]
    assert context["available_source_ids"] == [
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    ]


def test_cited_inherited_sources_reach_the_next_consumer() -> None:
    # Step 1 retrieves A. Step 2 reads step 1, retrieves nothing of its own and
    # cites A; its result carries A as an inherited citation. Step 3 binds only
    # step 2 and must still be able to cite A, while an unrelated source B on a
    # step it does not read stays out.
    first = _completed_grounded_result(
        step_order=1, source_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )
    unrelated = _completed_grounded_result(
        step_order=2, source_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )
    first_state = RunExecutionState(
        completed_by_order={1: first},
        prior_results=[first],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
        step_ref_mapping={"step_1": 1},
        step_names_by_order={1: "Grounded summary"},
    )
    consumer = RuntimeStep(
        step_id=uuid4(),
        step_order=3,
        assistant_id=uuid4(),
        user_description="Middle",
        input_source="previous_step",
        input_bindings={"question": "Underlag: {{ step_1.output.text }}"},
        input_config=None,
        output_mode="pass_through",
        output_config=None,
    )
    inherited = collect_inherited_citation_context(
        step=consumer, state=first_state, prompt_template=None
    )
    cited = inherited_cited_sources(
        citation_sidecar={
            "inherited_cited_source_ids": ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]
        },
        inherited_context=inherited,
    )
    middle_state = build_step_result_citation_state(None, inherited_sources=cited)
    assert middle_state is not None
    middle = _completed_grounded_result(step_order=3, rag=middle_state)

    final_step = RuntimeStep(
        step_id=uuid4(),
        step_order=4,
        assistant_id=uuid4(),
        user_description="Final report",
        input_source="all_previous_steps",
        input_bindings={"question": "Samtal: {{ step_3.output.text }}"},
        input_config=None,
        output_mode="pass_through",
        output_config=None,
    )
    state = RunExecutionState(
        completed_by_order={1: first, 2: unrelated, 3: middle},
        prior_results=[first, unrelated, middle],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
        step_ref_mapping={"step_1": 1, "step_2": 2, "step_3": 3},
        step_names_by_order={1: "Grounded summary", 2: "Unrelated", 3: "Middle"},
    )

    context = collect_inherited_citation_context(
        step=final_step, state=state, prompt_template=None
    )

    assert context["upstream_step_orders"] == [3]
    assert context["available_source_ids"] == ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]


def test_inherited_citation_context_reads_typed_source_refs() -> None:
    prior_result = _completed_grounded_result(step_order=1)
    context = collect_inherited_citation_context(
        prompt_template=None,
        step=_runtime_step(
            input_bindings={
                "source_refs": [
                    {"step_ref": "step_1", "output": "text", "label": "Grounding"}
                ]
            }
        ),
        state=_run_state(prior_result),
    )

    assert context["upstream_step_orders"] == [1]
    assert context["upstream_step_labels"] == ["Grounded summary"]
    assert context["available_source_ids"] == ["11111111-1111-1111-1111-111111111111"]
