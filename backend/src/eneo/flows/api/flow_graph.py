from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from pydantic import BaseModel, ConfigDict
from pydantic.config import JsonDict

from eneo.flows.domain.flow import FlowPersistedJsonObject, FlowStepResult
from eneo.flows.step_lineage import (
    build_step_ref_mapping,
    resolve_reference_step_orders,
)
from eneo.flows.template_reference_analyzer import analyze_template

GRAPH_RESPONSE_EXAMPLE: JsonDict = {
    "nodes": [
        {"id": "step-1", "label": "Transcribe uploaded audio", "type": "step"},
        {"id": "step-2", "label": "Create PDF summary", "type": "step"},
    ],
    "edges": [
        {"source": "step-1", "target": "step-2"},
    ],
}


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    step_order: int | None = None
    input_source: str | None = None
    input_type: str | None = None
    output_type: str | None = None
    output_mode: str | None = None
    mcp_policy: str | None = None
    output_classification_override: int | None = None
    run_status: str | None = None
    num_tokens_input: int | None = None
    num_tokens_output: int | None = None
    error_message: str | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: str | None = None
    source_step_order: int | None = None
    target_step_order: int | None = None
    style: str | None = None
    label: str | None = None


class GraphResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": GRAPH_RESPONSE_EXAMPLE})

    nodes: list[GraphNode]
    edges: list[GraphEdge]


def build_graph_from_steps(
    steps: Sequence[FlowPersistedJsonObject],
) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes: list[GraphNode] = [
        GraphNode(id="input", label="Input", type="input"),
    ]
    edges: list[GraphEdge] = []

    sorted_steps = sorted(steps, key=lambda item: int(item["step_order"]))
    for step in sorted_steps:
        step_id = str(step.get("step_id") or step.get("id"))
        label = step.get("user_description") or f"Steg {step['step_order']}"
        output_mode = step.get("output_mode")
        nodes.append(
            GraphNode(
                id=step_id,
                label=label,
                type="assembly" if output_mode == "template_fill" else "llm",
                step_order=int(step["step_order"]),
                input_source=step.get("input_source"),
                input_type=step.get("input_type"),
                output_type=step.get("output_type"),
                output_mode=output_mode,
                mcp_policy=step.get("mcp_policy"),
                output_classification_override=step.get(
                    "output_classification_override"
                ),
            )
        )

    nodes.append(GraphNode(id="output", label="Output", type="output"))
    step_ref_mapping = build_step_ref_mapping(sorted_steps)

    for step in sorted_steps:
        step_id = str(step.get("step_id") or step.get("id"))
        step_order = int(step["step_order"])
        input_source = step.get("input_source")

        if input_source in {"flow_input", "http_get", "http_post"}:
            style = "dashed" if input_source != "flow_input" else None
            edges.append(
                GraphEdge(
                    source="input",
                    target=step_id,
                    kind=input_source,
                    source_step_order=0,
                    target_step_order=step_order,
                    style=style,
                )
            )

        if input_source == "previous_step" and step_order > 1:
            prev = next(
                (
                    item
                    for item in sorted_steps
                    if int(item["step_order"]) == step_order - 1
                ),
                None,
            )
            if prev is not None:
                edges.append(
                    GraphEdge(
                        source=str(prev.get("step_id") or prev.get("id")),
                        target=step_id,
                        kind="previous_step",
                        source_step_order=int(prev["step_order"]),
                        target_step_order=step_order,
                    )
                )
        elif input_source == "all_previous_steps":
            for prev in sorted_steps:
                if int(prev["step_order"]) < step_order:
                    edges.append(
                        GraphEdge(
                            source=str(prev.get("step_id") or prev.get("id")),
                            target=step_id,
                            kind="all_previous_steps",
                            source_step_order=int(prev["step_order"]),
                            target_step_order=step_order,
                            style="dashed",
                            label="aggregated",
                        )
                    )
            edges.append(
                GraphEdge(
                    source="input",
                    target=step_id,
                    kind="all_previous_steps",
                    source_step_order=0,
                    target_step_order=step_order,
                    style="dashed",
                )
            )

        existing_upstream_orders = {
            edge.source_step_order
            for edge in edges
            if edge.target == step_id
            and edge.source_step_order is not None
            and edge.source_step_order > 0
        }
        for upstream_order in _binding_upstream_orders(
            step=step,
            step_ref_mapping=step_ref_mapping,
        ):
            if upstream_order in existing_upstream_orders:
                continue
            upstream = next(
                (
                    item
                    for item in sorted_steps
                    if int(item["step_order"]) == upstream_order
                ),
                None,
            )
            if upstream is None:
                continue
            edges.append(
                GraphEdge(
                    source=str(upstream.get("step_id") or upstream.get("id")),
                    target=step_id,
                    kind="input_bindings.question",
                    source_step_order=upstream_order,
                    target_step_order=step_order,
                    style="dashed",
                    label="underlag",
                )
            )

    if sorted_steps:
        step_ids = {str(step.get("step_id") or step.get("id")) for step in sorted_steps}
        source_step_ids = {
            edge.source
            for edge in edges
            if edge.source in step_ids and edge.target in step_ids
        }
        terminal_steps = [
            step
            for step in sorted_steps
            if str(step.get("step_id") or step.get("id")) not in source_step_ids
        ]
        for step in terminal_steps:
            edges.append(
                GraphEdge(
                    source=str(step.get("step_id") or step.get("id")),
                    target="output",
                    kind="flow_output",
                    source_step_order=int(step["step_order"]),
                    target_step_order=None,
                )
            )
    else:
        edges.append(
            GraphEdge(
                source="input",
                target="output",
                kind="empty",
                source_step_order=0,
                target_step_order=None,
                style="dashed",
            )
        )

    return nodes, edges


def _binding_upstream_orders(
    *,
    step: FlowPersistedJsonObject,
    step_ref_mapping: dict[str, int],
) -> list[int]:
    """Return upstream orders referenced by explicit underlag."""
    bindings = step.get("input_bindings")
    if not isinstance(bindings, dict):
        return []
    bindings_dict = cast(dict[str, object], bindings)
    question = bindings_dict.get("question")
    if not isinstance(question, str) or not question.strip():
        return []

    step_order = int(step["step_order"])
    references = analyze_template(
        question,
        step_refs=step_ref_mapping,
        form_field_names=set(),
    )
    return resolve_reference_step_orders(
        references=references,
        max_prior_step_order=step_order - 1,
    )


def enrich_nodes_with_run_results(
    nodes: Sequence[GraphNode],
    step_results: Sequence[FlowStepResult],
) -> list[GraphNode]:
    by_step_id = {str(item.step_id): item for item in step_results}

    enriched: list[GraphNode] = []
    for node in nodes:
        if node.type not in {"llm", "assembly"}:
            enriched.append(node)
            continue
        result = by_step_id.get(node.id)
        if result is None:
            enriched.append(node)
            continue
        enriched.append(
            node.model_copy(
                update={
                    "run_status": result.status.value,
                    "num_tokens_input": result.num_tokens_input,
                    "num_tokens_output": result.num_tokens_output,
                    "error_message": result.error_message,
                }
            )
        )
    return enriched


def build_graph_response(
    steps: Sequence[FlowPersistedJsonObject],
    step_results: Sequence[FlowStepResult] = (),
) -> GraphResponse:
    nodes, edges = build_graph_from_steps(steps)
    if step_results:
        nodes = enrich_nodes_with_run_results(nodes, step_results)
    return GraphResponse(nodes=nodes, edges=edges)
