from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from eneo.flows.domain.flow import FlowStepResult
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep
from eneo.flows.enums import FlowStepResultStatus
from eneo.flows.runtime.inherited_citations import collect_inherited_citation_context


def _completed_grounded_result(*, step_order: int) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    source_id = "11111111-1111-1111-1111-111111111111"
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        input_payload_json={
            "rag": {
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
                            "source_id_short": "11111111",
                            "source_title": "Procurement memo",
                            "chunk_count": 1,
                        }
                    ],
                },
                "citation_sources": [
                    {
                        "id": source_id,
                        "id_short": "11111111",
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


def test_inherited_citation_context_reads_typed_source_refs() -> None:
    prior_result = _completed_grounded_result(step_order=1)
    context = collect_inherited_citation_context(
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
