"""Task-specific prompt for final AI Builder plan proposal.

This prompt is intentionally not the planner union contract. The server
has already selected the phase; the model only drafts semantic flow
content through the create/edit tool schema.
"""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_event_models import RequirementsSummaryPayload
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    MCP_SELECTION_WITHOUT,
    mcp_selected_server_refs_from_values,
)
from intric.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSections,
)
from intric.flows.ai_builder.ai_builder_requirements_state import (
    render_confirmed_requirements_proposal_prompt_block,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    AIBuilderResourceReferenceMaterial,
    build_ai_builder_resource_reference_material,
    render_resource_reference_block,
)
from intric.flows.ai_builder.ai_builder_result_contract import (
    derive_result_contract,
    render_result_contract_prompt_block,
)
from intric.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from intric.flows.ai_builder.planning_state import PlanningState


def build_plan_proposal_system_prompt(
    *,
    planning_state: PlanningState,
    confirmed_requirements: RequirementsSummaryPayload | None,
    attachment_context: str | None,
    flow_context: str | None,
    is_edit_mode: bool,
    mcp_selection_values: set[str] | frozenset[str] | None = None,
    resource_catalog: AIBuilderResourceCatalog,
    plan_revision_context: str | None = None,
    requested_output_sections: RequestedOutputSections | None = None,
) -> str:
    submission_tool = PROPOSE_FLOW_TOOL_NAME
    selected_mcp_server_refs = mcp_selected_server_refs_from_values(
        set(mcp_selection_values or ())
    )
    resource_material = build_ai_builder_resource_reference_material(
        catalog=resource_catalog,
        selected_mcp_server_refs=selected_mcp_server_refs,
    )
    create_mode_rules = (
        [
            "- In create mode, describe semantic flow intent in propose_flow; do not choose Flow mechanics.",
            "- Use input_fields only for secondary inmatningsfält/input variables the user fills in at runtime.",
            "- Do not add an input_field for the primary text, document, file, or audio material being processed; the backend supplies that from the committed architecture.",
            "- Runtime metadata policy is enforced by the compiler; leave input_fields empty unless resolved slots or confirmed requirements clearly ask for runtime metadata.",
            "- For committed audio input, the backend inserts the first transcription/upload step; start propose_flow steps with the analysis, structuring, or synthesis work after transcription unless the user explicitly asks to review, approve, or edit the transcript itself.",
            "- For that transcript-review case, include the leading transcription step with review_mode; the backend attaches the checkpoint to its inserted transcription/upload step.",
            "- When the user explicitly asks to review, approve, or edit a step output before later steps continue, set that step's review_mode. Do not model human review as a separate AI step or as instruction prose.",
            "- The backend compiles step topology, underlag/input_bindings, runtime input, step refs, output modes, and document delivery.",
        ]
        if not is_edit_mode
        else []
    )
    section_rule = _requested_output_sections_design_rule(requested_output_sections)
    terminal_document_rule = _terminal_document_design_rule(planning_state)
    result_contract_block = render_result_contract_prompt_block(
        derive_result_contract(planning_state)
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
        "- Direct text transformations such as translation, rewriting, correction, shortening, or summarizing a supplied snippet default to one text step; add JSON, review, form fields, or extra steps only when the user explicitly asks for them.",
        "- Prefer a clear multi-step flow for complex work instead of one overloaded step.",
        "- Use JSON output fields when later steps need specific structured facts.",
        *([section_rule] if section_rule is not None else []),
        *([terminal_document_rule] if terminal_document_rule is not None else []),
        "- Describe each step's semantic work; the backend derives runtime input and final output mechanics from the committed architecture.",
        "- Do not author field-level previous-step paths; let the backend wire dataflow.",
        "- Do not write template variables, raw JSON Schema, raw input bindings, IDs, hashes, timestamps, or backend-owned refs.",
        "- Exception: when the Available resources section gives portable resource slot refs, use those refs only in their dedicated fields (`model_ref`, `knowledge_refs`, `mcp_server_refs`, `mcp_tool_refs`).",
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
        render_confirmed_requirements_proposal_prompt_block(confirmed_requirements),
    ]
    if result_contract_block is not None:
        lines.extend(["", "Result contract:", result_contract_block])
    section_block = _requested_output_sections_block(requested_output_sections)
    if section_block is not None:
        lines.extend(["", "Requested output sections:", section_block])
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


def _requested_output_sections_design_rule(
    requested_output_sections: RequestedOutputSections | None,
) -> str | None:
    if (
        requested_output_sections is None
        or not requested_output_sections.high_confidence
    ):
        return None
    return (
        "- When the user names multiple output headings/sections for an AI-generated "
        "report or document, preserve those sections as semantic section-writing "
        "work and add final assembly before DOCX/PDF delivery. Group only tightly "
        "related sections when needed; do not apply this to sectioned form intake "
        "or simple transformations."
    )


def _terminal_document_design_rule(planning_state: PlanningState) -> str | None:
    commit = planning_state.architecture_commit
    if commit is None:
        return None
    if not any(triple.output_type in {"docx", "pdf"} for triple in commit.tuples_chain):
        return None
    return (
        "- For DOCX/PDF delivery, the final text step immediately before the "
        "renderer must output the complete document body. If the flow includes "
        "quality review or consistency checks, place that review before final "
        "assembly or make the review step rewrite the full revised final body; "
        "do not put review notes directly before DOCX/PDF rendering."
    )


def _requested_output_sections_block(
    requested_output_sections: RequestedOutputSections | None,
) -> str | None:
    if (
        requested_output_sections is None
        or not requested_output_sections.high_confidence
    ):
        return None
    return "\n".join(f"- {section}" for section in requested_output_sections.sections)


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


def _resource_context_block(
    material: AIBuilderResourceReferenceMaterial,
) -> str:
    rendered = render_resource_reference_block(material)
    sections: list[str] = []
    if rendered.models:
        sections.append("Models:")
        sections.append(rendered.models)
    if rendered.knowledge_bases:
        sections.append("Knowledge bases:")
        sections.append(rendered.knowledge_bases)
    if rendered.mcp:
        sections.append("MCP metadata:")
        sections.append(
            "- Planning may read this metadata but must not execute MCP tools. "
            "Use MCP refs only when a step needs external tools or live data."
        )
        sections.append(rendered.mcp)
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
