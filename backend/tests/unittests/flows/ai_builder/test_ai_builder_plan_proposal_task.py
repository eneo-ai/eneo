from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContext,
    AIBuilderAttachmentEvidence,
    AIBuilderAttachmentSchemaDiscovery,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_plan_proposal_task import (
    AuthoringAttachment,
    AuthoringBrief,
    build_authoring_brief,
    project_authoring_brief,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import FlowInputFieldIntent
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_requirements import (
    ConfirmedRuntimeInputRequirement,
    render_confirmed_runtime_input_requirements,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    build_schema_evidence,
)
from eneo.flows.ai_builder.ai_builder_tools import build_propose_flow_tool_schema
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    ConfirmedRuntimeMetadataField,
    ExampleOutputCitation,
    ExampleOutputConstraintEvidence,
    ExampleOutputSchemaInferenceOutcome,
    ExampleOutputSourceCoverage,
    ExampleOutputStyleConstraint,
    FileRoleEvidence,
    PlanningState,
    ResolvedSlot,
    SchemaResolution,
    SlotConfidence,
    SlotSource,
    StepTriple,
)


def _empty_catalog() -> AIBuilderResourceCatalog:
    return build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
    )


def _state_with_runtime_inputs(
    requirements: tuple[ConfirmedRuntimeInputRequirement, ...],
) -> PlanningState:
    state = PlanningState.empty()
    state.input_fields = [
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                variable_name=requirement.name,
                label=requirement.name,
                provenance="user_confirmed",
            ),
            purpose=requirement.purpose,
            structured_answer_message_id=f"answer-{index}",
        )
        for index, requirement in enumerate(requirements)
    ]
    return state


def test_project_authoring_brief_create_fixture_is_typed() -> None:
    file_id = UUID("00000000-0000-0000-0000-000000000701")
    state = PlanningState.empty()
    state.file_roles = [
        FileRoleEvidence(
            file_id=file_id,
            filename="source-sentinel.pdf",
            file_type="document",
            mimetype="application/pdf",
            has_readable_text=True,
            coverage="excerpt_truncated",
            role="reference_material",
            source="model",
            confidence="medium",
        )
    ]
    runtime_inputs = (
        ConfirmedRuntimeInputRequirement(
            name="runtime-sentinel",
            purpose="shape_result",
        ),
    )
    state.input_fields = _state_with_runtime_inputs(runtime_inputs).input_fields
    attachment_context = AIBuilderAttachmentContext(
        context="attachment-sentinel",
        evidence=(
            AIBuilderAttachmentEvidence(
                file_id=file_id,
                filename="source-sentinel.pdf",
                file_type="document",
                mimetype="application/pdf",
                has_readable_text=True,
                excerpt="attachment-sentinel",
                coverage="excerpt_truncated",
            ),
        ),
        included_file_ids=[file_id],
        total_chars=len("attachment-sentinel"),
        truncated=True,
        schema_discovery=AIBuilderAttachmentSchemaDiscovery(candidates=()),
    )

    actual = project_authoring_brief(
        planning_state=state,
        attachment_context=attachment_context,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
        requested_output_sections=RequestedOutputSections(
            sections=("heading-sentinel",),
            confidence="high",
        ),
    )

    assert actual == AuthoringBrief(
        runtime_inputs=runtime_inputs,
        attachments=(
            AuthoringAttachment(
                local_reference="file 1",
                filename="source-sentinel.pdf",
                role="reference_material",
                has_readable_text=True,
                coverage="excerpt_truncated",
                excerpt="attachment-sentinel",
            ),
        ),
        requested_output_sections=("heading-sentinel",),
    )


def test_project_authoring_brief_edit_fixture_is_typed() -> None:
    runtime_inputs = (
        ConfirmedRuntimeInputRequirement(
            name="create-only-sentinel",
            purpose="whole_flow",
        ),
    )

    actual = project_authoring_brief(
        planning_state=_state_with_runtime_inputs(runtime_inputs),
        attachment_context=None,
        flow_context="existing-flow-sentinel",
        is_edit_mode=True,
        resource_catalog=_empty_catalog(),
        plan_revision_context="selected-step-sentinel",
    )

    assert actual == AuthoringBrief(
        flow_context="existing-flow-sentinel",
        plan_revision_context="selected-step-sentinel",
        is_edit_mode=True,
    )


def test_create_prompt_projects_confirmed_runtime_input_identity_and_purpose() -> None:
    requirements = (
        ConfirmedRuntimeInputRequirement(name="audience", purpose="interpret_input"),
        ConfirmedRuntimeInputRequirement(name="case_id", purpose="shape_result"),
        ConfirmedRuntimeInputRequirement(name="policy", purpose="whole_flow"),
    )
    rendered = render_confirmed_runtime_input_requirements(requirements)

    create_prompt = build_authoring_brief(
        planning_state=_state_with_runtime_inputs(requirements),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )
    edit_prompt = build_authoring_brief(
        planning_state=_state_with_runtime_inputs(requirements),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=True,
        resource_catalog=_empty_catalog(),
    )

    assert "Runtime inputs:" in create_prompt
    assert rendered in create_prompt
    assert "server-owned runtime inputs" in create_prompt
    assert "Runtime inputs:" not in edit_prompt


def test_runtime_input_projection_preserves_long_and_delimited_names_exactly() -> None:
    common_prefix = "field_" + "x" * 90
    names = (f'{common_prefix}_a, "quoted"', f"{common_prefix}_b\nsecond line")
    requirements = tuple(
        ConfirmedRuntimeInputRequirement(name=name, purpose="shape_result")
        for name in names
    )
    rendered = render_confirmed_runtime_input_requirements(requirements)

    prompt = build_authoring_brief(
        planning_state=_state_with_runtime_inputs(requirements),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )
    schema = build_propose_flow_tool_schema(
        resource_catalog=_empty_catalog(),
    )
    schema_description = schema["function"]["parameters"]["properties"]["steps"][
        "items"
    ]["properties"]["output_fields"]["description"]

    assert rendered in prompt
    assert rendered not in schema_description
    assert json.dumps(schema, ensure_ascii=False).count(rendered) == 0
    assert [item["name"] for item in json.loads(rendered)] == list(names)


def _planning_state_with_architecture(
    *tuples: StepTriple,
    chosen_patterns: list[str] | None = None,
    required_capabilities: list[str] | None = None,
) -> PlanningState:
    return PlanningState.empty().model_copy(
        update={
            "architecture_commit": ArchitectureCommit(
                chosen_patterns=chosen_patterns or [],
                required_capabilities=required_capabilities or [],
                committed_at=datetime.now(timezone.utc),
                architecture_hash="a" * 64,
                tuples_chain=list(tuples),
            )
        }
    )


def _state_with_slot(
    slot_name: str,
    value: str,
    *,
    state: PlanningState | None = None,
    source: SlotSource = "structured_answer",
    confidence: SlotConfidence = "high",
) -> PlanningState:
    base_state = state or PlanningState.empty()
    return base_state.model_copy(
        update={
            "resolved_slots": {
                **base_state.resolved_slots,
                slot_name: ResolvedSlot(
                    name=slot_name,
                    value=value,
                    source=source,
                    confidence=confidence,
                ),
            }
        },
        deep=True,
    )


def test_plan_proposal_prompt_includes_readable_resources_without_execution_surface():
    state = _planning_state_with_architecture(
        StepTriple(
            input_type="text",
            output_type="json",
            output_mode="pass_through",
        ),
    )

    catalog = build_ai_builder_resource_catalog(
        available_models=[
            {
                "id": "model-fast",
                "ref": "model-fast",
                "name": "Fast model",
                "display_name": "Fast model",
                "provider": "test",
            },
        ],
        available_kbs=[
            {
                "id": "kb-policy",
                "ref": "kb-policy",
                "name": "Policy KB",
                "display_name": "Policy KB",
                "description": "Local policy reference material.",
            }
        ],
    )

    prompt = build_authoring_brief(
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=catalog,
    )

    assert "Available resources:" in prompt
    assert "ref=`model.fast-model`" in prompt
    assert "ref=`knowledge.policy-kb`" in prompt
    assert (
        "Exception: when the Available resources section gives portable resource slot refs"
        in prompt
    )
    assert "human-readable `flow_name`" not in prompt
    assert "input_schema" not in prompt
    assert "assistant_ref" not in prompt


def test_plan_proposal_prompt_keeps_previous_refs_backend_owned() -> None:
    state = _planning_state_with_architecture(
        StepTriple(
            input_type="text",
            output_type="text",
            output_mode="pass_through",
        )
    )

    create_prompt = build_authoring_brief(
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )
    edit_prompt = build_authoring_brief(
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=True,
        resource_catalog=_empty_catalog(),
    )

    assert "uses_previous_fields" not in create_prompt
    assert "uses_previous_outputs" not in create_prompt
    assert "1-based earlier propose_flow step numbers" not in create_prompt
    assert "Do not author field-level previous-step paths" in create_prompt
    assert "backend-owned refs" in create_prompt
    assert "raw input bindings" not in create_prompt
    assert "step refs" in create_prompt
    assert "uses_previous_fields" not in edit_prompt
    assert "uses_previous_outputs" not in edit_prompt


def test_plan_proposal_prompt_keeps_document_rendering_backend_owned() -> None:
    state = _planning_state_with_architecture(
        StepTriple(
            input_type="document",
            output_type="json",
            output_mode="pass_through",
        ),
        StepTriple(
            input_type="text",
            output_type="pdf",
            output_mode="render_verbatim",
        ),
    )

    prompt = build_authoring_brief(
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "final text step immediately before the renderer" in prompt
    assert "Do not add a separate final conversion" in prompt
    assert "the backend adds the fixed renderer" in prompt
    assert "- document -> json (pass_through)" not in prompt
    assert "- text -> pdf (render_verbatim)" not in prompt


def test_plan_proposal_prompt_renders_persisted_file_roles() -> None:
    state = PlanningState.empty()
    state.file_roles = [
        FileRoleEvidence(
            file_id="00000000-0000-0000-0000-000000000701",
            filename="avtalsmall.docx",
            file_type="document",
            mimetype=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml."
                "document"
            ),
            has_readable_text=True,
            coverage="fully_seen",
            role="template",
            source="heuristic",
            confidence="medium",
            evidence=[
                "content:template_marker",
                "content:template_placeholder:kundnamn",
                "content:template_placeholder:datum",
            ],
            candidate_roles=["template", "reference_material"],
        ),
        FileRoleEvidence(
            file_id="00000000-0000-0000-0000-000000000702",
            filename="lagstod.pdf",
            file_type="document",
            mimetype="application/pdf",
            has_readable_text=True,
            coverage="fully_seen",
            role="reference_material",
            source="heuristic",
            confidence="medium",
        ),
    ]

    prompt = build_authoring_brief(
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "Uploaded files:" in prompt
    assert "- file 1\n  filename: avtalsmall.docx\n  role: template" in prompt
    assert "has_readable_text: true\n  coverage: fully_seen" in prompt
    assert "- file 2\n  filename: lagstod.pdf\n  role: reference_material" in prompt
    assert "heuristic" not in prompt
    assert "confidence" not in prompt
    assert "candidates:" not in prompt


def test_plan_proposal_prompt_renders_output_schema_evidence_compactly() -> None:
    state = _state_with_slot("terminal_output", "structured_json")
    state.output_schema_evidence = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {
                "decision": {"type": "string"},
                "next_steps": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["decision"],
            "additionalProperties": False,
        },
        source="declared_schema",
        confidence="high",
        evidence=["message:msg_schema", "fenced_json_schema"],
    )

    prompt = build_authoring_brief(
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "Output schema evidence:" in prompt
    assert "decision, next_steps" in prompt
    assert "declared output contract fields" in prompt
    assert "Use output_fields consistent with this declared contract." in prompt
    assert "confidence" not in prompt
    assert "additionalProperties" not in prompt


def test_plan_proposal_prompt_describes_input_schema_without_directing_docx_output() -> (
    None
):
    state = _state_with_slot("terminal_output", "docx_document")
    state.input_schema_evidence = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {"case_id": {"type": "string"}},
        },
        source="declared_schema",
        source_file_ids=("00000000-0000-0000-0000-000000000001",),
        confidence="high",
        evidence=("file:00000000-0000-0000-0000-000000000001:json_schema",),
    )

    prompt = build_authoring_brief(
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "Input schema evidence:" in prompt
    assert "case_id" in prompt
    assert "Output schema evidence:" not in prompt
    assert "Use output_fields consistent with these user-declared fields." not in prompt
    assert "Do not reinterpret its primary payload fields" in prompt


def test_plan_proposal_prompt_treats_example_shape_and_style_as_guidance() -> None:
    file_id = UUID("00000000-0000-0000-0000-000000000713")
    base_state = _state_with_slot("terminal_output", "structured_json")
    state = PlanningState.model_validate(
        {
            **dict(base_state),
            "file_roles": [
                FileRoleEvidence(
                    file_id=file_id,
                    filename="expected.json",
                    file_type="text",
                    mimetype="application/json",
                    has_readable_text=True,
                    coverage="fully_seen",
                    role="example_output",
                    source="model",
                    confidence="medium",
                )
            ],
            "example_output_constraints": ExampleOutputConstraintEvidence(
                source_file_ids=[file_id],
                source_coverage=[
                    ExampleOutputSourceCoverage(
                        file_id=file_id,
                        coverage="fully_seen",
                    )
                ],
                headings=[
                    "Summary",
                    "Decision",
                    *(f"Section {index}" for index in range(1, 10)),
                ],
                style_constraints=[
                    ExampleOutputStyleConstraint(
                        category="tone",
                        description="Formal and concise",
                    )
                ],
                confidence="medium",
                citations=[
                    ExampleOutputCitation(
                        source_id=f"uploaded_file:{file_id}",
                        file_id=file_id,
                        quote='"decision": "approved"',
                    )
                ],
            ),
            "schema_resolution": SchemaResolution.from_evidence(
                input_evidence=None,
                output_evidence=build_schema_evidence(
                    json_schema={
                        "type": "object",
                        "properties": {
                            f"field_{index}": {"type": "string"} for index in range(12)
                        },
                    },
                    source="inferred_example",
                    source_file_ids=(file_id,),
                    confidence="medium",
                    evidence=(f"file:{file_id}:inferred_example_shape",),
                ),
            ),
            "example_output_schema_inference": ExampleOutputSchemaInferenceOutcome(
                status="inferred",
                source_file_ids=[file_id],
            ),
        }
    )

    prompt = build_authoring_brief(
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "example-hint top-level fields:" in prompt
    assert "showing 8 of 12" in prompt
    assert "not as an explicit or closed contract" in prompt
    assert "Example-output evidence:" in prompt
    assert "- heading: Summary" in prompt
    assert "- heading: Decision" in prompt
    assert "- heading: Section 9" in prompt
    assert "additional example headings omitted" not in prompt
    assert "- tone: Formal and concise" in prompt
    assert "it is not a required output topology" in prompt
    assert "Do not promise exact visual layout" in prompt
    assert "Requested output sections:" not in prompt


def test_plan_proposal_prompt_renders_template_placeholder_evidence() -> None:
    state = PlanningState.empty()
    state.output_schema_evidence = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {
                "kundnamn": {"type": "string"},
                "datum": {"type": "string"},
            },
        },
        source="template_placeholders",
        source_file_ids=("00000000-0000-0000-0000-000000000001",),
        confidence="high",
        evidence=["file:file_id:content:template_placeholder:kundnamn"],
    )

    prompt = build_authoring_brief(
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )
    edit_prompt = build_authoring_brief(
        planning_state=state,
        attachment_context=None,
        flow_context="Existing template flow",
        is_edit_mode=True,
        resource_catalog=_empty_catalog(),
    )

    assert "template placeholder fields: kundnamn, datum" in prompt
    for rendered_prompt in (prompt, edit_prompt):
        assert (
            "For DOCX template-fill mode, use at most 5 semantic preparation steps"
            in rendered_prompt
        )
    assert "Prefer source-derived output_fields" in prompt
    assert "the backend owns runtime values" in prompt
    assert "Use output_fields consistent with these user-declared fields." not in prompt


def test_plan_proposal_prompt_visibly_clips_long_evidence_and_field_names() -> None:
    long_placeholder = "field_" + "x" * 240
    state = PlanningState.empty()
    state.file_roles = [
        FileRoleEvidence(
            file_id="00000000-0000-0000-0000-000000000701",
            filename="template.docx",
            file_type="document",
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            has_readable_text=True,
            coverage="fully_seen",
            role="template",
            source="heuristic",
            confidence="medium",
            evidence=[
                f"content:template_placeholder:{long_placeholder}",
            ],
            candidate_roles=["template"],
        )
    ]
    state.output_schema_evidence = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {long_placeholder: {"type": "string"}},
        },
        source="template_placeholders",
        source_file_ids=("00000000-0000-0000-0000-000000000001",),
        confidence="high",
        evidence=[f"file:file_id:content:template_placeholder:{long_placeholder}"],
    )

    prompt = build_authoring_brief(
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert long_placeholder not in prompt
    assert "…" in prompt


def test_plan_proposal_prompt_keeps_create_mechanics_backend_owned():
    prompt = build_authoring_brief(
        planning_state=PlanningState.empty(),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "input_fields" not in prompt
    assert "uses_form_fields" not in prompt
    assert "source-reading JSON output_fields" in prompt
    assert "folded from the user's own wording" not in prompt
    assert "keep key names the user asked for" not in prompt
    assert "Do not leave user-named facts only in instructions" in prompt
    assert "generic facts/notes fields" in prompt
    assert "instead of introducing new source-derived facts only in prose" in prompt


def test_plan_proposal_prompt_omits_raw_slots_and_provenance() -> None:
    state = _state_with_slot(
        "runtime_metadata_fields",
        "no_extra_metadata",
        source="policy_default",
        confidence="medium",
        state=_state_with_slot(
            "terminal_output",
            "structured_json",
            source="structured_answer",
        ),
    )

    prompt = build_authoring_brief(
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "terminal_output" not in prompt
    assert "runtime_metadata_fields" not in prompt
    assert "policy default assumption" not in prompt


def test_plan_proposal_prompt_teaches_direct_text_transform_restraint():
    prompt = build_authoring_brief(
        planning_state=PlanningState.empty(),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "Direct text transformations" in prompt
    assert "default to one text step" in prompt
    assert "only when the user explicitly asks" in prompt


def test_plan_proposal_prompt_surfaces_requested_output_sections_once() -> None:
    prompt = build_authoring_brief(
        planning_state=PlanningState.empty(),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
        requested_output_sections=RequestedOutputSections(
            sections=(
                "Problem/nuläge",
                "Lösningsförslag/nyläge",
                "Resursåtgång",
                "Planerad tidplan",
            ),
            confidence="high",
        ),
    )

    assert "Requested output sections:" in prompt
    assert "- Problem/nuläge" in prompt
    assert "preserve those sections as semantic section-writing work" not in prompt
    assert prompt.count("Problem/nuläge") == 1


def test_plan_proposal_prompt_omits_section_rule_for_simple_transform() -> None:
    prompt = build_authoring_brief(
        planning_state=PlanningState.empty(),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
        requested_output_sections=RequestedOutputSections(),
    )

    assert "Direct text transformations" in prompt
    assert "Requested output sections:" not in prompt
    assert "section-writing work" not in prompt
    assert "DOCX/PDF delivery" not in prompt


def test_plan_proposal_prompt_guides_terminal_document_review_shape() -> None:
    prompt = build_authoring_brief(
        planning_state=_planning_state_with_architecture(
            StepTriple(
                input_type="document",
                output_type="docx",
                output_mode="pass_through",
            )
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "For DOCX/PDF delivery" in prompt
    assert "complete document body" in prompt
    assert "do not put review notes directly before DOCX/PDF rendering" in prompt


def test_plan_proposal_prompt_renders_action_followup_result_contract() -> None:
    state = _state_with_slot(
        "terminal_output",
        "pdf_document",
        state=_state_with_slot("post_processing_goal", "action_followup"),
    )

    prompt = build_authoring_brief(
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "Result contract:" in prompt
    assert "- post_processing_goal: action_followup" not in prompt
    assert "- Decisions" in prompt
    assert "- Owners" in prompt
    assert (
        "Mark missing owners, deadlines, and responsibilities as unspecified" in prompt
    )
    assert "final document step should render completed content" in prompt


def test_plan_proposal_prompt_renders_machine_readable_result_contract() -> None:
    prompt = build_authoring_brief(
        planning_state=_state_with_slot("terminal_output", "structured_json"),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "Result contract:" in prompt
    assert "- terminal_output: structured_json" not in prompt
    assert "Use the requested schema or fields as the output contract" in prompt
    assert "Use null or unspecified placeholders for missing source values" in prompt
    assert "Brief summary" not in prompt


def test_plan_proposal_prompt_scopes_audio_transcription_to_backend():
    prompt = build_authoring_brief(
        planning_state=_planning_state_with_architecture(
            StepTriple(
                input_type="audio",
                output_type="text",
                output_mode="pass_through",
            )
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "committed audio input" in prompt
    assert "backend inserts the first transcription/upload step" in prompt
    assert "after transcription" in prompt
    assert "Transcript review is compiler-owned" in prompt
    assert "include the leading transcription step with review_mode" not in prompt
    assert "Human review checkpoints are compiler-owned in create mode" in prompt
    assert "Do not set review_mode" in prompt
    assert "separate AI step" in prompt


def test_pure_audio_prompt_requests_one_mechanics_free_transcription_step() -> None:
    prompt = build_authoring_brief(
        planning_state=_planning_state_with_architecture(
            StepTriple(
                input_type="audio",
                output_type="text",
                output_mode="transcribe_only",
            ),
            chosen_patterns=["audio_transcription"],
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        is_pure_audio_transcription=True,
        resource_catalog=_empty_catalog(),
    )

    assert "exactly one semantic transcription step" in prompt
    assert "only `name` and `instructions`" in prompt
    assert "backend owns upload and transcription mechanics" in prompt
    assert "start propose_flow steps with the analysis" not in prompt
