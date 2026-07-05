from __future__ import annotations

from typing import Any, cast

from eneo.flows.flow_run_provenance import normalize_rag_payload
from eneo.flows.input_binding_contract_rules import effective_question_binding
from eneo.flows.runtime.models import RunExecutionState, RuntimeStep
from eneo.flows.source_display import (
    format_source_container_display_name,
    format_source_container_label,
    format_source_display_name,
    resolve_reference_title,
)
from eneo.flows.step_lineage import resolve_upstream_step_orders
from eneo.flows.template_reference_analyzer import analyze_template

ReferencePayload = dict[str, Any]
SourceEntry = dict[str, Any]


def collect_inherited_citation_context(
    *,
    step: RuntimeStep,
    state: RunExecutionState,
) -> dict[str, Any]:
    question_template = effective_question_binding(step.input_bindings)
    references = (
        analyze_template(
            question_template,
            step_refs=state.step_ref_mapping,
            form_field_names=set(),
        )
        if question_template is not None
        else []
    )
    upstream_orders = resolve_upstream_step_orders(
        input_source=step.input_source,
        step_order=step.step_order,
        references=references,
        max_prior_step_order=max(
            (order for order in state.completed_by_order), default=0
        ),
    )
    sources_by_id: dict[str, dict[str, Any]] = {}
    grounded_orders: list[int] = []
    grounded_labels: list[str] = []
    for upstream_order in upstream_orders:
        prior_result = state.completed_by_order.get(upstream_order)
        if prior_result is None:
            continue
        input_payload = prior_result.input_payload_json
        rag = input_payload.get("rag") if isinstance(input_payload, dict) else None
        normalized_rag = normalize_rag_payload(rag)
        if not isinstance(normalized_rag, dict):
            continue
        prompt_context = normalized_rag.get("prompt_context")
        references_payload = normalized_rag.get("references")
        if not isinstance(prompt_context, dict) or not isinstance(
            references_payload, list
        ):
            continue
        prompt_context_dict = cast(ReferencePayload, prompt_context)
        references_list = cast(list[Any], references_payload)
        included_source_ids = [
            source_id
            for source_id in cast(
                list[Any], prompt_context_dict.get("included_source_ids", [])
            )
            if isinstance(source_id, str) and source_id.strip()
        ]
        if not included_source_ids:
            continue
        grouped_reference_map: dict[str, ReferencePayload] = {}
        for reference in references_list:
            if not isinstance(reference, dict):
                continue
            reference_dict = cast(ReferencePayload, reference)
            reference_id = reference_dict.get("id")
            if isinstance(reference_id, str) and reference_id.strip():
                grouped_reference_map[reference_id] = reference_dict
        grounded_orders.append(upstream_order)
        label = state.step_names_by_order.get(upstream_order)
        if isinstance(label, str) and label.strip():
            grounded_labels.append(label.strip())
        for source_id in included_source_ids:
            reference = grouped_reference_map.get(source_id)
            if reference is None:
                continue
            raw_id_short = reference.get("id_short")
            existing = sources_by_id.get(source_id)
            source_entry: SourceEntry = existing or {
                "id": source_id,
                "id_short": (
                    raw_id_short
                    if isinstance(raw_id_short, str) and raw_id_short.strip()
                    else source_id[:8]
                ),
                "title": resolve_reference_title(reference),
                "source_title_raw": reference.get("source_title_raw"),
                "source_display_name": (
                    reference.get("source_display_name")
                    if isinstance(reference.get("source_display_name"), str)
                    else None
                ),
                "source_url": reference.get("source_url"),
                "source_kind": reference.get("source_kind"),
                "source_container_kind": reference.get("source_container_kind"),
                "source_container_name_raw": reference.get("source_container_name_raw"),
                "source_container_label": (
                    reference.get("source_container_label")
                    or format_source_container_label(reference)
                ),
                "source_container_display_name": (
                    reference.get("source_container_display_name")
                    or format_source_container_display_name(reference)
                ),
                "source_step_orders": [],
                "source_step_labels": [],
            }
            title = source_entry.get("title")
            if isinstance(title, str) and title.strip():
                source_entry["display_title"] = format_source_display_name(title)
            source_step_orders = cast(list[int], source_entry["source_step_orders"])
            if upstream_order not in source_step_orders:
                source_step_orders.append(upstream_order)
            source_step_labels = cast(list[str], source_entry["source_step_labels"])
            if (
                isinstance(label, str)
                and label.strip()
                and label.strip() not in source_step_labels
            ):
                source_step_labels.append(label.strip())
            sources_by_id[source_id] = source_entry

    ordered_sources: list[SourceEntry] = sorted(
        sources_by_id.values(),
        key=lambda item: (
            min(cast(list[int], item.get("source_step_orders", [9999]))),
            str(item.get("id")),
        ),
    )
    return {
        "upstream_step_orders": list(dict.fromkeys(grounded_orders)),
        "upstream_step_labels": list(dict.fromkeys(grounded_labels)),
        "available_sources": ordered_sources,
        "available_source_ids": [source["id"] for source in ordered_sources],
    }


def build_inherited_citation_prompt_appendix(context: dict[str, Any]) -> str | None:
    sources = context.get("available_sources")
    if not isinstance(sources, list) or not sources:
        return None
    lines = [
        "Inherited source grounding:",
        "You are synthesizing grounded outputs from earlier flow steps.",
        'When a statement in your answer depends on grounded information from those earlier steps, cite the original source id immediately after the statement using <inref id="<source_id>"/>.',
        "Only cite source ids from the inherited source catalog below.",
        "Inherited source catalog (source_id | title | url | grounded_in_step):",
    ]
    for source in cast(list[Any], sources):
        if not isinstance(source, dict):
            continue
        source_dict = cast(SourceEntry, source)
        source_id = source_dict.get("id_short") or source_dict.get("id")
        if not isinstance(source_id, str) or not source_id.strip():
            continue
        title = (
            source_dict.get("display_title")
            or source_dict.get("title")
            or source_dict.get("source_display_name")
        )
        url = source_dict.get("source_url")
        grounded_orders_raw = source_dict.get("source_step_orders")
        grounded_orders = (
            cast(list[Any], grounded_orders_raw)
            if isinstance(grounded_orders_raw, list)
            else []
        )
        grounded_label = ",".join(
            str(order) for order in grounded_orders if isinstance(order, int)
        )
        line = f"- {source_id}"
        if isinstance(title, str) and title.strip():
            line += f" | {title.strip()}"
        if isinstance(url, str) and url.strip():
            line += f" | {url.strip()}"
        if grounded_label:
            line += f" | steps {grounded_label}"
        lines.append(line)
    return "\n".join(lines)
