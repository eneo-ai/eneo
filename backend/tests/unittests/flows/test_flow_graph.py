from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel

from intric.flows.api.flow_graph import (
    GRAPH_RESPONSE_EXAMPLE,
    GraphEdge,
    GraphNode,
    GraphResponse,
    build_graph_from_steps,
    build_graph_response,
    enrich_nodes_with_run_results,
)
from intric.flows.domain.flow import FlowStep, FlowStepResult
from intric.flows.enums import FlowOutputType, FlowStepResultStatus
from intric.flows.flow_validators import validate_steps

_GOLDEN_FLOW_ID = UUID("00000000-0000-0000-0000-000000000001")
_GOLDEN_TENANT_ID = UUID("00000000-0000-0000-0000-000000000010")
_GOLDEN_RUN_ID = UUID("00000000-0000-0000-0000-000000000301")
_GOLDEN_RESULT_ID = UUID("00000000-0000-0000-0000-000000000501")
_GOLDEN_STEP_1_ID = UUID("00000000-0000-0000-0000-000000000101")
_GOLDEN_STEP_2_ID = UUID("00000000-0000-0000-0000-000000000102")
_GOLDEN_STEP_3_ID = UUID("00000000-0000-0000-0000-000000000103")
_GOLDEN_STEP_4_ID = UUID("00000000-0000-0000-0000-000000000104")

_GOLDEN_GRAPH_RESPONSE = {
    "nodes": [
        {
            "id": "input",
            "label": "Input",
            "type": "input",
            "step_order": None,
            "input_source": None,
            "input_type": None,
            "output_type": None,
            "output_mode": None,
            "mcp_policy": None,
            "output_classification_override": None,
            "run_status": None,
            "num_tokens_input": None,
            "num_tokens_output": None,
            "error_message": None,
        },
        {
            "id": str(_GOLDEN_STEP_1_ID),
            "label": "Collect intake",
            "type": "llm",
            "step_order": 1,
            "input_source": "flow_input",
            "input_type": "text",
            "output_type": "text",
            "output_mode": "pass_through",
            "mcp_policy": "inherit",
            "output_classification_override": 2,
            "run_status": None,
            "num_tokens_input": None,
            "num_tokens_output": None,
            "error_message": None,
        },
        {
            "id": str(_GOLDEN_STEP_2_ID),
            "label": "Summarize intake",
            "type": "llm",
            "step_order": 2,
            "input_source": "previous_step",
            "input_type": "text",
            "output_type": "json",
            "output_mode": "pass_through",
            "mcp_policy": "inherit",
            "output_classification_override": None,
            "run_status": None,
            "num_tokens_input": None,
            "num_tokens_output": None,
            "error_message": None,
        },
        {
            "id": str(_GOLDEN_STEP_3_ID),
            "label": "Merge all prior context",
            "type": "llm",
            "step_order": 3,
            "input_source": "all_previous_steps",
            "input_type": "text",
            "output_type": "text",
            "output_mode": "pass_through",
            "mcp_policy": "inherit",
            "output_classification_override": None,
            "run_status": None,
            "num_tokens_input": None,
            "num_tokens_output": None,
            "error_message": None,
        },
        {
            "id": str(_GOLDEN_STEP_4_ID),
            "label": "Draft final response",
            "type": "assembly",
            "step_order": 4,
            "input_source": "previous_step",
            "input_type": "text",
            "output_type": "docx",
            "output_mode": "template_fill",
            "mcp_policy": "inherit",
            "output_classification_override": None,
            "run_status": "completed",
            "num_tokens_input": 11,
            "num_tokens_output": 17,
            "error_message": None,
        },
        {
            "id": "output",
            "label": "Output",
            "type": "output",
            "step_order": None,
            "input_source": None,
            "input_type": None,
            "output_type": None,
            "output_mode": None,
            "mcp_policy": None,
            "output_classification_override": None,
            "run_status": None,
            "num_tokens_input": None,
            "num_tokens_output": None,
            "error_message": None,
        },
    ],
    "edges": [
        {
            "source": "input",
            "target": str(_GOLDEN_STEP_1_ID),
            "kind": "flow_input",
            "source_step_order": 0,
            "target_step_order": 1,
            "style": None,
            "label": None,
        },
        {
            "source": str(_GOLDEN_STEP_1_ID),
            "target": str(_GOLDEN_STEP_2_ID),
            "kind": "previous_step",
            "source_step_order": 1,
            "target_step_order": 2,
            "style": None,
            "label": None,
        },
        {
            "source": str(_GOLDEN_STEP_1_ID),
            "target": str(_GOLDEN_STEP_3_ID),
            "kind": "all_previous_steps",
            "source_step_order": 1,
            "target_step_order": 3,
            "style": "dashed",
            "label": "aggregated",
        },
        {
            "source": str(_GOLDEN_STEP_2_ID),
            "target": str(_GOLDEN_STEP_3_ID),
            "kind": "all_previous_steps",
            "source_step_order": 2,
            "target_step_order": 3,
            "style": "dashed",
            "label": "aggregated",
        },
        {
            "source": "input",
            "target": str(_GOLDEN_STEP_3_ID),
            "kind": "all_previous_steps",
            "source_step_order": 0,
            "target_step_order": 3,
            "style": "dashed",
            "label": None,
        },
        {
            "source": str(_GOLDEN_STEP_3_ID),
            "target": str(_GOLDEN_STEP_4_ID),
            "kind": "previous_step",
            "source_step_order": 3,
            "target_step_order": 4,
            "style": None,
            "label": None,
        },
        {
            "source": str(_GOLDEN_STEP_1_ID),
            "target": str(_GOLDEN_STEP_4_ID),
            "kind": "input_bindings.question",
            "source_step_order": 1,
            "target_step_order": 4,
            "style": "dashed",
            "label": "underlag",
        },
        {
            "source": str(_GOLDEN_STEP_2_ID),
            "target": str(_GOLDEN_STEP_4_ID),
            "kind": "input_bindings.question",
            "source_step_order": 2,
            "target_step_order": 4,
            "style": "dashed",
            "label": "underlag",
        },
        {
            "source": str(_GOLDEN_STEP_4_ID),
            "target": "output",
            "kind": "flow_output",
            "source_step_order": 4,
            "target_step_order": None,
            "style": None,
            "label": None,
        },
    ],
}


def _step(
    *, step_order: int, input_source: str, output_type: str = "text"
) -> dict[str, object]:
    return {
        "step_id": str(uuid4()),
        "step_order": step_order,
        "user_description": f"Step {step_order}",
        "input_source": input_source,
        "input_type": "text",
        "output_type": output_type,
        "output_mode": "pass_through",
        "mcp_policy": "inherit",
        "output_classification_override": 2 if step_order == 1 else None,
    }


def _flow_step(step_order: int, **updates: object) -> FlowStep:
    step = FlowStep(
        id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=f"Step {step_order}",
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type="text",
        mcp_policy="inherit",
    )
    return step.model_copy(update=updates)


def _golden_graph_steps() -> list[dict[str, object]]:
    return [
        {
            "step_id": str(_GOLDEN_STEP_1_ID),
            "step_order": 1,
            "user_description": "Collect intake",
            "input_source": "flow_input",
            "input_type": "text",
            "output_type": "text",
            "output_mode": "pass_through",
            "mcp_policy": "inherit",
            "output_classification_override": 2,
        },
        {
            "step_id": str(_GOLDEN_STEP_2_ID),
            "step_order": 2,
            "user_description": "Summarize intake",
            "input_source": "previous_step",
            "input_type": "text",
            "output_type": "json",
            "output_mode": "pass_through",
            "mcp_policy": "inherit",
            "output_classification_override": None,
        },
        {
            "step_id": str(_GOLDEN_STEP_3_ID),
            "step_order": 3,
            "user_description": "Merge all prior context",
            "input_source": "all_previous_steps",
            "input_type": "text",
            "output_type": "text",
            "output_mode": "pass_through",
            "mcp_policy": "inherit",
            "output_classification_override": None,
        },
        {
            "step_id": str(_GOLDEN_STEP_4_ID),
            "step_order": 4,
            "user_description": "Draft final response",
            "input_source": "previous_step",
            "input_type": "text",
            "output_type": "docx",
            "output_mode": "template_fill",
            "mcp_policy": "inherit",
            "output_classification_override": None,
            "input_bindings": {
                "question": (
                    "Use intake: {{ step_1.output.text }} and summary: "
                    "{{ step_2.output.structured.summary }}"
                )
            },
        },
    ]


def _golden_step_result() -> FlowStepResult:
    now = datetime(2026, 3, 17, 10, 5, 30, tzinfo=timezone.utc)
    return FlowStepResult(
        id=_GOLDEN_RESULT_ID,
        flow_run_id=_GOLDEN_RUN_ID,
        flow_id=_GOLDEN_FLOW_ID,
        tenant_id=_GOLDEN_TENANT_ID,
        step_id=_GOLDEN_STEP_4_ID,
        step_order=4,
        num_tokens_input=11,
        num_tokens_output=17,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


def _assert_example_keys_belong_to_model(
    *, model: type[BaseModel], example: dict[str, object]
) -> None:
    assert set(example) <= set(model.model_fields)


def test_graph_response_example_matches_public_model() -> None:
    _assert_example_keys_belong_to_model(
        model=GraphResponse,
        example=GRAPH_RESPONSE_EXAMPLE,
    )
    for node in GRAPH_RESPONSE_EXAMPLE["nodes"]:
        _assert_example_keys_belong_to_model(model=GraphNode, example=node)
    for edge in GRAPH_RESPONSE_EXAMPLE["edges"]:
        _assert_example_keys_belong_to_model(model=GraphEdge, example=edge)

    response = GraphResponse.model_validate(GRAPH_RESPONSE_EXAMPLE)

    assert isinstance(response.nodes[0], GraphNode)
    assert isinstance(response.edges[0], GraphEdge)


def test_graph_response_parses_typed_nodes_and_edges() -> None:
    response = GraphResponse.model_validate(
        {
            "nodes": [
                {"id": "input", "label": "Input", "type": "input"},
                {
                    "id": "step-1",
                    "label": "Step 1",
                    "type": "llm",
                    "step_order": 1,
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_type": "json",
                    "output_mode": "pass_through",
                    "mcp_policy": "inherit",
                    "run_status": "completed",
                },
            ],
            "edges": [
                {
                    "source": "input",
                    "target": "step-1",
                    "kind": "flow_input",
                    "source_step_order": 0,
                    "target_step_order": 1,
                }
            ],
        }
    )

    assert isinstance(response.nodes[0], GraphNode)
    assert isinstance(response.edges[0], GraphEdge)
    assert response.nodes[1].run_status == "completed"


def test_graph_builders_return_typed_models_without_changing_serialized_response() -> (
    None
):
    nodes, edges = build_graph_from_steps(_golden_graph_steps())

    assert all(isinstance(node, GraphNode) for node in nodes)
    assert all(isinstance(edge, GraphEdge) for edge in edges)

    enriched_nodes = enrich_nodes_with_run_results(nodes, [_golden_step_result()])
    response = build_graph_response(_golden_graph_steps(), [_golden_step_result()])

    assert response.nodes == enriched_nodes
    assert response.edges == edges
    assert response.model_dump(mode="json") == _GOLDEN_GRAPH_RESPONSE


def test_enrich_nodes_with_run_results_uses_typed_step_result_fields() -> None:
    now = datetime.now(timezone.utc)
    flow_run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    step_id = uuid4()
    nodes = [
        GraphNode(id="input", label="Input", type="input"),
        GraphNode(id=str(step_id), label="Step", type="llm", step_order=1),
    ]
    step_results = [
        FlowStepResult(
            id=uuid4(),
            flow_run_id=flow_run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            step_id=step_id,
            step_order=1,
            num_tokens_input=11,
            num_tokens_output=17,
            status=FlowStepResultStatus.COMPLETED,
            error_message=None,
            created_at=now,
            updated_at=now,
        )
    ]

    enriched = enrich_nodes_with_run_results(nodes, step_results)

    llm_node = next(node for node in enriched if node.type == "llm")
    assert llm_node.run_status == "completed"
    assert llm_node.num_tokens_input == 11
    assert llm_node.num_tokens_output == 17
    assert llm_node.error_message is None


def test_build_graph_includes_explicit_underlag_dependencies() -> None:
    steps = [
        _step(step_order=1, input_source="flow_input"),
        _step(step_order=2, input_source="previous_step", output_type="json"),
        {
            **_step(step_order=3, input_source="previous_step"),
            "input_bindings": {
                "question": (
                    "Rapport: {{ step_2.output.structured.summary }}\n\n"
                    "Transkribering: {{ step_1.output.text }}"
                )
            },
        },
    ]

    _, edges = build_graph_from_steps(steps)
    step_1_id = str(steps[0]["step_id"])
    step_3_id = str(steps[2]["step_id"])

    assert any(
        edge.source == step_1_id
        and edge.target == step_3_id
        and edge.kind == "input_bindings.question"
        and edge.source_step_order == 1
        and edge.target_step_order == 3
        for edge in edges
    )


def test_validate_steps_and_graph_accept_same_explicit_underlag_dependency() -> None:
    flow_steps = [
        _flow_step(1),
        _flow_step(2, output_type=FlowOutputType.JSON),
        _flow_step(
            3,
            input_bindings={
                "question": (
                    "Rapport: {{ step_2.output.structured.summary }}\n\n"
                    "Transkribering: {{ step_1.output.text }}"
                )
            },
        ),
    ]

    validate_steps(flow_steps)

    graph_steps = [
        {**step.model_dump(mode="json"), "step_id": str(step.id)} for step in flow_steps
    ]
    _, edges = build_graph_from_steps(graph_steps)

    assert any(
        edge.source_step_order == 1
        and edge.target_step_order == 3
        and edge.kind == "input_bindings.question"
        for edge in edges
    )


def test_build_graph_adds_flow_input_edge_for_non_first_flow_input_step() -> None:
    steps = [
        _step(step_order=1, input_source="flow_input"),
        _step(step_order=2, input_source="flow_input"),
    ]

    _, edges = build_graph_from_steps(steps)
    step_2_id = str(steps[1]["step_id"])

    assert any(
        edge.source == "input"
        and edge.target == step_2_id
        and edge.kind == "flow_input"
        for edge in edges
    )


def test_build_graph_emits_dependency_metadata_fields() -> None:
    steps = [
        _step(step_order=1, input_source="flow_input"),
        _step(step_order=2, input_source="previous_step"),
    ]

    _, edges = build_graph_from_steps(steps)
    dependency_edge = next(
        edge
        for edge in edges
        if edge.source == str(steps[0]["step_id"])
        and edge.target == str(steps[1]["step_id"])
    )

    assert dependency_edge.kind == "previous_step"
    assert dependency_edge.source_step_order == 1
    assert dependency_edge.target_step_order == 2


def test_build_graph_includes_step_output_classification_override() -> None:
    steps = [_step(step_order=1, input_source="flow_input")]

    nodes, _ = build_graph_from_steps(steps)
    llm_node = next(node for node in nodes if node.type == "llm")

    assert llm_node.output_classification_override == 2


def test_build_graph_connects_all_terminal_steps_to_output() -> None:
    steps = [
        _step(step_order=1, input_source="flow_input"),
        _step(step_order=2, input_source="flow_input"),
        _step(step_order=3, input_source="previous_step"),
    ]

    _, edges = build_graph_from_steps(steps)
    step_1_id = str(steps[0]["step_id"])
    step_3_id = str(steps[2]["step_id"])

    assert any(edge.source == step_1_id and edge.target == "output" for edge in edges)
    assert any(edge.source == step_3_id and edge.target == "output" for edge in edges)


def test_build_graph_connects_empty_definition_to_output() -> None:
    nodes, edges = build_graph_from_steps([])

    assert [node.id for node in nodes] == ["input", "output"]
    assert edges == [
        GraphEdge(
            source="input",
            target="output",
            kind="empty",
            source_step_order=0,
            target_step_order=None,
            style="dashed",
        )
    ]


def test_build_graph_marks_template_fill_steps_as_assembly_nodes() -> None:
    steps = [
        {
            **_step(step_order=1, input_source="previous_step", output_type="docx"),
            "output_mode": "template_fill",
        }
    ]

    nodes, _ = build_graph_from_steps(steps)
    assembly_node = next(node for node in nodes if node.id == str(steps[0]["step_id"]))

    assert assembly_node.type == "assembly"
