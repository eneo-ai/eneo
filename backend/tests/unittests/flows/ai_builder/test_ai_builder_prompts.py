"""Tests for AI Builder system prompt construction and context management."""

from __future__ import annotations

from uuid import uuid4

from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    ConversationMessage,
    FlowDraftSpecCore,
    FormFieldSpec,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_prompts import (
    _extract_signals_from_requirements,
    build_available_kbs_context,
    build_clarification_hints,
    build_available_models_context,
    build_flow_context,
    build_plan_summary,
    build_step_ref_mapping,
    build_system_prompt,
    trim_conversation_for_context,
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
        assert "propose_flow" in prompt

    def test_prompt_contains_knowledge_pack_sections(self) -> None:
        # Discovery phase (no confirmed requirements) — core sections only
        prompt = build_system_prompt()
        assert "Flödesarkitektur" in prompt
        assert "Variabelsystemet" in prompt
        assert "Instruktioner vs Underlag" in prompt

        # Proposal phase (confirmed requirements) — full content
        prompt_confirmed = build_system_prompt(
            confirmed_requirements={
                "summary": "Test",
                "key_decisions": [],
                "input_description": "Test",
                "output_description": "Test",
            },
        )
        assert "Kontrakt" in prompt_confirmed or "kontrakt" in prompt_confirmed
        assert "Antimönster" in prompt_confirmed
        assert "Stegdesignprinciper" in prompt_confirmed

    def test_prompt_contains_variable_documentation(self) -> None:
        prompt = build_system_prompt()
        assert "{{ step_a.output.text }}" in prompt
        assert "{{ föregående_steg }}" in prompt
        assert "{{ step_input.text }}" in prompt
        assert "input_bindings" in prompt
        assert "question" in prompt
        assert "plan_step_ref" in prompt
        assert "Blanda inte `step_a` och `step_1`" in prompt
        assert "Använd inte stegnamn" in prompt
        assert "runtime_input" in prompt
        assert "Ta emot filer vid körning" in prompt

    def test_prompt_contains_chaining_rules(self) -> None:
        prompt = build_system_prompt()
        assert "flow_input" in prompt
        assert "previous_step" in prompt
        assert "all_previous_steps" in prompt
        assert "document" in prompt
        assert "input_config.runtime_input.enabled=true" in prompt

    def test_prompt_does_not_contain_validate_flow_draft(self) -> None:
        """validate_flow_draft was removed as an LLM-facing tool to prevent incremental validation."""
        prompt = build_system_prompt()
        assert "validate_flow_draft" not in prompt

    def test_prompt_contains_contract_documentation(self) -> None:
        # Contracts are only included in proposal phase (confirmed requirements)
        prompt = build_system_prompt(
            confirmed_requirements={
                "summary": "Test",
                "key_decisions": [],
                "input_description": "Test",
                "output_description": "Test",
            },
        )
        assert "input_contract" in prompt
        assert "output_contract" in prompt
        assert "JSON Schema" in prompt

    def test_prompt_with_flow_context(self) -> None:
        flow = _make_flow(
            name="Tjänsteskrivelse",
            steps=[
                _make_step(step_order=1, user_description="Extrahera"),
                _make_step(step_order=2, user_description="Bedöm", input_source="previous_step"),
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
            {"ref": "kb_policy", "name": "Policy KB", "description": "Internal policies"},
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
        """The AI must deeply understand how 'underlag' (input_bindings.question) works."""
        prompt = build_system_prompt()
        # Must explain that underlag is where you compose text from variables
        assert "Underlag" in prompt
        # Must explain the difference between instructions and underlag
        assert "Instruktioner" in prompt
        # Must have concrete examples with variable syntax
        assert "{{ step_a.output." in prompt
        assert "{{ step_input.text }}" in prompt
        # Must explain form field variables
        assert "Ärendenummer" in prompt or "formulärfält" in prompt.lower()

    def test_prompt_demotes_runtime_only_aliases_and_raw_json_blobs(self) -> None:
        prompt = build_system_prompt(
            confirmed_requirements={
                "summary": "Test",
                "key_decisions": [],
                "input_description": "Test",
                "output_description": "Test",
            },
        )
        assert "inte primär AI-authoring" in prompt
        assert "hela JSON-blobs" in prompt
        assert "output.structured" in prompt

    def test_prompt_covers_json_pipeline_patterns(self) -> None:
        """The AI must understand when to use JSON input/output with contracts."""
        prompt = build_system_prompt(
            confirmed_requirements={
                "summary": "Test", "key_decisions": [],
                "input_description": "Test", "output_description": "Test",
            },
        )
        assert "json" in prompt.lower()
        assert "output_contract" in prompt
        assert "input_contract" in prompt

    def test_prompt_has_long_instruction_examples(self) -> None:
        """Per user request — AI must write long, detailed instructions."""
        prompt = build_system_prompt(
            confirmed_requirements={
                "summary": "Test", "key_decisions": [],
                "input_description": "Test", "output_description": "Test",
            },
        )
        assert "500+" in prompt or "flera hundra" in prompt or "LÅNGA" in prompt

    def test_prompt_contains_validation_repair_examples(self) -> None:
        prompt = build_system_prompt(
            confirmed_requirements={
                "summary": "Test", "key_decisions": [],
                "input_description": "Test", "output_description": "Test",
            },
        )
        assert "bad draft" in prompt.lower() or "felaktigt utkast" in prompt.lower()
        assert "validation error" in prompt.lower() or "valideringsfel" in prompt.lower()
        assert "corrected draft" in prompt.lower() or "korrigerat utkast" in prompt.lower()

    def test_prompt_contains_framework_guardrails(self) -> None:
        prompt = build_system_prompt()
        assert "Eneo Flow-ramverket" in prompt
        assert "Python" in prompt
        assert "endast bygga giltiga Eneo-flöden" in prompt


class TestAdditionalClarificationHints:
    def test_edit_flow_hints_do_not_reopen_resolved_output_format(self) -> None:
        flow = _make_flow(
            name="Bora",
            steps=[
                _make_step(step_order=1, input_type="audio", output_type="text"),
                _make_step(step_order=2, input_source="previous_step", output_type="json"),
                _make_step(step_order=3, input_source="previous_step", output_type="text"),
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
        assert "question_id=\"final_output_mode\"" not in hints

    def test_edit_flow_hints_ignore_previous_answer_label_when_output_is_unchanged(self) -> None:
        flow = _make_flow(
            name="Bora",
            steps=[
                _make_step(step_order=1, input_type="audio", output_type="text"),
                _make_step(step_order=2, input_source="previous_step", output_type="json"),
                _make_step(step_order=3, input_source="previous_step", output_type="text"),
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

    def test_flags_docx_mode_when_unspecified(self) -> None:
        hints = build_clarification_hints(
            conversation=[],
            latest_user_message="Skapa en färdig DOCX-rapport av analysen.",
        )

        assert hints is not None
        assert "docx_output_mode" in hints

    def test_pdf_clarification_does_not_emit_docx_template_hints_from_stale_template_wording(self) -> None:
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

    def test_pdf_template_expectation_surfaces_pdf_generation_question_before_docx_hint(self) -> None:
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

    def test_requirements_output_pdf_does_not_force_document_input_signal(self) -> None:
        signals = _extract_signals_from_requirements(
            {
                "input_description": "Användaren laddar upp en ljudfil med ett medarbetarsamtal.",
                "output_description": "Det räcker med en PDF-sammanfattning av samtalet.",
            }
        )

        assert signals["input_material_mode"] == {"audio"}
        assert signals["final_output_mode"] == {"pdf_document"}

    def test_includes_form_field_and_contract_hints_for_structured_analysis_flows(self) -> None:
        hints = build_clarification_hints(
            conversation=[],
            latest_user_message=(
                "Användaren ska kunna ange ärendenummer och önskat språk. "
                "Extrahera strukturerad JSON med fält för risker, möjligheter och rekommendationer."
            ),
        )

        assert hints is not None
        assert "form_fields" in hints
        assert "output_contract" in hints

    def test_flow_with_form_fields(self) -> None:
        flow = _make_flow(
            metadata_json={
                "form_schema": {
                    "fields": [
                        {"name": "Ärendenummer", "type": "text"},
                        {"name": "Prioritet", "type": "select"},
                    ]
                }
            },
        )
        ctx = build_flow_context(flow)
        assert "Ärendenummer" in ctx
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
                "ärendenummer": {"type": "string"},
                "bakgrund": {"type": "string"},
            },
        }
        flow = _make_flow(steps=[step])
        ctx = build_flow_context(flow)
        assert "Indatakontrakt:" in ctx
        assert "ärendenummer" in ctx

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
                    "model_ref": "gpt-4",
                    "knowledge_refs": ["kb-policy", "kb-archive"],
                }
            },
        )
        assert "Syfte:" in ctx
        assert "Extrahera summary" in ctx
        assert "Modell: gpt-4" in ctx
        assert "Kunskapsbaser: kb-policy, kb-archive" in ctx
        assert "Output config" in ctx


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
                FormFieldSpec(name="Ärendenummer", type="text", label="Ärende"),
                FormFieldSpec(name="Prioritet", type="select", label="Prio"),
            ],
        )
        summary = build_plan_summary(spec)
        assert "Ärendenummer" in summary
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
            {"role": "user", "content": f"Message {i}" + "x" * 100}
            for i in range(20)
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
                "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "propose_flow", "arguments": "{}"}}],
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
                "tool_calls": [{"id": "call_x", "type": "function", "function": {"name": "propose_flow", "arguments": "{}"}}],
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
                        "function": {"name": "propose_flow", "arguments": "{}"},
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
        messages = [
            {"role": "user", "content": f"Message {i}"}
            for i in range(50)
        ]
        result = trim_conversation_for_context(messages, max_tokens=999_999)
        assert len(result) == 50
