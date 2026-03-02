from __future__ import annotations

from uuid import uuid4

from intric.flows.api.flow_graph import build_graph_from_steps


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
