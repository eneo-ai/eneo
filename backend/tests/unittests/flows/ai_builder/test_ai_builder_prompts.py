"""Tests for AI Builder system prompt construction and context management."""

from __future__ import annotations

from uuid import uuid4

from intric.flows.ai_builder.ai_builder_action_policy import PlannerActionPolicy
from intric.flows.ai_builder.ai_builder_create_outline import OUTLINE_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_capability_profile,
)
from intric.flows.ai_builder.ai_builder_edit_scope import (
    EditScopeResolution,
)
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    ConversationMessage,
    FlowDraftSpecCore,
    FormFieldSpec,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_prompts import (
    build_available_kbs_context,
    build_available_models_context,
    build_clarification_hints,
    build_flow_context,
    build_plan_summary,
    build_step_ref_mapping,
    build_system_prompt,
    trim_conversation_for_context,
)
from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)
from intric.flows.flow import Flow, FlowStep

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_flow(
    *,
    name: str = "Test flow",
    description: str | None = "A test flow",
    steps: list[FlowStep] | None = None,
    published_version: int | None = None,
    draft_revision: int = 0,
    metadata_json: dict | None = None,
) -> Flow:
    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name=name,
        description=description,
        draft_revision=draft_revision,
        published_version=published_version,
        metadata_json=metadata_json,
        steps=steps or [],
    )


def _make_step(
    *,
    step_order: int = 1,
    user_description: str = "Test step",
    input_source: str = "flow_input",
    input_type: str = "text",
    output_mode: str = "pass_through",
    output_type: str = "text",
    mcp_policy: str = "inherit",
) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=user_description,
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        mcp_policy=mcp_policy,
    )


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    def test_basic_prompt_contains_role(self) -> None:
        prompt = build_system_prompt()
        assert "expert" in prompt.lower()
        assert OUTLINE_FLOW_TOOL_NAME in prompt
        assert "propose_flow" not in prompt

    def test_prompt_contains_knowledge_pack_sections(self) -> None:
        # Discovery phase (no confirmed requirements) — core sections only
        prompt = build_system_prompt()
        assert "Outline-flow-kompilering" in prompt
        assert "Instruktioner vs Underlag" not in prompt

        # Confirmed requirements still use the compact server-state prompt;
        # final proposal has its own task-specific outline_flow prompt.
        prompt_confirmed = build_system_prompt(
            confirmed_requirements={
                "summary": "Test",
                "key_decisions": [],
                "input_description": "Test",
                "output_description": "Test",
            },
        )
        assert "Outline-flow-kompilering" in prompt_confirmed
        assert "Flow capabilities (engine truth)" in prompt_confirmed
        assert "Create-läge: kompilerad datamodell" not in prompt_confirmed
        assert "Create-läge: vanliga mönster" not in prompt_confirmed

    def test_confirmed_prompt_omits_legacy_create_recipe_examples(self) -> None:
        prompt = build_system_prompt(
            confirmed_requirements={
                "summary": "Build a PDF summary from uploaded documents",
                "key_decisions": [],
                "input_description": "User uploads PDF documents",
                "output_description": "Generate a PDF summary",
            },
        )

        assert "Outline-flow-kompilering" in prompt
        assert "Dokumentpaket -> JSON -> grounded text -> DOCX/PDF" not in prompt
        assert "Audio -> text -> analys -> rapport" not in prompt

    def test_create_mode_prompt_stays_on_ir_surface(self) -> None:
        prompt = build_system_prompt(
            confirmed_requirements={
                "summary": "Test",
                "key_decisions": [],
                "input_description": "Test",
                "output_description": "Test",
            },
        )
        # Planner-emitted-variable syntax stays hidden in create mode;
        # templating is backend-compiled, not planner-authored.
        assert "input_bindings.question" not in prompt
        assert "{{ step_a.output.text }}" not in prompt
        assert "do not emit plan_step_ref values" in prompt
        # Create-mode IR surface (what the planner DOES emit) stays present.
        assert "output_fields" in prompt
        assert "runtime_input" in prompt
        assert "runtime_upload" not in prompt

    def test_edit_mode_prompt_keeps_canonical_variable_documentation(self) -> None:
        prompt = build_system_prompt(
            flow_context="Namn: Test\nAntal steg: 2",
            is_edit_mode=True,
        )
        assert "{{ step_a.output.text }}" in prompt
        assert "{{ föregående_steg }}" in prompt
        assert "{{ step_input.text }}" in prompt
        assert "uses_previous_fields" in prompt
        assert "input_bindings" in prompt
        assert "question" in prompt
        assert "plan_step_ref" in prompt
        assert "Blanda inte `step_a` och `step_1`" in prompt
        assert "Använd inte stegnamn" in prompt

    def test_create_mode_prompt_contains_semantic_flow_contract(self) -> None:
        prompt = build_system_prompt()
        assert "outline_flow" in prompt
        assert "backend derives step topology" in prompt
        assert "do not emit input_source in create mode" in prompt
        assert '"input_source":' not in prompt

    def test_prompt_exposes_mcp_refs_as_step_scoped_resources(self) -> None:
        prompt = build_system_prompt(
            available_mcp_servers=[
                {
                    "ref": "server-1",
                    "name": "Case system",
                    "display_name": "Case system",
                    "description": "Live case data.",
                    "tools": [
                        {
                            "ref": "tool-1",
                            "name": "lookup_case",
                            "display_name": "Lookup case",
                            "description": "Fetch a case.",
                        }
                    ],
                }
            ]
        )

        assert "Tillgängliga MCP-verktyg" in prompt
        assert "server_ref=`server-1`" in prompt
        assert "Lookup case [tool-1]: Fetch a case." in prompt
        assert "mcp_tool_refs" in prompt
        assert "ska inte köra MCP-verktyg" in prompt
        assert "Verktygsbeskrivningar är beslutsstöd" in prompt
        assert "systemval eller tillstånd saknas" in prompt
        assert "ställ en kort förtydligande fråga" in prompt
        assert "Kombinera inte MCP med `knowledge_refs`" in prompt

    def test_prompt_omits_malformed_mcp_resources(self) -> None:
        prompt = build_system_prompt(
            available_mcp_servers=[
                {"ref": "", "name": "Broken", "tools": [{"ref": "ignored-tool"}]},
                {
                    "ref": "server-1",
                    "name": "Case system",
                    "tools": [
                        {"ref": " ", "name": "blank"},
                        {"ref": "tool-1", "name": "lookup_case"},
                    ],
                },
            ]
        )

        assert "server_ref=`server-1`" in prompt
        assert "lookup_case [tool-1]" in prompt
        assert "ignored-tool" not in prompt
        assert "blank [" not in prompt

    def test_edit_mode_prompt_contains_flow_chaining_rules(self) -> None:
        prompt = build_system_prompt(
            flow_context="Namn: Test\nAntal steg: 2",
            is_edit_mode=True,
        )
        assert "flow_input" in prompt
        assert "previous_step" in prompt
        assert "all_previous_steps" in prompt
        assert "document" in prompt

    def test_prompt_does_not_contain_validate_flow_draft(self) -> None:
        """validate_flow_draft was removed as an LLM-facing tool to prevent incremental validation."""
        prompt = build_system_prompt()
        assert "validate_flow_draft" not in prompt

    def test_prompt_contains_contract_documentation(self) -> None:
        prompt = build_system_prompt(
            confirmed_requirements={
                "summary": "Test",
                "key_decisions": [],
                "input_description": "Test",
                "output_description": "Test",
            },
        )
        assert "output_fields" in prompt
        assert "nesting depth" in prompt
        assert "3" in prompt
        assert "do not emit raw JSON Schema" in prompt

    def test_edit_mode_prompt_uses_edit_flow_contract(self) -> None:
        prompt = build_system_prompt(
            flow_context="Namn: Test\nAntal steg: 2",
            is_edit_mode=True,
        )

        assert "edit_flow" in prompt
        assert "create_flow" not in prompt

    def test_prompt_keeps_architecture_commit_server_derived(self) -> None:
        """The prompt must not ask weaker models to author tuple internals."""
        prompt = build_system_prompt()

        assert "Servern härleder `architecture_commit`" in prompt
        assert '"architecture_commit": null' in prompt
        assert "StepTriple" not in prompt
        assert "INTE arrayer/tupler" not in prompt

    def test_prompt_with_flow_context(self) -> None:
        flow = _make_flow(
            name="Tjänsteskrivelse",
            steps=[
                _make_step(step_order=1, user_description="Extrahera"),
                _make_step(
                    step_order=2, user_description="Bedöm", input_source="previous_step"
                ),
            ],
        )
        context = build_flow_context(flow)
        prompt = build_system_prompt(flow_context=context)
        assert "Tjänsteskrivelse" in prompt
        assert "Extrahera" in prompt
        assert "Bedöm" in prompt

    def test_prompt_with_models(self) -> None:
        models = [
            {"ref": "gpt-4", "name": "GPT-4", "provider": "openai"},
            {"ref": "claude-3", "name": "Claude 3", "provider": "anthropic"},
        ]
        prompt = build_system_prompt(available_models=models)
        assert "gpt-4" in prompt
        assert "claude-3" in prompt
        assert "Tillgängliga modeller" in prompt

    def test_prompt_includes_planner_hints(self) -> None:
        prompt = build_system_prompt(planner_hints="- Fråga först om PDF-omfång.")
        assert "Planeringshintar" in prompt
        assert "PDF-omfång" in prompt

    def test_prompt_includes_active_ui_language_guidance(self) -> None:
        prompt = build_system_prompt(ui_language="sv")
        assert "Aktivt gränssnittsspråk" in prompt
        assert "svenska" in prompt

    def test_prompt_with_knowledge_bases(self) -> None:
        kbs = [
            {
                "ref": "kb_policy",
                "name": "Policy KB",
                "description": "Internal policies",
            },
        ]
        prompt = build_system_prompt(available_knowledge_bases=kbs)
        assert "kb_policy" in prompt
        assert "Tillgängliga kunskapsbaser" in prompt

    def test_prompt_without_optional_sections(self) -> None:
        prompt = build_system_prompt()
        assert "Tillgängliga modeller" not in prompt
        assert "Tillgängliga kunskapsbaser" not in prompt
        assert "Aktuellt flöde" not in prompt

    def test_prompt_deeply_covers_underlag(self) -> None:
        """Create mode should teach compiler-owned underlag behavior without raw bindings."""
        prompt = build_system_prompt(
            confirmed_requirements={
                "summary": "Test",
                "key_decisions": [],
                "input_description": "Test",
                "output_description": "Test",
            },
        )
        assert "underlag" in prompt.lower()
        assert "input_fields" in prompt
        assert "uses_input_fields" in prompt
        assert "uses_previous_fields" in prompt
        assert "input_bindings.question" not in prompt

    def test_prompt_demotes_runtime_only_aliases_and_raw_json_blobs(self) -> None:
        prompt = build_system_prompt(
            confirmed_requirements={
                "summary": "Test",
                "key_decisions": [],
                "input_description": "Test",
                "output_description": "Test",
            },
        )
        assert "kompilerar" in prompt
        assert "råa config-dicts" in prompt or "raw input_config" in prompt

    def test_prompt_covers_json_pipeline_patterns(self) -> None:
        """Create mode should understand JSON extraction via output_fields only."""
        prompt = build_system_prompt(
            confirmed_requirements={
                "summary": "Test",
                "key_decisions": [],
                "input_description": "Test",
                "output_description": "Test",
            },
        )
        assert "json" in prompt.lower()
        assert "output_fields" in prompt
        assert "input_contract" not in prompt

    def test_prompt_has_long_instruction_examples(self) -> None:
        """Per user request — AI must write long, detailed instructions."""
        prompt = build_system_prompt(
            confirmed_requirements={
                "summary": "Test",
                "key_decisions": [],
                "input_description": "Test",
                "output_description": "Test",
            },
        )
        assert "LÅNGA" in prompt or "långa" in prompt

    def test_prompt_omits_validation_repair_examples_from_server_state_prompt(
        self,
    ) -> None:
        prompt = build_system_prompt(
            confirmed_requirements={
                "summary": "Test",
                "key_decisions": [],
                "input_description": "Test",
                "output_description": "Test",
            },
        )
        assert "bad draft" not in prompt.lower()
        assert "felaktigt utkast" not in prompt.lower()
        assert "corrected draft" not in prompt.lower()
        assert "korrigerat utkast" not in prompt.lower()

    def test_prompt_contains_framework_guardrails(self) -> None:
        prompt = build_system_prompt()
        assert "Eneo Flow-ramverket" in prompt
        assert "Python" in prompt
        assert "endast bygga giltiga Eneo-flöden" in prompt

    def test_prompt_publishes_canonical_ask_question_vocabulary(self) -> None:
        prompt = build_system_prompt()
        assert "Ask-question vocabulary" in prompt
        assert "`payload.question_id`" in prompt
        assert "`payload.slot_name`" in prompt
        assert "domain-specific IDs" in prompt
        for slot_name in KNOWN_REQUIREMENT_SLOT_NAMES:
            assert f"`{slot_name}`" in prompt


class TestAllowedActionsPhaseLock:
    """Server-side phase lock: when required architectural slots are still
    unresolved, the prompt must explicitly restrict the allowed planner actions
    for this turn so the LLM cannot even attempt `commit_architecture`.

    The orchestrator-side rejection (`architecture_commit_premature_unresolved_choices`
    in `ai_builder_orchestrator.py`) catches the violation post-hoc, but by
    then an LLM call has been wasted and the user has seen a rejected turn.
    Moving the invariant to the prompt surface prevents the attempt entirely.
    """

    def test_commit_blocked_when_core_slots_unresolved(self) -> None:
        prompt = build_system_prompt(
            unresolved_architectural_choices=frozenset(
                {"primary_runtime_input", "terminal_output"}
            ),
        )
        assert "Tillåtna handlingar denna tur" in prompt, (
            "prompt must render an explicit allowed-actions section when "
            "commit is blocked"
        )
        assert "commit_architecture" in prompt
        lowered = prompt.lower()
        assert "primary_runtime_input" in prompt
        assert "terminal_output" in prompt
        assert "inte tillåtet" in lowered or "ej tillåtet" in lowered, (
            "the section must say commit_architecture is not allowed this turn"
        )
        assert "ask_question" in prompt

    def test_commit_allowed_when_no_slots_unresolved(self) -> None:
        prompt = build_system_prompt(
            unresolved_architectural_choices=frozenset(),
        )
        assert "Tillåtna handlingar denna tur" not in prompt, (
            "prompt must not render the restriction section when all core "
            "slots are resolved — the default protocol allows all actions"
        )

    def test_commit_blocked_section_names_each_unresolved_slot(self) -> None:
        prompt = build_system_prompt(
            unresolved_architectural_choices=frozenset({"terminal_output"}),
        )
        assert "Tillåtna handlingar denna tur" in prompt
        assert "terminal_output" in prompt
        assert (
            "primary_runtime_input"
            not in prompt.split("Tillåtna handlingar denna tur")[1].split("\n\n")[0]
        ), (
            "the blocking-slots list must enumerate only the slots still "
            "unresolved, not every slot name"
        )

    def test_commit_blocked_directive_is_unambiguous_and_unified(self) -> None:
        """Anti-confusion rail: the directive must co-locate the forbidden
        action, the allowed alternatives, and the blocking slots in one
        section so the LLM has no gap where it can guess.
        """
        prompt = build_system_prompt(
            unresolved_architectural_choices=frozenset({"primary_runtime_input"}),
        )
        start = prompt.find("Tillåtna handlingar denna tur")
        assert start != -1
        # Grab a bounded window after the header
        window = prompt[start : start + 1500]
        # All anti-confusion anchors must appear inside the same section
        for token in (
            "commit_architecture",
            "ask_question",
            "primary_runtime_input",
        ):
            assert token in window, (
                f"`{token}` must appear inside the phase-lock section so the "
                "LLM sees the full contract in one place"
            )

    def test_action_policy_block_takes_precedence_over_legacy_phase_lock(
        self,
    ) -> None:
        prompt = build_system_prompt(
            unresolved_architectural_choices=frozenset({"primary_runtime_input"}),
            action_policy=PlannerActionPolicy(
                allowed_action_kinds=("commit_architecture", "confirm_requirements"),
                allowed_ask_question_targets=(),
                blocked_action_reasons={
                    "ask_question": "no unresolved ask_question targets",
                    "propose_plan": "architecture has not been committed",
                },
            ),
        )

        assert "Allowed Planner Actions This Turn" in prompt
        assert (
            "Allowed actions: `commit_architecture`, `confirm_requirements`." in prompt
        )
        assert "Tillåtna handlingar denna tur" not in prompt


class TestAdditionalClarificationHints:
    def test_edit_flow_hints_do_not_reopen_resolved_output_format(self) -> None:
        flow = _make_flow(
            name="Bora",
            steps=[
                _make_step(step_order=1, input_type="audio", output_type="text"),
                _make_step(
                    step_order=2, input_source="previous_step", output_type="json"
                ),
                _make_step(
                    step_order=3, input_source="previous_step", output_type="text"
                ),
            ],
        )
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Behåll samma flöde men gör slutrapporten på engelska och "
                    "lägg till makrotrender."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        hints = build_clarification_hints(
            conversation=conversation,
            latest_user_message=conversation[0].content,
            flow=flow,
        )

        assert hints is not None
        assert 'question_id="final_output_mode"' not in hints

    def test_edit_flow_hints_ignore_previous_answer_label_when_output_is_unchanged(
        self,
    ) -> None:
        flow = _make_flow(
            name="Bora",
            steps=[
                _make_step(step_order=1, input_type="audio", output_type="text"),
                _make_step(
                    step_order=2, input_source="previous_step", output_type="json"
                ),
                _make_step(
                    step_order=3, input_source="previous_step", output_type="text"
                ),
            ],
        )
        conversation = [
            ConversationMessage(
                role="user",
                content="DOCX document",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_option_id": "docx_document",
                    }
                },
            ),
            ConversationMessage(
                role="user",
                content="Behåll samma flöde men lägg till makrotrender.",
                metadata={"ui_language": "sv"},
            ),
        ]

        hints = build_clarification_hints(
            conversation=conversation,
            latest_user_message=conversation[-1].content,
            flow=flow,
        )

        assert hints is not None
        assert "öppna inte en ny fråga om output-format" in hints.lower()


# ---------------------------------------------------------------------------
# Flow context
# ---------------------------------------------------------------------------


class TestBuildFlowContext:
    def test_empty_flow(self) -> None:
        flow = _make_flow(name="Nytt flöde")
        ctx = build_flow_context(flow)
        assert "Nytt flöde" in ctx
        assert "Antal steg: 0" in ctx

    def test_flow_with_steps(self) -> None:
        flow = _make_flow(
            name="Pipeline",
            steps=[
                _make_step(step_order=1, user_description="Extrahera fakta"),
                _make_step(
                    step_order=2,
                    user_description="Bedöm konsekvenser",
                    input_source="previous_step",
                ),
            ],
        )
        ctx = build_flow_context(flow)
        assert "Extrahera fakta" in ctx
        assert "Bedöm konsekvenser" in ctx
        assert "existing_step_1" in ctx


class TestBuildClarificationHints:
    def test_flags_multi_pdf_scope_when_unanswered(self) -> None:
        hints = build_clarification_hints(
            conversation=[],
            latest_user_message=(
                "Jag vill ladda upp ett eller flera PDF-dokument och jämföra innehållet mellan dokumenten."
            ),
        )

        assert hints is not None
        assert "document_material_scope" in hints

    def test_includes_structured_intermediate_hint_for_complex_analysis_reports(
        self,
    ) -> None:
        hints = build_clarification_hints(
            conversation=[],
            latest_user_message=(
                "Bygg ett flöde som tar emot officiella ärendedokument, extraherar centrala fakta, "
                "gör en sociologisk och psykologisk analys och genererar en strukturerad PDF-rapport."
            ),
        )

        assert hints is not None
        assert "mellanliggande" in hints.lower()
        assert "json" in hints.lower()

    def test_does_not_include_structured_intermediate_hint_for_simple_summary(
        self,
    ) -> None:
        hints = build_clarification_hints(
            conversation=[],
            latest_user_message="Bygg ett flöde som sammanfattar ett dokument och genererar en PDF.",
        )

        assert hints is None or "mellanliggande" not in hints.lower()

    def test_skips_multi_pdf_scope_when_already_answered(self) -> None:
        hints = build_clarification_hints(
            conversation=[
                ConversationMessage(
                    role="user",
                    content="Flera dokument samtidigt",
                    metadata={
                        "question_answer": {
                            "question_id": "document_material_scope",
                            "selected_option_id": "multiple_documents_case",
                        }
                    },
                )
            ],
            latest_user_message=(
                "Jag vill ladda upp ett eller flera PDF-dokument och jämföra innehållet mellan dokumenten."
            ),
        )

        assert hints is not None
        assert "document_material_scope" not in hints

    def test_generic_docx_prompt_does_not_flag_docx_mode_when_default_is_safe(
        self,
    ) -> None:
        hints = build_clarification_hints(
            conversation=[],
            latest_user_message="Skapa en färdig DOCX-rapport av analysen.",
        )

        assert hints is not None
        assert "docx_output_mode" not in hints

    def test_word_instead_of_pdf_edit_does_not_flag_docx_mode_when_default_is_safe(
        self,
    ) -> None:
        flow = Flow(
            id=uuid4(),
            name="Ljudrapport",
            description="",
            tenant_id=uuid4(),
            user_id=uuid4(),
            space_id=uuid4(),
            steps=[
                FlowStep(
                    id=uuid4(),
                    flow_id=uuid4(),
                    tenant_id=uuid4(),
                    assistant_id=uuid4(),
                    step_order=1,
                    user_description="Skriv slutrapport",
                    input_source="flow_input",
                    input_type="document",
                    output_mode="pass_through",
                    output_type="pdf",
                    mcp_policy="inherit",
                )
            ],
            metadata_json=None,
            published=False,
            published_version=None,
            draft_revision=1,
        )

        hints = build_clarification_hints(
            conversation=[],
            latest_user_message="ändra så att jag får ut en word dokument istället för en pdf",
            flow=flow,
        )

        assert hints is not None
        assert "docx_output_mode" not in hints
        assert "terminala dokumentsteget" in hints

    def test_pdf_clarification_does_not_emit_docx_template_hints_from_stale_template_wording(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill fylla i en mall med transkriberingen.",
            ),
            ConversationMessage(
                role="user",
                content="Jag vill få ut en pdf sammanfattning.",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_values": ["pdf_document"],
                    }
                },
            ),
        ]

        hints = build_clarification_hints(
            conversation=conversation,
            latest_user_message=conversation[-1].content,
        )

        assert hints is not None
        assert "docx_output_mode" not in hints
        assert "template_fill" not in hints

    def test_pdf_template_expectation_surfaces_pdf_generation_question_before_docx_hint(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill skapa en PDF från en mall.",
            ),
            ConversationMessage(
                role="user",
                content="PDF-dokument",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_values": ["pdf_document"],
                    }
                },
            ),
        ]

        hints = build_clarification_hints(
            conversation=conversation,
            latest_user_message=conversation[-1].content,
        )

        assert hints is not None
        assert "pdf_generation_mode" in hints
        assert "docx_output_mode" not in hints

    def test_includes_runtime_upload_hint_for_pdf_flows(self) -> None:
        hints = build_clarification_hints(
            conversation=[],
            latest_user_message="Låt användaren ladda upp PDF-filer som ska analyseras.",
        )

        assert hints is not None
        assert "Ta emot filer vid körning" in hints
        assert "låsta arkitekturen" in hints
        assert "runtime_upload" not in hints

    def test_includes_form_field_and_contract_hints_for_structured_analysis_flows(
        self,
    ) -> None:
        hints = build_clarification_hints(
            conversation=[],
            latest_user_message=(
                "Användaren ska kunna ange referensnummer och önskat språk. "
                "Extrahera strukturerad JSON med fält för risker, möjligheter och rekommendationer."
            ),
        )

        assert hints is not None
        assert "form_fields" in hints
        assert "output_fields" in hints

    def test_includes_form_field_hint_for_sectioned_rubric_intake_flows(self) -> None:
        hints = build_clarification_hints(
            conversation=[],
            latest_user_message=(
                "Visa en sektion i taget och be användaren om fritext för varje sektion. "
                "Spara innehållet separat per rubrik och skapa sedan ett DOCX-dokument."
            ),
        )

        assert hints is not None
        assert "form_fields" in hints
        assert "ett textfält per rubrik" in hints

    def test_output_heading_hint_rejects_runtime_form_field_modeling(self) -> None:
        hints = build_clarification_hints(
            conversation=[],
            latest_user_message=(
                "Transkribera ljud och sammanfatta mötet. Jag vill ha rubrikerna "
                "i varje steg för Sekreterare, Föregående protokoll, Diskussion och Beslut."
            ),
        )

        assert hints is not None
        assert "Modellera därför inte rubrikerna som `form_fields`" in hints

    def test_create_mode_hints_reference_outline_flow_instead_of_legacy_submission_tool(
        self,
    ) -> None:
        hints = build_clarification_hints(
            conversation=[],
            latest_user_message="Skapa en PDF från en mall.",
        )

        assert hints is not None
        assert OUTLINE_FLOW_TOOL_NAME in hints
        assert "propose_flow" not in hints

    def test_pdf_scope_hint_uses_v2_ask_question_vocabulary(self) -> None:
        hints = build_clarification_hints(
            conversation=[],
            latest_user_message=(
                "Jag vill ladda upp ett eller flera PDF-dokument och jämföra innehållet mellan dokumenten."
            ),
        )

        assert hints is not None
        assert "document_material_scope" in hints
        assert "ask_structured_question" not in hints
        assert "ask_question" in hints

    def test_flow_with_form_fields(self) -> None:
        flow = _make_flow(
            metadata_json={
                "form_schema": {
                    "fields": [
                        {"name": "Referensnummer", "type": "text"},
                        {"name": "Prioritet", "type": "select"},
                    ]
                }
            },
        )
        ctx = build_flow_context(flow)
        assert "Referensnummer" in ctx
        assert "Prioritet" in ctx
        assert "Formulärfält" in ctx

    def test_published_flow(self) -> None:
        flow = _make_flow(published_version=3)
        ctx = build_flow_context(flow)
        assert "Ja (v3)" in ctx

    def test_draft_revision_shown(self) -> None:
        flow = _make_flow(draft_revision=5)
        ctx = build_flow_context(flow)
        assert "Draft-revision: 5" in ctx

    def test_step_without_name(self) -> None:
        flow = _make_flow(
            steps=[_make_step(step_order=1, user_description=None)],  # type: ignore[arg-type]
        )
        ctx = build_flow_context(flow)
        assert "(namnlöst)" in ctx

    def test_step_with_input_bindings(self) -> None:
        step = _make_step(step_order=1, user_description="Bedöm")
        step.input_bindings = {"question": "BAKGRUND:\n{{ step_1.output.text }}"}
        flow = _make_flow(steps=[step])
        ctx = build_flow_context(flow)
        assert "Underlag:" in ctx
        assert "{{ step_1.output.text }}" in ctx

    def test_step_with_output_contract(self) -> None:
        step = _make_step(step_order=1, user_description="Extrahera")
        step.output_contract = {
            "type": "object",
            "properties": {
                "sammanfattning": {"type": "string"},
                "risk": {"type": "string"},
            },
        }
        flow = _make_flow(steps=[step])
        ctx = build_flow_context(flow)
        assert "Utdatakontrakt:" in ctx
        assert "sammanfattning" in ctx
        assert "risk" in ctx

    def test_step_with_input_contract(self) -> None:
        step = _make_step(step_order=1, user_description="Validera")
        step.input_contract = {
            "type": "object",
            "properties": {
                "referensnummer": {"type": "string"},
                "bakgrund": {"type": "string"},
            },
        }
        flow = _make_flow(steps=[step])
        ctx = build_flow_context(flow)
        assert "Indatakontrakt:" in ctx
        assert "referensnummer" in ctx

    def test_long_bindings_are_truncated(self) -> None:
        step = _make_step(step_order=1, user_description="Steg")
        step.input_bindings = {"question": "A" * 200}
        flow = _make_flow(steps=[step])
        ctx = build_flow_context(flow)
        assert "..." in ctx

    def test_flow_context_includes_assistant_snapshots(self) -> None:
        step = _make_step(step_order=1, user_description="Analysera")
        step.output_config = {
            "bindings": {"SAMMANFATTNING": "{{ step_1.output.structured.summary }}"},
        }
        flow = _make_flow(steps=[step])
        ctx = build_flow_context(
            flow,
            assistant_snapshots={
                step.assistant_id: {
                    "instructions": "Extrahera summary, keywords och teman.",
                    "model_ref": "model-uuid-1",
                    "model_label": "GPT-4",
                    "knowledge_refs": ["kb-policy", "kb-archive"],
                    "knowledge_labels": ["Policy", "Archive"],
                }
            },
        )
        assert "Syfte:" in ctx
        assert "Extrahera summary" in ctx
        assert "Modell: GPT-4 [model-uuid-1]" in ctx
        assert "Kunskapsbaser: Policy [kb-policy], Archive [kb-archive]" in ctx
        assert "Output config" in ctx

    def test_edit_mode_flow_context_uses_structured_capability_brief(self) -> None:
        step_one = _make_step(
            step_order=1,
            user_description="Extrahera text",
            input_source="flow_input",
            input_type="file",
            output_mode="pass_through",
            output_type="text",
        )
        step_one.input_config = {"runtime_input": {"enabled": True, "max_files": 3}}
        step_one.output_config = {"citation_mode": "inline_inref_sidecar"}
        step_two = _make_step(
            step_order=2,
            user_description="Generera rapport",
            input_source="previous_step",
            input_type="text",
            output_mode="pass_through",
            output_type="pdf",
        )
        flow = _make_flow(
            name="Rapportflöde",
            steps=[step_one, step_two],
            metadata_json={
                "form_schema": {"fields": [{"name": "Referensnummer", "type": "text"}]}
            },
        )

        ctx = build_flow_context(
            flow,
            assistant_snapshots={
                step_two.assistant_id: {
                    "knowledge_refs": ["kb-policy"],
                    "knowledge_labels": ["Policy"],
                }
            },
            is_edit_mode=True,
            capabilities=build_flow_capability_profile(flow),
            edit_scope=EditScopeResolution(
                settled_families=frozenset({"input_shape", "output_artifact"}),
                active_families=frozenset({"output_artifact"}),
                requested_output_artifact="docx_document",
            ),
        )

        assert "Flödets nuvarande profil" in ctx
        assert "Indata: dokument via steg 1" in ctx
        assert "Utdata: PDF via steg 2" in ctx
        assert "Formulär: Referensnummer" in ctx
        assert "Kunskapsbaser: steg 2 (Policy)" in ctx
        assert "Källhänvisningar: steg 1" in ctx
        assert "Aktiv familj: output_artifact" in ctx
        assert "Begärd ändring: PDF -> DOCX" in ctx
        assert "Draft-revision" not in ctx


# ---------------------------------------------------------------------------
# Model / KB context builders
# ---------------------------------------------------------------------------


class TestContextBuilders:
    def test_build_models_context(self) -> None:
        models = [{"id": "abc-123", "name": "GPT-4", "provider": "openai"}]
        result = build_available_models_context(models)
        assert len(result) == 1
        assert result[0]["ref"] == "abc-123"
        assert result[0]["name"] == "GPT-4"

    def test_build_kbs_context(self) -> None:
        kbs = [{"id": "kb-1", "name": "Policy", "description": "Company policies"}]
        result = build_available_kbs_context(kbs)
        assert len(result) == 1
        assert result[0]["ref"] == "kb-1"
        assert result[0]["display_name"] == "Policy"
        assert result[0]["description"] == "Company policies"

    def test_build_kbs_context_no_description(self) -> None:
        kbs = [{"id": "kb-1", "name": "Policy"}]
        result = build_available_kbs_context(kbs)
        assert result[0]["description"] == ""


# ---------------------------------------------------------------------------
# Step ref mapping
# ---------------------------------------------------------------------------


class TestStepRefMapping:
    def test_maps_step_order_to_id(self) -> None:
        step1 = _make_step(step_order=1)
        step2 = _make_step(step_order=2)
        flow = _make_flow(steps=[step1, step2])
        mapping = build_step_ref_mapping(flow)
        assert mapping["existing_step_1"] == step1.id
        assert mapping["existing_step_2"] == step2.id

    def test_empty_flow(self) -> None:
        flow = _make_flow()
        mapping = build_step_ref_mapping(flow)
        assert mapping == {}

    def test_step_without_id_skipped(self) -> None:
        step = FlowStep(
            id=None,
            assistant_id=uuid4(),
            step_order=1,
            input_source="flow_input",
            input_type="text",
            output_mode="pass_through",
            output_type="text",
            mcp_policy="inherit",
        )
        flow = _make_flow(steps=[step])
        mapping = build_step_ref_mapping(flow)
        assert mapping == {}


# ---------------------------------------------------------------------------
# Conversation trimming
# ---------------------------------------------------------------------------


class TestBuildPlanSummary:
    def test_basic_summary(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Sammanfatta dokument",
            flow_description="Extraherar och sammanfattar",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Extrahera fakta",
                    assistant_spec=AssistantSpec(instructions="Extrahera."),
                    input_source="flow_input",
                ),
            ],
        )
        summary = build_plan_summary(spec)
        assert "Sammanfatta dokument" in summary
        assert "Extrahera fakta" in summary
        assert "step_a" in summary
        assert "Antal steg: 1" in summary

    def test_summary_includes_output_contract_fields(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Pipeline",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Extrahera",
                    assistant_spec=AssistantSpec(instructions="Gör det."),
                    input_source="flow_input",
                    output_type="json",
                    output_contract={
                        "type": "object",
                        "properties": {
                            "sammanfattning": {"type": "string"},
                            "risk": {"type": "string"},
                        },
                    },
                ),
            ],
        )
        summary = build_plan_summary(spec)
        assert "sammanfattning" in summary
        assert "risk" in summary
        assert "Utdatakontrakt" in summary

    def test_summary_includes_form_fields(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Formulärflöde",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Steg 1",
                    assistant_spec=AssistantSpec(instructions="Test."),
                    input_source="flow_input",
                ),
            ],
            form_fields=[
                FormFieldSpec(name="Referensnummer", type="text", label="Ärende"),
                FormFieldSpec(name="Prioritet", type="select", label="Prio"),
            ],
        )
        summary = build_plan_summary(spec)
        assert "Referensnummer" in summary
        assert "Prioritet" in summary
        assert "Formulärfält" in summary

    def test_summary_includes_assumptions(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Test",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="S1",
                    assistant_spec=AssistantSpec(instructions="X."),
                    input_source="flow_input",
                ),
            ],
        )
        summary = build_plan_summary(spec, assumptions=["Texten är på svenska"])
        assert "Texten är på svenska" in summary
        assert "Antaganden" in summary

    def test_summary_shows_existing_step_ref(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Edit flow",
            steps=[
                StepSpec(
                    plan_step_ref="step_a",
                    name="Uppdaterat steg",
                    existing_step_ref="existing_step_1",
                    assistant_spec=AssistantSpec(instructions="Ny instruktion."),
                    input_source="flow_input",
                ),
            ],
        )
        summary = build_plan_summary(spec)
        assert "existing_step_1" in summary
        assert "modifierar" in summary


class TestTrimConversation:
    def test_within_budget_unchanged(self) -> None:
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        result = trim_conversation_for_context(messages, max_tokens=999_999)
        assert len(result) == 2

    def test_over_budget_keeps_recent(self) -> None:
        messages = [
            {"role": "user", "content": f"Message {i}" + "x" * 100} for i in range(20)
        ]
        # Small budget forces trimming to only the most recent messages
        result = trim_conversation_for_context(messages, max_tokens=200)
        assert len(result) < 20
        assert result[-1]["content"].startswith("Message 19")

    def test_empty_messages(self) -> None:
        result = trim_conversation_for_context([], max_tokens=999_999)
        assert result == []

    def test_returns_new_list(self) -> None:
        messages = [{"role": "user", "content": "Test"}]
        result = trim_conversation_for_context(messages, max_tokens=999_999)
        assert result is not messages

    def test_tool_call_and_result_kept_together(self) -> None:
        """When trimming, assistant+tool_calls and tool result messages are atomic."""
        messages = [
            {"role": "user", "content": "Old message 1" + "x" * 500},
            {"role": "user", "content": "Old message 2" + "x" * 500},
            {"role": "user", "content": "Build a flow"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "outline_flow", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "content": "Plan: Test flow", "tool_call_id": "call_1"},
            {"role": "user", "content": "Change step 2"},
        ]
        # Budget that fits the tool group + last user msg but not the old messages
        result = trim_conversation_for_context(messages, max_tokens=200)
        roles = [m["role"] for m in result]
        # The assistant+tool pair should be kept together
        assert "assistant" in roles
        assert "tool" in roles
        # Tool result should follow its assistant
        assistant_idx = roles.index("assistant")
        tool_idx = roles.index("tool")
        assert tool_idx == assistant_idx + 1

    def test_tool_call_group_not_split(self) -> None:
        """Trimming should never orphan a tool result from its assistant."""
        messages = [
            {"role": "user", "content": f"Msg {i}" + "x" * 200} for i in range(8)
        ] + [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_x",
                        "type": "function",
                        "function": {"name": "outline_flow", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "content": "Plan summary", "tool_call_id": "call_x"},
            {"role": "user", "content": "Final msg"},
        ]
        result = trim_conversation_for_context(messages, max_tokens=300)
        # Should never have a tool message without its preceding assistant
        for i, msg in enumerate(result):
            if msg.get("role") == "tool":
                assert i > 0
                assert result[i - 1].get("role") == "assistant"

    def test_token_budget_trims_old_large_messages(self) -> None:
        messages = [
            {"role": "user", "content": "A" * 1200},
            {"role": "assistant", "content": "B" * 1200},
            {"role": "user", "content": "Keep me"},
            {"role": "assistant", "content": "And me"},
        ]

        result = trim_conversation_for_context(messages, max_tokens=80)

        assert [message["content"] for message in result] == ["Keep me", "And me"]

    def test_token_budget_keeps_latest_tool_call_group_atomic(self) -> None:
        messages = [
            {"role": "user", "content": "A" * 1200},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_latest",
                        "type": "function",
                        "function": {"name": "outline_flow", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "content": "Plan summary", "tool_call_id": "call_latest"},
        ]

        result = trim_conversation_for_context(messages, max_tokens=20)

        assert len(result) == 2
        assert result[0]["role"] == "assistant"
        assert result[1]["role"] == "tool"

    def test_large_budget_keeps_everything(self) -> None:
        """With a budget larger than the conversation, nothing is trimmed."""
        messages = [{"role": "user", "content": f"Message {i}"} for i in range(50)]
        result = trim_conversation_for_context(messages, max_tokens=999_999)
        assert len(result) == 50
