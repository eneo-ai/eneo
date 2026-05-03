"""Task-specific prompt for final AI Builder plan proposal.

This prompt is intentionally not the planner union contract. The server
has already selected the phase; the model only drafts semantic flow
content through the create/edit tool schema.
"""

from __future__ import annotations

from typing import Any, cast

from intric.flows.ai_builder.ai_builder_mcp_intent import (
    MCP_SELECTION_WITHOUT,
    mcp_selected_server_refs_from_values,
)
from intric.flows.ai_builder.ai_builder_mcp_resources import (
    AIBuilderMCPResourceInput,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceReferenceMaterial,
    build_ai_builder_resource_catalog,
    build_ai_builder_resource_reference_material,
)
from intric.flows.ai_builder.planning_state import PlanningState


def build_plan_proposal_system_prompt(
    *,
    planning_state: PlanningState,
    confirmed_requirements: dict[str, Any] | None,
    attachment_context: str | None,
    flow_context: str | None,
    is_edit_mode: bool,
    available_models: list[dict[str, Any]] | None = None,
    available_kbs: list[dict[str, Any]] | None = None,
    available_mcps: AIBuilderMCPResourceInput = None,
    mcp_selection_values: set[str] | frozenset[str] | None = None,
    plan_revision_context: str | None = None,
) -> str:
    """Build a compact task prompt for create/edit flow proposal."""

    submission_tool = "edit_flow" if is_edit_mode else "outline_flow"
    selected_mcp_server_refs = mcp_selected_server_refs_from_values(
        set(mcp_selection_values or ())
    )
    resource_material = build_ai_builder_resource_reference_material(
        catalog=build_ai_builder_resource_catalog(
            available_models=available_models,
            available_kbs=available_kbs,
            available_mcps=available_mcps,
        ),
        selected_mcp_server_refs=selected_mcp_server_refs,
    )
    create_mode_rules = (
        [
            "- In create mode, describe semantic flow intent in outline_flow; do not choose Flow mechanics.",
            "- Use input_fields only for secondary inmatningsfält/input variables the user fills in at runtime.",
            "- Do not add an input_field for the primary text, document, file, or audio material being processed; the backend supplies that from the committed architecture.",
            "- Runtime metadata policy is enforced by the compiler; leave input_fields empty unless resolved slots or confirmed requirements clearly ask for runtime metadata.",
            "- For committed audio input, the backend inserts the first transcription/upload step; start outline_flow steps with the analysis, structuring, or synthesis work after transcription.",
            "- The backend compiles step topology, underlag/input_bindings, runtime uploads, step refs, output modes, and document delivery.",
        ]
        if not is_edit_mode
        else []
    )
    lines = [
        "You are drafting an Eneo Flow plan.",
        "",
        "The backend has already completed discovery and selected this turn's phase.",
        f"Call exactly one `{submission_tool}` tool. Do not ask a question, do not confirm requirements, and do not return prose only.",
        "",
        "Design rules:",
        "- Use a short human-readable `flow_name` with words and spaces; never copy internal pattern ids, capability ids, or snake_case tokens into the name.",
        "- Use as many steps as the requested workflow needs, up to the tool schema limit.",
        "- Prefer a clear multi-step flow for complex work instead of one overloaded step.",
        "- Use JSON output fields when later steps need specific structured facts.",
        "- Describe each step's semantic work; the backend derives runtime uploads and final output mechanics from the committed architecture.",
        "- Do not author field-level previous-step paths; let the backend wire dataflow.",
        "- Do not write template variables, raw JSON Schema, raw input bindings, IDs, hashes, timestamps, or backend-owned refs.",
        "- Exception: when the Available resources section gives canonical resource refs, use those refs only in their dedicated fields (`model_ref`, `knowledge_refs`, `mcp_server_refs`, `mcp_tool_refs`).",
        "- The backend will compile, validate, and persist the plan for user approval.",
        *create_mode_rules,
        "",
        "Committed architecture:",
        _architecture_block(planning_state),
        "",
        "Resolved planning slots:",
        _resolved_slots_block(planning_state),
        "",
        "Confirmed requirements:",
        _confirmed_requirements_block(confirmed_requirements),
    ]
    if flow_context:
        lines.extend(["", "Existing flow context:", flow_context])
    resource_context = _resource_context_block(resource_material)
    if resource_context:
        lines.extend(["", "Available resources:", resource_context])
    mcp_decision_context = _mcp_selection_context_block(
        mcp_selection_values,
        resource_material=resource_material,
    )
    if mcp_decision_context:
        lines.extend(["", "MCP selection decision:", mcp_decision_context])
    if plan_revision_context:
        lines.extend(["", plan_revision_context])
    if attachment_context:
        lines.extend(["", "Attachment context:", attachment_context])
    return "\n".join(lines)


def _architecture_block(planning_state: PlanningState) -> str:
    commit = planning_state.architecture_commit
    if commit is None:
        return "- No committed architecture is present. Create the safest valid plan."
    tuples = [
        f"- {triple.input_type} -> {triple.output_type} ({triple.output_mode})"
        for triple in commit.tuples_chain
    ]
    return "\n".join(
        [
            *tuples,
            "- implementation_strategy: server-selected capability profile (ids hidden from user-facing text)",
        ]
    )


def _resolved_slots_block(planning_state: PlanningState) -> str:
    if not planning_state.resolved_slots:
        return "- none"
    return "\n".join(
        f"- {name}: {slot.value}"
        for name, slot in sorted(planning_state.resolved_slots.items())
    )


def _confirmed_requirements_block(
    confirmed_requirements: dict[str, Any] | None,
) -> str:
    if not confirmed_requirements:
        return "- none"

    lines: list[str] = []
    for key in (
        "summary",
        "input_description",
        "output_description",
    ):
        value = confirmed_requirements.get(key)
        if isinstance(value, str) and value.strip():
            lines.append(f"- {key}: {value.strip()}")

    key_decisions = confirmed_requirements.get("key_decisions")
    if isinstance(key_decisions, list) and key_decisions:
        lines.append("- key_decisions:")
        for raw_decision in cast(list[Any], key_decisions):
            if not isinstance(raw_decision, dict):
                continue
            decision = cast(dict[str, Any], raw_decision)
            topic = decision.get("topic")
            selected = decision.get("decision")
            if isinstance(topic, str) and isinstance(selected, str):
                lines.append(f"  - {topic}: {selected}")

    assumptions = confirmed_requirements.get("assumptions")
    if isinstance(assumptions, list) and assumptions:
        lines.append("- assumptions:")
        for assumption in cast(list[Any], assumptions):
            if isinstance(assumption, str) and assumption.strip():
                lines.append(f"  - {assumption.strip()}")

    return "\n".join(lines) if lines else "- none"


def _resource_context_block(
    material: AIBuilderResourceReferenceMaterial,
) -> str:
    sections: list[str] = []
    if material.models:
        sections.append("Models:")
        sections.extend(
            f"- {entry.prompt_fields(ref_label='ref')}" for entry in material.models
        )
    if material.knowledge_bases:
        sections.append("Knowledge bases:")
        sections.extend(
            f"- {entry.prompt_fields(ref_label='ref')}"
            for entry in material.knowledge_bases
        )
    if material.mcp_servers:
        sections.append("MCP metadata:")
        sections.append(
            "- Planning may read this metadata but must not execute MCP tools. "
            "Use MCP refs only when a step needs external tools or live data."
        )
        for server in material.mcp_servers:
            sections.append(f"- {server.prompt_fields(ref_label='server_ref')}")
            for tool in material.mcp_tools:
                if tool.parent_ref != server.ref:
                    continue
                sections.append(f"  - {tool.prompt_fields(ref_label='tool_ref')}")
    return "\n".join(sections)


def _mcp_selection_context_block(
    mcp_selection_values: set[str] | frozenset[str] | None,
    *,
    resource_material: AIBuilderResourceReferenceMaterial,
) -> str | None:
    values = set(mcp_selection_values or set())
    if not values:
        return None
    if MCP_SELECTION_WITHOUT in values:
        return (
            "- The user chose to continue without MCP tools. Do not attach "
            "`mcp_server_refs` or `mcp_tool_refs`, even if earlier text mentioned MCP.\n"
            "- Without MCP tools, do not claim that the flow fetches live or external "
            "data by itself. If the task needs live data, collect it as runtime input "
            "or make the limitation explicit in the step instructions."
        )
    selected_server_refs = sorted(
        entry.ref for entry in resource_material.selected_mcp_servers
    )
    if not selected_server_refs:
        return None
    refs = ", ".join(f"`{ref}`" for ref in selected_server_refs)
    lines = [
        f"- The user allowed these MCP server refs: {refs}.",
        "- Use MCP refs only on steps that need external tools or live data.",
        "- Prefer specific `mcp_tool_refs` over attaching a whole server; do not attach MCP refs to unrelated analysis or formatting steps.",
    ]
    selected_tool_lines = _selected_mcp_tool_lines(
        resource_material=resource_material,
    )
    if selected_tool_lines:
        lines.append("- Selected MCP tools available for step-level use:")
        lines.extend(selected_tool_lines)
    return "\n".join(lines)


def _selected_mcp_tool_lines(
    *,
    resource_material: AIBuilderResourceReferenceMaterial,
) -> list[str]:
    return [
        f"  - {tool.prompt_fields(ref_label='tool_ref', include_parent_ref=True)}"
        for tool in resource_material.selected_mcp_tools
    ]


__all__ = ["build_plan_proposal_system_prompt"]
