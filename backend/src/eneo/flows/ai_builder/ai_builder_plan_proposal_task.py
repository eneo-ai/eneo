"""Task-specific prompt for final AI Builder plan proposal.

This prompt is intentionally not the planner union contract. The server
has already selected the phase; the model only drafts semantic flow
content through the create/edit tool schema.
"""

from __future__ import annotations

import json
from typing import assert_never

from eneo.flows.ai_builder.ai_builder_attachment_context import (
    render_ai_builder_evidence_value,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    CreateCompileContext,
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_event_models import RequirementsSummaryPayload
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    render_confirmed_requirements_proposal_prompt_block,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    AIBuilderResourceReferenceMaterial,
    build_ai_builder_resource_reference_material,
    render_resource_reference_block,
)
from eneo.flows.ai_builder.ai_builder_result_contract import (
    derive_result_contract,
    render_result_contract_prompt_block,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    project_schema_fields,
)
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.planning_state import (
    FileRoleEvidence,
    PlanningState,
    ResolvedSlot,
)


def build_plan_proposal_system_prompt(
    *,
    planning_state: PlanningState,
    confirmed_requirements: RequirementsSummaryPayload | None,
    attachment_context: str | None,
    flow_context: str | None,
    is_edit_mode: bool,
    resource_catalog: AIBuilderResourceCatalog,
    plan_revision_context: str | None = None,
    requested_output_sections: RequestedOutputSections | None = None,
    compile_context: CreateCompileContext | None = None,
) -> str:
    submission_tool = PROPOSE_FLOW_TOOL_NAME
    resource_material = build_ai_builder_resource_reference_material(
        catalog=resource_catalog,
    )
    create_mode_rules = (
        [
            "- In create mode, describe semantic flow intent in propose_flow; do not choose Flow mechanics.",
            "- Use input_fields only for secondary inmatningsfält/input variables the user fills in at runtime.",
            "- Do not add an input_field for the primary text, document, file, or audio material being processed; the backend supplies that from the committed architecture.",
            "- Runtime metadata policy is compiler-owned: do not invent input_fields from defaults. Declare secondary input_fields only when confirmed requirements, confirmed resolved slots, or the semantic workflow clearly needs runtime variables; if a resolved slot shows an explicit no-extra-fields decision, leave them empty.",
            "- For committed audio input, the backend inserts the first transcription/upload step; start propose_flow steps with the analysis, structuring, or synthesis work after transcription unless the user explicitly asks to review, approve, or edit the transcript itself.",
            "- For that transcript-review case, include the leading transcription step with review_mode; the backend attaches the checkpoint to its inserted transcription/upload step.",
            "- When the user explicitly asks to review, approve, or edit a step output before later steps continue, set that step's review_mode. Do not model human review as a separate AI step or as instruction prose.",
            "- Do not author field-level previous-step paths or text-output refs in create mode; the backend owns those underlag channels from the proposed step outputs and committed architecture.",
            "- The backend compiles step topology, backend-owned refs, underlag/input_bindings, runtime input, step refs, output modes, and document delivery.",
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
        "- JSON output field names are schema keys: use ASCII English names such as `summary` or `date_or_year`; put Swedish or other localized wording in descriptions and user-facing text.",
        "- For source-material reports, include every final-report fact or per-item short summary that must come from the source in the source-reading JSON output_fields. Do not leave user-named facts only in instructions or hide them inside generic facts/notes fields; later text or document steps should consume those fields instead of introducing new source-derived facts only in prose.",
        *([section_rule] if section_rule is not None else []),
        *([terminal_document_rule] if terminal_document_rule is not None else []),
        "- Describe each step's semantic work; the backend derives runtime input and final output mechanics from the committed architecture.",
        "- Do not write template variables, raw JSON Schema, raw input bindings, IDs, hashes, timestamps, step refs, or backend mechanics.",
        "- Exception: when the Available resources section gives portable resource slot refs, use those refs only in their dedicated fields (`model_ref`, `knowledge_refs`).",
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
    server_owned_fields_block = _server_owned_runtime_input_fields_block(
        compile_context or create_compile_context_from_planning_state(planning_state)
    )
    if not is_edit_mode and server_owned_fields_block is not None:
        lines.extend(
            [
                "",
                "Server-owned runtime input fields:",
                server_owned_fields_block,
            ]
        )
    file_roles_block = _file_roles_block(planning_state)
    if file_roles_block is not None:
        lines.extend(["", "Uploaded file roles:", file_roles_block])
    input_schema_block = _input_schema_evidence_block(planning_state)
    if input_schema_block is not None:
        lines.extend(["", "Input schema evidence:", input_schema_block])
    output_schema_block = _output_schema_evidence_block(planning_state)
    if output_schema_block is not None:
        lines.extend(["", "Output schema evidence:", output_schema_block])
    example_style_block = _example_output_style_evidence_block(planning_state)
    if example_style_block is not None:
        lines.extend(["", "Example-output style evidence:", example_style_block])
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
    if plan_revision_context:
        lines.extend(["", plan_revision_context])
    if attachment_context:
        lines.extend(["", "Attachment context:", attachment_context])
    return "\n".join(lines)


def _server_owned_runtime_input_fields_block(
    compile_context: CreateCompileContext | None,
) -> str | None:
    if compile_context is None or not compile_context.admitted_form_field_hints:
        return None

    lines: list[str] = []
    for field in compile_context.admitted_form_field_hints:
        contract: dict[str, object] = {
            "variable_name": field.variable_name,
            "field_type": field.field_type,
            "required": field.required,
            "label": field.label,
        }
        if field.options:
            contract["options"] = list(field.options)
        contract["provenance"] = field.provenance
        lines.append(f"- {json.dumps(contract, ensure_ascii=False)}")

    lines.extend(
        [
            "- Do not redeclare or rename these server-owned fields in input_fields.",
            "- Use each exact variable_name in uses_form_fields only on steps "
            "whose semantic work directly consumes it; every field needs at "
            "least one actual consumer.",
        ]
    )
    return "\n".join(lines)


def _requested_output_sections_design_rule(
    requested_output_sections: RequestedOutputSections | None,
) -> str | None:
    if (
        requested_output_sections is None
        or not requested_output_sections.high_confidence
        or len(requested_output_sections.sections) < 2
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
        "do not put review notes directly before DOCX/PDF rendering. Do not "
        "add a separate final conversion, formatting, render, PDF, or DOCX "
        "step; the backend adds the fixed renderer."
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
        f"- {triple.input_type.value} -> {triple.output_type.value} "
        f"({triple.output_mode.value})"
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
        f"- {name}: {slot.value} ({_resolved_slot_prompt_status(slot)})"
        for name, slot in sorted(planning_state.resolved_slots.items())
    )


def _resolved_slot_prompt_status(slot: ResolvedSlot) -> str:
    match slot.source:
        case "structured_answer" | "requirements_summary":
            return "confirmed"
        case "flow_default":
            return "from existing flow"
        case "attachment_structure":
            return "confirmed from attachment structure"
        case "policy_default":
            return "policy default assumption"
        case "heuristic":
            return f"heuristic inference, {slot.confidence} confidence"
        case "model":
            return f"model inference, {slot.confidence} confidence"
    return assert_never(slot.source)


def _file_roles_block(planning_state: PlanningState) -> str | None:
    if not planning_state.file_roles:
        return None
    return "\n".join(
        f"- {render_ai_builder_evidence_value(item.filename)}: {item.role} "
        f"({item.source}, {item.confidence} confidence"
        f"{_file_role_detail_prompt_suffix(item)})"
        for item in planning_state.file_roles
    )


def _file_role_detail_prompt_suffix(item: FileRoleEvidence) -> str:
    details = [
        f"has_readable_text: {str(item.has_readable_text).lower()}",
        f"coverage: {item.coverage}",
    ]
    candidate_roles = tuple(item.candidate_roles)
    if candidate_roles and candidate_roles != (item.role,):
        details.append("candidates: " + ", ".join(candidate_roles))
    if item.evidence:
        details.append(
            "evidence: "
            + ", ".join(
                render_ai_builder_evidence_value(marker) for marker in item.evidence[:6]
            )
        )
    return "; " + "; ".join(details)


def _output_schema_evidence_block(planning_state: PlanningState) -> str | None:
    evidence = planning_state.output_schema_evidence
    if evidence is None:
        return None
    projection = project_schema_fields(evidence.json_schema)
    fields = projection.fields
    field_text = (
        ", ".join(render_ai_builder_evidence_value(field) for field in fields)
        if fields
        else "top-level object"
    )
    if projection.truncated:
        field_text = (
            f"{field_text} "
            f"(showing {len(projection.fields)} of {projection.total_count})"
        )
    if evidence.source == "template_placeholders":
        coverage_line = (
            f"- placeholder coverage: {len(fields)} of {evidence.total_count} unique "
            "fields retained (truncated)"
            if evidence.truncated and evidence.total_count is not None
            else None
        )
        return "\n".join(
            [
                f"- source: {evidence.source}, {evidence.confidence} confidence",
                f"- template placeholder fields: {field_text}",
                *([coverage_line] if coverage_line is not None else []),
                "- Prefer source-derived output_fields for placeholders that can be "
                "extracted from uploaded documents; use input_fields only for values "
                "the user must provide at runtime.",
            ]
        )
    terminal_output = planning_state.resolved_slots.get("terminal_output")
    if terminal_output is None or terminal_output.value != "structured_json":
        return None
    if evidence.source == "inferred_example":
        return "\n".join(
            [
                f"- source: {evidence.source}, {evidence.confidence} confidence",
                f"- inferred top-level fields: {field_text}",
                "- Treat this as an open structural hint from a selected example, "
                "not as an explicit or closed contract. Do not invent required "
                "fields or validation constraints.",
            ]
        )
    return "\n".join(
        [
            f"- source: {evidence.source}, {evidence.confidence} confidence",
            f"- declared top-level fields: {field_text}",
            "- Use output_fields consistent with these user-declared fields.",
        ]
    )


def _input_schema_evidence_block(planning_state: PlanningState) -> str | None:
    evidence = planning_state.input_schema_evidence
    if evidence is None:
        return None
    projection = project_schema_fields(evidence.json_schema)
    field_text = (
        ", ".join(
            render_ai_builder_evidence_value(field) for field in projection.fields
        )
        if projection.fields
        else "top-level object"
    )
    if projection.truncated:
        field_text = (
            f"{field_text} "
            f"(showing {len(projection.fields)} of {projection.total_count})"
        )
    return "\n".join(
        [
            f"- source: {evidence.source}, {evidence.confidence} confidence",
            f"- declared top-level fields: {field_text}",
            "- This schema describes the Flow input boundary. Do not turn its "
            "primary payload fields into secondary input_fields.",
        ]
    )


def _example_output_style_evidence_block(
    planning_state: PlanningState,
) -> str | None:
    constraints = planning_state.example_output_constraints
    if constraints is None or not constraints.style_constraints:
        return None
    visible = constraints.style_constraints[:8]
    lines = [
        f"- {item.category}: {render_ai_builder_evidence_value(item.description)}"
        for item in visible
    ]
    omitted = len(constraints.style_constraints) - len(visible)
    if omitted:
        lines.append(f"- {omitted} additional style constraints omitted")
    lines.append(
        "- Use this evidence to guide structure and style; do not promise exact "
        "visual layout or copy accidental example content."
    )
    return "\n".join(lines)


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
    return "\n".join(sections)


__all__ = ["build_plan_proposal_system_prompt"]
