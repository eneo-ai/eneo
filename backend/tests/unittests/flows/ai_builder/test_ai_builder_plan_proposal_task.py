from __future__ import annotations

from datetime import datetime, timezone

from eneo.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_plan_proposal_task import (
    build_plan_proposal_system_prompt,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    FileRoleEvidence,
    OutputSchemaEvidence,
    PlanningState,
    ResolvedSlot,
    SlotConfidence,
    SlotSource,
    StepTriple,
)


def _requirements(**overrides: object) -> RequirementsSummaryPayload:
    payload = {
        "summary": "Test",
        "key_decisions": [],
        "input_description": "Test",
        "output_description": "Test",
    }
    payload.update(overrides)
    return RequirementsSummaryPayload.model_validate(payload)


def _empty_catalog() -> AIBuilderResourceCatalog:
    return build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[],
    )


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
        chosen_patterns=["mcp_lookup"],
        required_capabilities=["mcp_policy"],
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
        available_mcps=[
            {
                "ref": "case-server",
                "display_name": "Case system",
                "description": "Reads current case data.",
                "tools": [
                    {
                        "ref": "case-lookup",
                        "display_name": "Lookup case",
                        "description": "Fetches a case by ID.",
                        "input_schema": {"type": "object"},
                    }
                ],
            }
        ],
    )

    prompt = build_plan_proposal_system_prompt(
        planning_state=state,
        confirmed_requirements=_requirements(
            summary="Look up a case and summarize it."
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=catalog,
    )

    assert "Available resources:" in prompt
    assert "ref=`model.fast-model`" in prompt
    assert "ref=`knowledge.policy-kb`" in prompt
    assert "server_ref=`mcp_server.case-system`" in prompt
    assert "tool_ref=`mcp_tool.case-system-lookup-case`" in prompt
    assert (
        "Exception: when the Available resources section gives portable resource slot refs"
        in prompt
    )
    assert "human-readable `flow_name`" in prompt
    assert "mcp_lookup" not in prompt
    assert "mcp_policy" not in prompt
    assert "must not execute MCP tools" in prompt
    assert "input_schema" not in prompt
    assert "assistant_ref" not in prompt


def test_plan_proposal_prompt_allows_create_only_declared_previous_refs() -> None:
    state = _planning_state_with_architecture(
        StepTriple(
            input_type="text",
            output_type="text",
            output_mode="pass_through",
        )
    )

    create_prompt = build_plan_proposal_system_prompt(
        planning_state=state,
        confirmed_requirements=_requirements(),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )
    edit_prompt = build_plan_proposal_system_prompt(
        planning_state=state,
        confirmed_requirements=_requirements(),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=True,
        resource_catalog=_empty_catalog(),
    )

    assert "uses_previous_fields" in create_prompt
    assert "uses_previous_outputs" in create_prompt
    assert "1-based earlier propose_flow step numbers" in create_prompt
    assert "Do not author field-level previous-step paths" not in create_prompt
    assert "backend-owned refs" not in create_prompt
    assert "raw input bindings" in create_prompt
    assert "step refs" in create_prompt
    assert "uses_previous_fields" not in edit_prompt
    assert "uses_previous_outputs" not in edit_prompt


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
            role="template",
            source="heuristic",
            confidence="medium",
            candidate_roles=["template", "reference_material"],
        ),
        FileRoleEvidence(
            file_id="00000000-0000-0000-0000-000000000702",
            filename="lagstod.pdf",
            file_type="document",
            mimetype="application/pdf",
            role="reference_material",
            source="heuristic",
            confidence="medium",
        ),
    ]

    prompt = build_plan_proposal_system_prompt(
        planning_state=state,
        confirmed_requirements=_requirements(summary="Use the uploaded files."),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "Uploaded file roles:" in prompt
    assert (
        "- avtalsmall.docx: template (heuristic, medium confidence; "
        "candidates: template, reference_material)"
    ) in prompt
    assert "- lagstod.pdf: reference_material (heuristic, medium confidence)" in prompt


def test_plan_proposal_prompt_renders_output_schema_evidence_compactly() -> None:
    state = PlanningState.empty()
    state.output_schema_evidence = OutputSchemaEvidence(
        json_schema={
            "type": "object",
            "properties": {
                "decision": {"type": "string"},
                "next_steps": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["decision"],
            "additionalProperties": False,
        },
        source="freeform_text",
        confidence="high",
        evidence=["message:msg_schema", "fenced_json_schema"],
    )

    prompt = build_plan_proposal_system_prompt(
        planning_state=state,
        confirmed_requirements=_requirements(summary="Return decisions as JSON."),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "Output schema evidence:" in prompt
    assert "decision, next_steps" in prompt
    assert "freeform_text, high confidence" in prompt
    assert "Use output_fields consistent with these user-declared fields." in prompt
    assert "additionalProperties" not in prompt


def test_plan_proposal_prompt_honors_continue_without_mcp_decision():
    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Answer without external integrations."
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
        mcp_selection_values={"without_mcp"},
    )

    assert "MCP selection decision:" in prompt
    assert "continue without MCP tools" in prompt
    assert "`mcp_server_refs` or `mcp_tool_refs`" in prompt
    assert (
        "do not claim that the flow fetches live or external data by itself" in prompt
    )
    assert "collect it as runtime input" in prompt


def test_plan_proposal_prompt_identifies_runtime_metadata_as_compiler_policy():
    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Skapa ett svenskt ljud till DOCX-flöde."
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "input_fields" in prompt
    assert "Runtime metadata policy" in prompt
    assert "compiler" in prompt
    assert "do not invent input_fields from defaults" in prompt
    assert "explicit no-extra-fields decision" in prompt


def test_plan_proposal_prompt_marks_resolved_slot_decision_strength() -> None:
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

    prompt = build_plan_proposal_system_prompt(
        planning_state=state,
        confirmed_requirements=_requirements(
            summary="Ta input JSON och returnera bara JSON enligt output-schemat.",
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "- terminal_output: structured_json (confirmed)" in prompt
    assert (
        "- runtime_metadata_fields: no_extra_metadata (policy default assumption)"
    ) in prompt


def test_plan_proposal_prompt_teaches_direct_text_transform_restraint():
    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Översätt en kort mening till engelska.",
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "Direct text transformations" in prompt
    assert "default to one text step" in prompt
    assert "only when the user explicitly asks" in prompt


def test_plan_proposal_prompt_surfaces_requested_output_sections_once() -> None:
    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Skapa ett beslutsunderlag från ett Word-dokument.",
        ),
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
    assert "preserve those sections as semantic section-writing work" in prompt
    assert prompt.count("Problem/nuläge") == 1


def test_plan_proposal_prompt_omits_section_rule_for_simple_transform() -> None:
    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Översätt en kort mening till engelska.",
        ),
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
    prompt = build_plan_proposal_system_prompt(
        planning_state=_planning_state_with_architecture(
            StepTriple(
                input_type="document",
                output_type="docx",
                output_mode="pass_through",
            )
        ),
        confirmed_requirements=_requirements(
            summary="Skapa ett beslutsunderlag från ett Word-dokument.",
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

    prompt = build_plan_proposal_system_prompt(
        planning_state=state,
        confirmed_requirements=_requirements(
            summary="Transkribera mötet och plocka ut beslut och nästa steg.",
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "Result contract:" in prompt
    assert "- post_processing_goal: action_followup" in prompt
    assert "- Decisions" in prompt
    assert "- Owners" in prompt
    assert (
        "Mark missing owners, deadlines, and responsibilities as unspecified" in prompt
    )
    assert "final document step should render completed content" in prompt


def test_plan_proposal_prompt_renders_machine_readable_result_contract() -> None:
    prompt = build_plan_proposal_system_prompt(
        planning_state=_state_with_slot("terminal_output", "structured_json"),
        confirmed_requirements=_requirements(
            summary="Ta input JSON och returnera bara JSON enligt output-schemat.",
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "Result contract:" in prompt
    assert "- terminal_output: structured_json" in prompt
    assert "Use the requested schema or fields as the output contract" in prompt
    assert "Use null or unspecified placeholders for missing source values" in prompt
    assert "Brief summary" not in prompt


def test_plan_proposal_prompt_omits_confirmed_requirement_boilerplate():
    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Översätt en kort svensk text till engelska.",
            input_description="Primär indata vid körning behöver granskas.",
            output_description="Huvudsakligt slutresultat behöver granskas.",
            assumptions=[
                "Planen ska följa kraven och underlaget i konversationen.",
                "Användaren ska kunna granska och ändra planen innan den tillämpas.",
                "Inga extra fält.",
            ],
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "- summary: Översätt en kort svensk text till engelska." in prompt
    assert "behöver granskas" not in prompt
    assert "Användaren ska kunna granska" not in prompt
    assert "Inga extra fält." in prompt


def test_plan_proposal_prompt_does_not_render_requirements_version() -> None:
    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            requirements_version="do-not-render",
            summary="Sammanfatta kunddialogen.",
            key_decisions=[{"topic": "Indata", "decision": "Ljudfil vid körning."}],
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "do-not-render" not in prompt
    assert "- Indata: Ljudfil vid körning." in prompt


def test_plan_proposal_prompt_scopes_audio_transcription_to_backend():
    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Skapa ett svenskt ljud till DOCX-flöde."
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_empty_catalog(),
    )

    assert "committed audio input" in prompt
    assert "backend inserts the first transcription/upload step" in prompt
    assert "after transcription" in prompt
    assert "include the leading transcription step with review_mode" in prompt
    assert "set that step's review_mode" in prompt
    assert "separate AI step" in prompt


def test_plan_proposal_prompt_honors_selected_mcp_server():
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "ref": "time-server",
                "display_name": "Time MCP",
                "description": "Kan hämta tiden.",
                "tools": [
                    {
                        "ref": "current-time",
                        "display_name": "get_current_time",
                        "description": "Get current time in a specific timezone.",
                    }
                ],
            }
        ],
    )

    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Use an enabled MCP for live data."
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=catalog,
        mcp_selection_values={"use_mcp_server:mcp_server.time-mcp"},
    )

    assert "The user allowed these MCP server refs: `mcp_server.time-mcp`." in prompt
    assert "Prefer specific `mcp_tool_refs`" in prompt
    assert "Selected MCP tools available for step-level use" in prompt
    assert "tool_ref=`mcp_tool.time-mcp-get-current-time`" in prompt
    assert "server_ref=`mcp_server.time-mcp`" in prompt


def test_plan_proposal_prompt_drops_selected_mcp_ref_that_is_not_in_catalog():
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "ref": "time-server",
                "display_name": "Time MCP",
                "tools": [{"ref": "current-time", "display_name": "get_current_time"}],
            }
        ],
    )

    prompt = build_plan_proposal_system_prompt(
        planning_state=PlanningState.empty(),
        confirmed_requirements=_requirements(
            summary="Use an enabled MCP for live data."
        ),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=catalog,
        mcp_selection_values={"use_mcp_server:missing-server"},
    )

    assert "Available resources:" in prompt
    assert "server_ref=`mcp_server.time-mcp`" in prompt
    assert "MCP selection decision:" not in prompt
    assert "missing-server" not in prompt
