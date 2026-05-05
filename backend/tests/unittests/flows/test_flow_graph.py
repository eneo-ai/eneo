from __future__ import annotations

from uuid import uuid4

from intric.flows.api.flow_graph import build_graph_from_steps
from intric.flows.enums import FlowOutputType
from intric.flows.flow import FlowStep
from intric.flows.flow_validators import validate_steps


def _step(*, step_order: int, input_source: str, output_type: str = "text") -> dict[str, object]:
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
        edge["source"] == step_1_id
        and edge["target"] == step_3_id
        and edge["kind"] == "input_bindings.question"
        and edge["source_step_order"] == 1
        and edge["target_step_order"] == 3
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
        {**step.model_dump(mode="json"), "step_id": str(step.id)}
        for step in flow_steps
    ]
    _, edges = build_graph_from_steps(graph_steps)

    assert any(
        edge["source_step_order"] == 1
        and edge["target_step_order"] == 3
        and edge["kind"] == "input_bindings.question"
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
        edge["source"] == "input"
        and edge["target"] == step_2_id
        and edge["kind"] == "flow_input"
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
        if edge["source"] == str(steps[0]["step_id"]) and edge["target"] == str(steps[1]["step_id"])
    )

    assert dependency_edge["kind"] == "previous_step"
    assert dependency_edge["source_step_order"] == 1
    assert dependency_edge["target_step_order"] == 2


def test_build_graph_includes_step_output_classification_override() -> None:
    steps = [_step(step_order=1, input_source="flow_input")]

    nodes, _ = build_graph_from_steps(steps)
    llm_node = next(node for node in nodes if node["type"] == "llm")

    assert llm_node["output_classification_override"] == 2


def test_build_graph_connects_all_terminal_steps_to_output() -> None:
    steps = [
        _step(step_order=1, input_source="flow_input"),
        _step(step_order=2, input_source="flow_input"),
        _step(step_order=3, input_source="previous_step"),
    ]

    _, edges = build_graph_from_steps(steps)
    step_1_id = str(steps[0]["step_id"])
    step_3_id = str(steps[2]["step_id"])

    assert any(edge["source"] == step_1_id and edge["target"] == "output" for edge in edges)
    assert any(edge["source"] == step_3_id and edge["target"] == "output" for edge in edges)


def test_build_graph_marks_template_fill_steps_as_assembly_nodes() -> None:
    steps = [
        {
            **_step(step_order=1, input_source="previous_step", output_type="docx"),
            "output_mode": "template_fill",
        }
    ]

    nodes, _ = build_graph_from_steps(steps)
    assembly_node = next(node for node in nodes if node["id"] == str(steps[0]["step_id"]))

    assert assembly_node["type"] == "assembly"
