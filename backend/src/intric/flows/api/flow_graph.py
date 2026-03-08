from __future__ import annotations

from typing import Any


def build_graph_from_steps(steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = [
        {"id": "input", "label": "Input", "type": "input"},
    ]
    edges: list[dict[str, Any]] = []

    sorted_steps = sorted(steps, key=lambda item: int(item["step_order"]))
    for step in sorted_steps:
        step_id = str(step.get("step_id") or step.get("id"))
        label = step.get("user_description") or f"Steg {step['step_order']}"
        output_mode = step.get("output_mode")
        nodes.append(
            {
                "id": step_id,
                "label": label,
                "type": "assembly" if output_mode == "template_fill" else "llm",
                "step_order": step["step_order"],
                "input_source": step.get("input_source"),
                "input_type": step.get("input_type"),
                "output_type": step.get("output_type"),
                "output_mode": output_mode,
                "mcp_policy": step.get("mcp_policy"),
                "output_classification_override": step.get("output_classification_override"),
            }
        )

    nodes.append({"id": "output", "label": "Output", "type": "output"})

    for step in sorted_steps:
        step_id = str(step.get("step_id") or step.get("id"))
        step_order = int(step["step_order"])
        input_source = step.get("input_source")

        if input_source in {"flow_input", "http_get", "http_post"}:
            edge: dict[str, Any] = {
                "source": "input",
                "target": step_id,
                "kind": input_source,
                "source_step_order": 0,
                "target_step_order": step_order,
            }
            if input_source != "flow_input":
                edge["style"] = "dashed"
            edges.append(edge)

        if input_source == "previous_step" and step_order > 1:
            prev = next(
                (item for item in sorted_steps if int(item["step_order"]) == step_order - 1),
                None,
            )
            if prev is not None:
                edges.append(
                    {
                        "source": str(prev.get("step_id") or prev.get("id")),
                        "target": step_id,
                        "kind": "previous_step",
                        "source_step_order": int(prev["step_order"]),
                        "target_step_order": step_order,
                    }
                )
        elif input_source == "all_previous_steps":
            for prev in sorted_steps:
                if int(prev["step_order"]) < step_order:
                    edges.append(
                        {
                            "source": str(prev.get("step_id") or prev.get("id")),
                            "target": step_id,
                            "kind": "all_previous_steps",
                            "source_step_order": int(prev["step_order"]),
                            "target_step_order": step_order,
                            "style": "dashed",
                            "label": "aggregated",
                        }
                    )
            edges.append(
                {
                    "source": "input",
                    "target": step_id,
                    "kind": "all_previous_steps",
                    "source_step_order": 0,
                    "target_step_order": step_order,
                    "style": "dashed",
                }
            )

    if sorted_steps:
        step_ids = {str(step.get("step_id") or step.get("id")) for step in sorted_steps}
        source_step_ids = {
            str(edge["source"])
            for edge in edges
            if str(edge["source"]) in step_ids and str(edge["target"]) in step_ids
        }
        terminal_steps = [
            step for step in sorted_steps if str(step.get("step_id") or step.get("id")) not in source_step_ids
        ]
        for step in terminal_steps:
            edges.append(
                {
                    "source": str(step.get("step_id") or step.get("id")),
                    "target": "output",
                    "kind": "flow_output",
                    "source_step_order": int(step["step_order"]),
                    "target_step_order": None,
                }
            )
    else:
        edges.append(
            {
                "source": "input",
                "target": "output",
                "kind": "empty",
                "source_step_order": 0,
                "target_step_order": None,
                "style": "dashed",
            }
        )

    return nodes, edges


def enrich_nodes_with_run_results(
    nodes: list[dict[str, Any]],
    step_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_step_id = {
        str(item["step_id"]): item
        for item in step_results
        if item.get("step_id") is not None
    }
    by_step_order = {int(item["step_order"]): item for item in step_results}

    enriched: list[dict[str, Any]] = []
    for node in nodes:
        if node["type"] not in {"llm", "assembly"}:
            enriched.append(node)
            continue
        result = by_step_id.get(node["id"]) or by_step_order.get(int(node["step_order"]))
        if result is None:
            enriched.append(node)
            continue
        merged = dict(node)
        merged["run_status"] = result.get("status")
        merged["num_tokens_input"] = result.get("num_tokens_input")
        merged["num_tokens_output"] = result.get("num_tokens_output")
        merged["error_message"] = result.get("error_message")
        enriched.append(merged)
    return enriched
