"""Task-specific prompt for final AI Builder plan proposal.

This prompt is intentionally not the planner union contract. The server
has already selected the phase; the model only drafts semantic flow
content through the create/edit tool schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eneo.flows.ai_builder.ai_builder_action_policy import (
    named_result_projection,
)
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    render_ai_builder_evidence_value,
)
from eneo.flows.ai_builder.ai_builder_event_models import RequirementsSummaryPayload
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ProposalObligationProjection,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    user_relevant_requirement_notes,
    user_relevant_requirement_text,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    AIBuilderResourceReferenceMaterial,
    build_ai_builder_resource_reference_material,
    render_resource_reference_block,
)
from eneo.flows.ai_builder.ai_builder_result_contract import (
    ResultObligation,
    derive_result_contract,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_requirements import (
    ConfirmedRuntimeInputRequirement,
    render_confirmed_runtime_input_requirements,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    project_schema_fields,
)
from eneo.flows.ai_builder.ai_builder_template_attachment_contract import (
    MAX_TEMPLATE_PREPARATION_STAGES,
)
from eneo.flows.ai_builder.ai_builder_tool_names import (
    DECLINE_FLOW_CHANGE_TOOL_NAME,
    PROPOSE_FLOW_TOOL_NAME,
)
from eneo.flows.ai_builder.planning_state import (
    AttachmentCoverage,
    ExampleOutputStyleCategory,
    FileRole,
    PlanningState,
    SchemaEvidence,
)


@dataclass(frozen=True, slots=True)
class AuthoringKeyDecision:
    topic: str
    decision: str


@dataclass(frozen=True, slots=True)
class AuthoringRequirementFacts:
    summary: str | None = None
    input_description: str | None = None
    output_description: str | None = None
    key_decisions: tuple[AuthoringKeyDecision, ...] = ()
    named_content_fields: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthoringFileRole:
    filename: str
    role: FileRole
    has_readable_text: bool
    coverage: AttachmentCoverage


SchemaAuthority = Literal[
    "declared_input_contract",
    "declared_output_contract",
    "example_hint",
    "template_placeholders",
]


@dataclass(frozen=True, slots=True)
class AuthoringSchema:
    authority: SchemaAuthority
    fields: tuple[str, ...]
    total_count: int
    fields_truncated: bool = False
    source_total_count: int | None = None
    source_truncated: bool = False


@dataclass(frozen=True, slots=True)
class AuthoringExampleStyle:
    category: ExampleOutputStyleCategory
    description: str


@dataclass(frozen=True, slots=True)
class AuthoringExampleGuidance:
    headings: tuple[str, ...] = ()
    style_constraints: tuple[AuthoringExampleStyle, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthoringResultContract:
    secondary_obligations: tuple[ResultObligation, ...] = ()
    required_sections: tuple[str, ...] = ()
    result_policies: tuple[str, ...] = ()
    required_output_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthoringBrief:
    requirements: AuthoringRequirementFacts | None = None
    runtime_inputs: tuple[ConfirmedRuntimeInputRequirement, ...] = ()
    file_roles: tuple[AuthoringFileRole, ...] = ()
    input_schema: AuthoringSchema | None = None
    output_schema: AuthoringSchema | None = None
    example_output: AuthoringExampleGuidance | None = None
    result_contract: AuthoringResultContract | None = None
    named_results: ProposalObligationProjection | None = None
    requested_output_sections: tuple[str, ...] = ()
    resources: AIBuilderResourceReferenceMaterial | None = None
    flow_context: str | None = None
    plan_revision_context: str | None = None
    attachment_context: str | None = None
    is_edit_mode: bool = False
    is_pure_audio_transcription: bool = False
    has_committed_audio_input: bool = False
    has_terminal_document: bool = False
    can_decline: bool = False


def project_authoring_brief(
    *,
    planning_state: PlanningState,
    confirmed_requirements: RequirementsSummaryPayload | None,
    attachment_context: str | None,
    flow_context: str | None,
    is_edit_mode: bool,
    resource_catalog: AIBuilderResourceCatalog,
    is_pure_audio_transcription: bool = False,
    plan_revision_context: str | None = None,
    requested_output_sections: RequestedOutputSections | None = None,
    confirmed_runtime_inputs: tuple[ConfirmedRuntimeInputRequirement, ...] = (),
    can_decline: bool = False,
) -> AuthoringBrief:
    resource_material = build_ai_builder_resource_reference_material(
        catalog=resource_catalog,
    )
    resources = (
        resource_material
        if resource_material.models or resource_material.knowledge_bases
        else None
    )
    commit = planning_state.architecture_commit
    result_contract = derive_result_contract(planning_state)
    constraints = planning_state.example_output_constraints
    return AuthoringBrief(
        requirements=_project_requirement_facts(confirmed_requirements),
        runtime_inputs=(confirmed_runtime_inputs if not is_edit_mode else ()),
        file_roles=tuple(
            AuthoringFileRole(
                filename=item.filename,
                role=item.role,
                has_readable_text=item.has_readable_text,
                coverage=item.coverage,
            )
            for item in planning_state.file_roles
        ),
        input_schema=_project_authoring_schema(
            planning_state.input_schema_evidence,
            direction="input",
        ),
        output_schema=_project_authoring_schema(
            planning_state.output_schema_evidence,
            direction="output",
            terminal_output=planning_state.commit_grade_slot_value("terminal_output"),
        ),
        example_output=(
            AuthoringExampleGuidance(
                headings=tuple(constraints.headings),
                style_constraints=tuple(
                    AuthoringExampleStyle(
                        category=item.category,
                        description=item.description,
                    )
                    for item in constraints.style_constraints
                ),
            )
            if constraints is not None
            else None
        ),
        result_contract=(
            AuthoringResultContract(
                secondary_obligations=result_contract.secondary_obligations,
                required_sections=result_contract.required_sections,
                result_policies=result_contract.result_policies,
                required_output_fields=tuple(
                    requirement.canonical_name
                    for requirement in result_contract.required_output_fields
                ),
            )
            if result_contract is not None
            else None
        ),
        named_results=named_result_projection(
            planning_state,
            is_edit_mode=is_edit_mode,
        ),
        requested_output_sections=(
            requested_output_sections.sections
            if requested_output_sections is not None
            and requested_output_sections.high_confidence
            else ()
        ),
        resources=resources,
        flow_context=flow_context,
        plan_revision_context=plan_revision_context,
        attachment_context=attachment_context,
        is_edit_mode=is_edit_mode,
        is_pure_audio_transcription=is_pure_audio_transcription,
        has_committed_audio_input=(
            commit is not None
            and any(triple.input_type == "audio" for triple in commit.tuples_chain)
        ),
        has_terminal_document=(
            commit is not None
            and any(
                triple.output_type in {"docx", "pdf"} for triple in commit.tuples_chain
            )
        ),
        can_decline=can_decline,
    )


def _project_requirement_facts(
    summary: RequirementsSummaryPayload | None,
) -> AuthoringRequirementFacts | None:
    if summary is None:
        return None
    facts = AuthoringRequirementFacts(
        summary=user_relevant_requirement_text(summary.summary),
        input_description=user_relevant_requirement_text(summary.input_description),
        output_description=user_relevant_requirement_text(summary.output_description),
        key_decisions=tuple(
            AuthoringKeyDecision(topic=item.topic, decision=item.decision)
            for item in summary.key_decisions
        ),
        named_content_fields=tuple(item.label for item in summary.named_content_fields),
        assumptions=user_relevant_requirement_notes(summary.assumptions),
    )
    return (
        facts
        if any(
            (
                facts.summary,
                facts.input_description,
                facts.output_description,
                facts.key_decisions,
                facts.named_content_fields,
                facts.assumptions,
            )
        )
        else None
    )


def _project_authoring_schema(
    evidence: SchemaEvidence | None,
    *,
    direction: Literal["input", "output"],
    terminal_output: str | None = None,
) -> AuthoringSchema | None:
    if evidence is None:
        return None
    if (
        direction == "output"
        and evidence.source != "template_placeholders"
        and (terminal_output != "structured_json")
    ):
        return None
    projection = project_schema_fields(evidence.json_schema)
    authority: SchemaAuthority
    if evidence.source == "template_placeholders":
        authority = "template_placeholders"
    elif direction == "input":
        authority = "declared_input_contract"
    elif evidence.source == "inferred_example":
        authority = "example_hint"
    else:
        authority = "declared_output_contract"
    return AuthoringSchema(
        authority=authority,
        fields=projection.fields,
        total_count=projection.total_count,
        fields_truncated=projection.truncated,
        source_total_count=evidence.total_count,
        source_truncated=evidence.truncated,
    )


def build_authoring_brief(
    *,
    planning_state: PlanningState,
    confirmed_requirements: RequirementsSummaryPayload | None,
    attachment_context: str | None,
    flow_context: str | None,
    is_edit_mode: bool,
    is_pure_audio_transcription: bool = False,
    resource_catalog: AIBuilderResourceCatalog,
    plan_revision_context: str | None = None,
    requested_output_sections: RequestedOutputSections | None = None,
    confirmed_runtime_inputs: tuple[ConfirmedRuntimeInputRequirement, ...] = (),
    can_decline: bool = False,
) -> str:
    brief = project_authoring_brief(
        planning_state=planning_state,
        confirmed_requirements=confirmed_requirements,
        attachment_context=attachment_context,
        flow_context=flow_context,
        is_edit_mode=is_edit_mode,
        is_pure_audio_transcription=is_pure_audio_transcription,
        resource_catalog=resource_catalog,
        plan_revision_context=plan_revision_context,
        requested_output_sections=requested_output_sections,
        confirmed_runtime_inputs=confirmed_runtime_inputs,
        can_decline=can_decline,
    )
    return _render_authoring_brief(brief)


def _render_authoring_brief(brief: AuthoringBrief) -> str:
    submission_tool = PROPOSE_FLOW_TOOL_NAME
    audio_create_rule = (
        "- For this pure audio transcription flow, propose exactly one semantic "
        "transcription step with only `name` and `instructions`; the backend owns "
        "upload and transcription mechanics."
        if brief.is_pure_audio_transcription
        else "- For committed audio input, the backend inserts the first "
        "transcription/upload step; start propose_flow steps with the analysis, "
        "structuring, or synthesis work after transcription. Transcript review is "
        "compiler-owned and stays on that backend-inserted step."
    )
    create_mode_rules = (
        [
            "- In create mode, describe semantic flow intent in propose_flow; do not choose Flow mechanics.",
            *(
                [audio_create_rule]
                if brief.has_committed_audio_input or brief.is_pure_audio_transcription
                else []
            ),
            "- Human review checkpoints are compiler-owned in create mode: the backend places confirmed review intents on their producing steps. Do not set review_mode, and do not model human review as a separate AI step or as instruction prose.",
            "- Do not author field-level previous-step paths or text-output refs in create mode; the backend owns those underlag channels from the proposed step outputs and committed architecture.",
            "- The backend compiles step topology, backend-owned refs, underlag/input_bindings, runtime input, step refs, output modes, and document delivery.",
        ]
        if not brief.is_edit_mode
        else []
    )
    terminal_document_rule = _terminal_document_design_rule(brief)
    obligation_projection = brief.named_results
    projected_names_rule = (
        (
            "- The result must contain these exact named results: "
            + ", ".join(
                (
                    f"`{key.name}` (placement not specified)"
                    if key.placement.kind == "unplaced"
                    else f"`{obligation_projection.render_key_location(key)}`"
                    + (f" (type {key.declared_shape})" if key.declared_shape else "")
                )
                for key in obligation_projection.keys
            )
            + ". Before submitting, check the FINAL step's output_fields "
            "against this list: (1) every exact result appears at its listed "
            "location in the final step — not in an earlier step or through "
            "an extra wrapper; (2) every placement-not-specified result appears "
            "exactly once anywhere in the final step; (3) spelling is exactly "
            "as written above; (4) each result is declared exactly once at its "
            "location, with an accurate description; (5) named results of "
            "type object or array are declared with nullable false. Missing, "
            "renamed, duplicated, ambiguously placed or wrongly typed results "
            "are rejected."
        )
        if obligation_projection is not None and obligation_projection.keys
        else None
    )
    result_contract_block = _render_result_contract(brief.result_contract)
    lines = [
        "You are drafting an Eneo Flow plan.",
        "",
        "The backend has already completed discovery and selected this turn's phase.",
        (
            f"Call exactly one `{submission_tool}` tool, or one "
            f"`{DECLINE_FLOW_CHANGE_TOOL_NAME}` tool when the request is only "
            "for a listed decline reason. Do not ask a question, do not confirm "
            "requirements, and do not return prose only."
            if brief.can_decline
            else f"Call exactly one `{submission_tool}` tool. Do not ask a question, do not confirm requirements, and do not return prose only."
        ),
        "",
        "Design rules:",
        "- Use as many steps as the requested workflow needs, up to the tool schema "
        "limit. For DOCX template-fill mode, use at most "
        f"{MAX_TEMPLATE_PREPARATION_STAGES} semantic preparation steps before the "
        "backend-owned fill step.",
        "- Direct text transformations such as translation, rewriting, correction, shortening, or summarizing a supplied snippet default to one text step; add JSON, review, or extra steps only when the user explicitly asks for them.",
        "- Prefer a clear multi-step flow for complex work instead of one overloaded step.",
        "- For source-material reports, include every final-report fact or per-item short summary that must come from the source in the source-reading JSON output_fields. Do not leave user-named facts only in instructions or hide them inside generic facts/notes fields; later text or document steps should consume those fields instead of introducing new source-derived facts only in prose.",
        *([projected_names_rule] if projected_names_rule is not None else []),
        *([terminal_document_rule] if terminal_document_rule is not None else []),
        "- Describe each step's semantic work; the backend derives runtime input and final output mechanics from the committed architecture.",
        "- Exception: when the Available resources section gives portable resource slot refs, use those refs only in their dedicated fields (`model_ref`, `knowledge_refs`).",
        "- The backend will compile, validate, and persist the plan for user approval.",
        *create_mode_rules,
        "",
        "Requirements:",
        _render_requirement_facts(brief.requirements),
    ]
    if brief.runtime_inputs:
        lines.extend(
            [
                "",
                "Runtime inputs:",
                render_confirmed_runtime_input_requirements(brief.runtime_inputs),
                "- Keep these exact identities as server-owned runtime inputs; "
                "do not repeat an identity as a source output field. Preserve "
                "each listed purpose when designing semantic work.",
            ]
        )
    file_roles_block = _file_roles_block(brief.file_roles)
    if file_roles_block is not None:
        lines.extend(["", "Uploaded file roles:", file_roles_block])
    input_schema_block = _schema_evidence_block(brief.input_schema)
    if input_schema_block is not None:
        lines.extend(["", "Input schema evidence:", input_schema_block])
    output_schema_block = _schema_evidence_block(brief.output_schema)
    if output_schema_block is not None:
        lines.extend(["", "Output schema evidence:", output_schema_block])
    example_evidence_block = _example_output_evidence_block(brief.example_output)
    if example_evidence_block is not None:
        lines.extend(["", "Example-output evidence:", example_evidence_block])
    if result_contract_block is not None:
        lines.extend(["", "Result contract:", result_contract_block])
    section_block = _requested_output_sections_block(brief.requested_output_sections)
    if section_block is not None:
        lines.extend(["", "Requested output sections:", section_block])
    if brief.flow_context:
        lines.extend(["", "Existing flow context:", brief.flow_context])
    resource_context = (
        _resource_context_block(brief.resources) if brief.resources is not None else ""
    )
    if resource_context:
        lines.extend(["", "Available resources:", resource_context])
    if brief.plan_revision_context:
        lines.extend(["", brief.plan_revision_context])
    if brief.attachment_context:
        lines.extend(["", "Attachment context:", brief.attachment_context])
    return "\n".join(lines)


def _terminal_document_design_rule(brief: AuthoringBrief) -> str | None:
    if not brief.has_terminal_document:
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
    requested_output_sections: tuple[str, ...],
) -> str | None:
    if not requested_output_sections:
        return None
    return "\n".join(f"- {section}" for section in requested_output_sections)


def _render_requirement_facts(facts: AuthoringRequirementFacts | None) -> str:
    if facts is None:
        return "- none"
    lines: list[str] = []
    for key, value in (
        ("summary", facts.summary),
        ("input_description", facts.input_description),
        ("output_description", facts.output_description),
    ):
        if value is not None:
            lines.append(f"- {key}: {value}")
    if facts.key_decisions:
        lines.append("- key_decisions:")
        lines.extend(
            f"  - {decision.topic}: {decision.decision}"
            for decision in facts.key_decisions
        )
    if facts.named_content_fields:
        lines.append("- named_content_fields:")
        lines.extend(f"  - {label}" for label in facts.named_content_fields)
    if facts.assumptions:
        lines.append("- assumptions:")
        lines.extend(f"  - {assumption}" for assumption in facts.assumptions)
    return "\n".join(lines) if lines else "- none"


def _file_roles_block(file_roles: tuple[AuthoringFileRole, ...]) -> str | None:
    if not file_roles:
        return None
    return "\n".join(
        f"- {render_ai_builder_evidence_value(item.filename)}: {item.role} "
        f"(has_readable_text: {str(item.has_readable_text).lower()}; "
        f"coverage: {item.coverage})"
        for item in file_roles
    )


def _schema_evidence_block(schema: AuthoringSchema | None) -> str | None:
    if schema is None:
        return None
    field_text = (
        ", ".join(render_ai_builder_evidence_value(field) for field in schema.fields)
        if schema.fields
        else "top-level object"
    )
    if schema.fields_truncated:
        field_text = (
            f"{field_text} (showing {len(schema.fields)} of {schema.total_count})"
        )
    if schema.authority == "template_placeholders":
        coverage_line = (
            f"- placeholder coverage: {len(schema.fields)} of "
            f"{schema.source_total_count} unique "
            "fields retained (truncated)"
            if schema.source_truncated and schema.source_total_count is not None
            else None
        )
        return "\n".join(
            [
                f"- template placeholder fields: {field_text}",
                *([coverage_line] if coverage_line is not None else []),
                "- Prefer source-derived output_fields for placeholders that can be "
                "extracted from uploaded documents; the backend owns runtime values "
                "that the user must provide.",
            ]
        )
    if schema.authority == "example_hint":
        return "\n".join(
            [
                f"- example-hint top-level fields: {field_text}",
                "- Treat this as an open structural hint from a selected example, "
                "not as an explicit or closed contract. Do not invent required "
                "fields or validation constraints.",
            ]
        )
    boundary = "input" if schema.authority == "declared_input_contract" else "output"
    return "\n".join(
        [
            f"- declared {boundary} contract fields: {field_text}",
            *(
                [
                    "- This schema describes the Flow input boundary. Do not "
                    "reinterpret its primary payload fields as independent runtime "
                    "values."
                ]
                if boundary == "input"
                else ["- Use output_fields consistent with this declared contract."]
            ),
        ]
    )


def _render_result_contract(contract: AuthoringResultContract | None) -> str | None:
    if contract is None:
        return None
    lines: list[str] = []
    if contract.secondary_obligations:
        lines.append("- secondary_obligations:")
        lines.extend(
            f"  - {obligation}" for obligation in contract.secondary_obligations
        )
    if contract.required_sections:
        lines.append("- required_sections:")
        lines.extend(f"  - {section}" for section in contract.required_sections)
    if contract.required_output_fields:
        lines.append("- required_output_fields:")
        lines.extend(f"  - {name}" for name in contract.required_output_fields)
        lines.append(
            "- A human-readable outcome for this goal needs a structured extraction "
            "step declaring these fields, feeding the final writing step."
        )
    if contract.result_policies:
        lines.append("- result_policies:")
        lines.extend(f"  - {policy}" for policy in contract.result_policies)
    return "\n".join(lines) if lines else None


def _example_output_evidence_block(
    constraints: AuthoringExampleGuidance | None,
) -> str | None:
    if constraints is None:
        return None
    lines = [
        f"- heading: {render_ai_builder_evidence_value(heading)}"
        for heading in constraints.headings
    ]
    lines.extend(
        f"- {item.category}: {render_ai_builder_evidence_value(item.description)}"
        for item in constraints.style_constraints
    )
    if not lines:
        return None
    lines.append(
        "- This describes how one earlier document looked. Use it to guide "
        "structure and style; it is not a required output topology. Do not "
        "promise exact visual layout or copy accidental example content."
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


__all__ = [
    "AuthoringBrief",
    "AuthoringExampleGuidance",
    "AuthoringExampleStyle",
    "AuthoringFileRole",
    "AuthoringKeyDecision",
    "AuthoringRequirementFacts",
    "AuthoringResultContract",
    "AuthoringSchema",
    "build_authoring_brief",
    "project_authoring_brief",
]
