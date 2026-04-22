from __future__ import annotations

from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_plan_quality_critic import (
    build_conversation_aware_quality_feedback,
)


def _step(
    ref: str,
    name: str,
    instructions: str,
    *,
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.TEXT,
    output_type: OutputType = OutputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    output_contract: dict | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        name=name,
        assistant_spec=AssistantSpec(instructions=instructions),
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        output_contract=output_contract,
    )


def test_flags_missing_form_fields_when_runtime_metadata_was_requested() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Add basic metadata",
            "metadata": {
                "question_answer": {
                    "question_id": "runtime_metadata_fields",
                    "selected_values": ["basic_case_metadata"],
                }
            },
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Kommunanalys",
        steps=[
            _step(
                "step_a",
                "Analysera dokument",
                "Sammanfatta ärendet.",
                input_type=InputType.DOCUMENT,
            )
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "form_fields" in feedback


def test_flags_missing_form_fields_for_sectioned_rubric_intake_flows() -> None:
    conversation = [
        {
            "role": "user",
            "content": (
                "Visa en sektion i taget, be användaren om fritext för varje sektion, "
                "spara innehållet separat per rubrik och skapa sedan ett DOCX-dokument."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Sammanställning",
        steps=[
            _step(
                "step_a",
                "Samla in sektion 1",
                "Be användaren skriva om första rubriken.",
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {
                        "sektion_1": {"type": "string"},
                    },
                },
            ),
            _step(
                "step_b",
                "Generera DOCX",
                "Skapa slutligt DOCX.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.DOCX,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)

    assert feedback is not None
    assert "form_fields" in feedback
    assert "rubrik" in feedback.lower()


def test_does_not_flag_form_fields_for_output_only_heading_requirements() -> None:
    conversation = [
        {
            "role": "user",
            "content": (
                "Slutrapporten ska innehålla rubrikerna Planering och hälsa, "
                "Tidigare insatser och Ekonomi."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Rapport",
        steps=[
            _step(
                "step_a",
                "Skriv rapport",
                "Skriv rapport med dessa rubriker.",
                output_type=OutputType.DOCX,
            )
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)

    assert feedback is None


def test_does_not_flag_sectioned_rubric_intake_when_form_fields_are_present() -> None:
    conversation = [
        {
            "role": "user",
            "content": (
                "Visa en sektion i taget, be användaren om fritext för varje sektion, "
                "spara innehållet separat per rubrik och skapa sedan ett DOCX-dokument."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Sammanställning",
        form_fields=[
            FormFieldSpec(
                name="planering_och_halsa", type="text", label="Planering och hälsa"
            ),
            FormFieldSpec(
                name="tidigare_insatser", type="text", label="Tidigare insatser"
            ),
        ],
        steps=[
            _step(
                "step_a",
                "Sammanställ underlag",
                "Sammanställ sektionerna till ett DOCX.",
                output_type=OutputType.DOCX,
            )
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)

    assert feedback is None


def test_flags_output_mismatch_against_explicit_pdf_choice() -> None:
    conversation = [
        {
            "role": "user",
            "content": "PDF document",
            "metadata": {
                "question_answer": {
                    "question_id": "final_output_mode",
                    "selected_values": ["pdf_document"],
                }
            },
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Rapport",
        steps=[
            _step(
                "step_a",
                "Skriv rapport",
                "Skriv en rapport.",
                output_type=OutputType.TEXT,
            )
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "PDF" in feedback


def test_flags_template_fill_when_generated_docx_was_explicitly_selected() -> None:
    conversation = [
        {
            "role": "user",
            "content": "ändra så att jag får ut en word dokument istället för en pdf",
            "metadata": {"ui_language": "sv"},
        },
        {
            "role": "user",
            "content": "Genererad DOCX utan mall",
            "metadata": {
                "question_answer": {
                    "question_id": "docx_output_mode",
                    "selected_value": "generated_docx",
                    "answer": "generated_docx",
                }
            },
        },
    ]
    spec = FlowDraftSpecCore(
        flow_name="Rapport",
        steps=[
            _step(
                "step_a",
                "Generera rapport",
                "Skapa ett Word-dokument.",
                output_type=OutputType.DOCX,
                output_mode=OutputMode.TEMPLATE_FILL,
            )
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "genererad DOCX" in feedback
    assert "template_fill" in feedback


def test_flags_missing_structured_extraction_when_user_asked_for_structured_fields() -> (
    None
):
    conversation = [
        {
            "role": "user",
            "content": (
                "Flödet ska extrahera viktiga fakta, risker, möjligheter och rekommendationer "
                "och använda strukturerad data där det förbättrar kvaliteten."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Kommunanalys",
        steps=[
            _step(
                "step_a",
                "Läs dokument",
                "Läs dokumentet och skriv en lång text.",
                input_type=InputType.DOCUMENT,
            ),
            _step(
                "step_b",
                "Skriv beslutsunderlag",
                "Skriv ett beslutsunderlag baserat på föregående steg.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "json" in feedback.lower()
    assert "output_contract" in feedback


def test_does_not_overstructure_simple_single_step_summary() -> None:
    conversation = [
        {"role": "user", "content": "Summarize one uploaded document as plain text."}
    ]
    spec = FlowDraftSpecCore(
        flow_name="Kort sammanfattning",
        steps=[_step("step_a", "Sammanfatta", "Skriv en kort sammanfattning.")],
    )

    assert build_conversation_aware_quality_feedback(conversation, spec) is None


def test_flags_edit_plan_that_fakes_audio_transcription_by_downgrading_to_generic_file() -> (
    None
):
    from uuid import uuid4

    from intric.flows.flow import Flow, FlowStep

    flow = Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Kommunanalys",
        steps=[
            FlowStep(
                assistant_id=uuid4(),
                step_order=1,
                user_description="Analysera dokument",
                input_source="flow_input",
                input_type="document",
                output_mode="pass_through",
                output_type="json",
                mcp_policy="inherit",
            ),
            FlowStep(
                assistant_id=uuid4(),
                step_order=2,
                user_description="Skriv rapport",
                input_source="previous_step",
                input_type="json",
                output_mode="pass_through",
                output_type="pdf",
                mcp_policy="inherit",
            ),
        ],
    )
    conversation = [
        {
            "role": "user",
            "content": (
                "Behåll samma flöde men lägg till ljudfiler och transkribera samtalet först, "
                "och skicka sedan in dokument som vanligt. Jag vill fortfarande ha PDF ut."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Kommunanalys",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                existing_step_ref="existing_step_1",
                name="Analysera underlag",
                assistant_spec=AssistantSpec(
                    instructions=(
                        "Läs ett blandat underlag med samtal och dokument, återge samtalet "
                        "och returnera giltig JSON."
                    )
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.FILE,
                output_type=OutputType.JSON,
            ),
            StepSpec(
                plan_step_ref="step_b",
                existing_step_ref="existing_step_2",
                name="Skriv rapport",
                assistant_spec=AssistantSpec(instructions="Skriv PDF-rapport."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.PDF,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec, flow=flow)

    assert feedback is not None
    assert 'input_type="file"' in feedback
    assert "transkriberingssteg" in feedback
    assert "flow_input" in feedback


def test_allows_audio_first_edit_when_plan_uses_real_transcription_step() -> None:
    from uuid import uuid4

    from intric.flows.flow import Flow, FlowStep

    flow = Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Kommunanalys",
        steps=[
            FlowStep(
                assistant_id=uuid4(),
                step_order=1,
                user_description="Analysera dokument",
                input_source="flow_input",
                input_type="document",
                output_mode="pass_through",
                output_type="json",
                mcp_policy="inherit",
            ),
            FlowStep(
                assistant_id=uuid4(),
                step_order=2,
                user_description="Skriv rapport",
                input_source="previous_step",
                input_type="json",
                output_mode="pass_through",
                output_type="pdf",
                mcp_policy="inherit",
            ),
        ],
    )
    conversation = [
        {
            "role": "user",
            "content": "Byt till ljud som primär indata och transkribera först. Behåll PDF ut.",
            "metadata": {
                "question_answer": {
                    "question_id": "flow_input_architecture",
                    "selected_value": "audio_primary_input",
                }
            },
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Kommunanalys",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Transkribera ljud",
                assistant_spec=AssistantSpec(instructions="Transkribera ljudet."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Analysera samtalet",
                assistant_spec=AssistantSpec(
                    instructions="Analysera transkriberingen."
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.PDF,
            ),
        ],
    )

    assert (
        build_conversation_aware_quality_feedback(conversation, spec, flow=flow) is None
    )


# ── R7: Anti-over-structuring guardrail ──────────────────────────────────


def test_anti_over_structuring_simple_summary_no_json_warning() -> None:
    """R7: Simple summary -> text output, NO JSON warning."""
    conversation = [{"role": "user", "content": "Sammanfatta dokument som text."}]
    spec = FlowDraftSpecCore(
        flow_name="Sammanfattning",
        steps=[
            _step(
                "step_a",
                "Sammanfatta",
                "Skriv en kort sammanfattning.",
                output_type=OutputType.TEXT,
            )
        ],
    )
    assert build_conversation_aware_quality_feedback(conversation, spec) is None


def test_flags_missing_json_contract_when_user_wants_structured_extraction() -> None:
    """Warns when conversation explicitly asks for JSON extraction but spec has none."""
    conversation = [
        {
            "role": "user",
            "content": "Extrahera fält som JSON och skicka vidare till nästa steg.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Extraktion",
        steps=[
            _step(
                "step_a", "Extrahera", "Extrahera data.", input_type=InputType.DOCUMENT
            ),
            _step(
                "step_b",
                "Rapport",
                "Skriv rapport.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )
    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "json" in feedback.lower()


def test_no_json_warning_when_spec_already_has_json_step() -> None:
    """No warning when the spec already has a JSON contract step."""
    conversation = [
        {"role": "user", "content": "Extrahera fält som JSON och skicka vidare."}
    ]
    spec = FlowDraftSpecCore(
        flow_name="Extraktion",
        steps=[
            _step(
                "step_a",
                "Extrahera",
                "Extrahera.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"risk": {"type": "string"}},
                },
            ),
            _step(
                "step_b",
                "Rapport",
                "Skriv rapport.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )
    assert build_conversation_aware_quality_feedback(conversation, spec) is None


def test_flags_missing_input_bindings_for_field_reuse() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Extrahera fält som JSON och använd de specifika fälten i nästa steg.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Fältåteranvändning",
        steps=[
            _step(
                "step_a",
                "Extrahera",
                "Extrahera.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"risk": {"type": "string"}},
                },
            ),
            _step(
                "step_b",
                "Rapport",
                "Skriv rapport baserat på JSON.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
            ),
        ],
    )
    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "uses_previous_fields" in feedback


def test_flags_missing_all_previous_steps_for_multi_document_compare() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Jämför flera dokument i samma körning och skriv en sammanfattning.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Jämförelse",
        steps=[
            _step(
                "step_a",
                "Analysera",
                "Analysera dokument.",
                input_type=InputType.DOCUMENT,
            ),
            _step(
                "step_b",
                "Sammanfatta",
                "Skriv sammanfattning.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )
    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "all_previous_steps" in feedback


def test_flags_missing_audio_step_when_conversation_mentions_transcription() -> None:
    """Warns when audio/transcription is mentioned but no step handles audio."""
    conversation = [
        {"role": "user", "content": "Transkribera ljudinspelningen och sammanfatta."}
    ]
    spec = FlowDraftSpecCore(
        flow_name="Transkribering",
        steps=[_step("step_a", "Sammanfatta", "Sammanfatta texten.")],
    )
    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "audio" in feedback.lower() or "transcribe_only" in feedback


def test_no_audio_warning_when_spec_has_transcription_step() -> None:
    """No warning when the spec already has a proper audio step."""
    conversation = [
        {"role": "user", "content": "Transkribera ljudinspelningen och sammanfatta."}
    ]
    spec = FlowDraftSpecCore(
        flow_name="Transkribering",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Transkribera",
                assistant_spec=AssistantSpec(instructions="Transkribera."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            ),
            _step(
                "step_b",
                "Sammanfatta",
                "Sammanfatta.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )
    assert build_conversation_aware_quality_feedback(conversation, spec) is None


def test_does_not_require_template_fill_after_conversation_shifts_to_pdf_summary() -> (
    None
):
    conversation = [
        {
            "role": "user",
            "content": (
                "Jag vill ha ett flöde som transkriberar samtal och sammanfattar "
                "och sedan fyller i en pdf mall med transkriberingen."
            ),
        },
        {
            "role": "user",
            "content": "ja exakt transkribera först men sedan ska jag få ut en pdf sammanfattning",
            "metadata": {
                "question_answer": {
                    "question_id": "final_output_mode",
                    "selected_values": ["pdf_document"],
                }
            },
        },
    ]
    spec = FlowDraftSpecCore(
        flow_name="Samtalssammanfattning",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Transkribera samtal",
                assistant_spec=AssistantSpec(instructions="Transkribera ljudfilen."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Skapa PDF-sammanfattning",
                assistant_spec=AssistantSpec(
                    instructions="Skriv en strukturerad PDF-sammanfattning."
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.PDF,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)

    assert feedback is None or "template_fill" not in feedback


def test_still_requires_template_fill_for_explicit_docx_template_request() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Skapa ett Word-dokument från en mall med fält från analysen.",
            "metadata": {
                "question_answer": {
                    "question_id": "final_output_mode",
                    "selected_values": ["docx_document"],
                }
            },
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Mallstyrd DOCX",
        steps=[
            _step(
                "step_a",
                "Extrahera innehåll",
                "Analysera underlaget.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                },
            ),
            _step(
                "step_b",
                "Skriv dokument",
                "Skriv ett DOCX-dokument.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.DOCX,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)

    assert feedback is not None
    assert "template_fill" in feedback


def test_quality_feedback_prefers_confirmed_docx_output_over_pdf_input_mentions() -> (
    None
):
    conversation = [
        {
            "role": "user",
            "content": (
                "Bygg ett flöde som tar ett uppladdat PDF-dokument och genererar en DOCX-rapport."
            ),
        },
        {
            "role": "tool",
            "content": "Requirements presented to user. Awaiting confirmation.",
            "metadata": {
                "requirements_summary": {
                    "output_description": "En genererad DOCX-rapport baserad på PDF-underlaget."
                }
            },
        },
    ]
    spec = FlowDraftSpecCore(
        flow_name="Felaktig PDF-plan",
        steps=[
            _step(
                "step_a",
                "Läs PDF",
                "Läs PDF-underlaget.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.TEXT,
            ),
            _step(
                "step_b",
                "Skriv rapport",
                "Skriv rapporten.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.PDF,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)

    assert feedback is not None
    assert "DOCX" in feedback
    assert "PDF som slutartefakt" not in feedback


def test_flags_non_terminal_docx_conversion_for_output_only_edit() -> None:
    from uuid import uuid4

    from intric.flows.flow import Flow, FlowStep

    flow = Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Transkribering och tolkning",
        steps=[
            FlowStep(
                assistant_id=uuid4(),
                step_order=1,
                user_description="Transkribera ljud",
                input_source="flow_input",
                input_type="audio",
                output_mode="transcribe_only",
                output_type="text",
                mcp_policy="inherit",
            ),
            FlowStep(
                assistant_id=uuid4(),
                step_order=2,
                user_description="Tematisk sammanfattning",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
                mcp_policy="inherit",
            ),
            FlowStep(
                assistant_id=uuid4(),
                step_order=3,
                user_description="Psykologisk och sociologisk tolkning",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="pdf",
                mcp_policy="inherit",
            ),
        ],
    )
    conversation = [
        {
            "role": "user",
            "content": "ändra så att jag får ut en word dokument istället för en pdf",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Transkribering och tolkning",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                existing_step_ref="existing_step_1",
                name="Transkribera ljud",
                assistant_spec=AssistantSpec(instructions="Transkribera ljudet."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                existing_step_ref="existing_step_2",
                name="Tematisk sammanfattning",
                assistant_spec=AssistantSpec(
                    instructions="Sammanfatta transkriptionen."
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.TEMPLATE_FILL,
                output_type=OutputType.DOCX,
            ),
            StepSpec(
                plan_step_ref="step_c",
                existing_step_ref="existing_step_3",
                name="Psykologisk och sociologisk tolkning",
                assistant_spec=AssistantSpec(instructions="Skriv Word-dokumentet."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.TEMPLATE_FILL,
                output_type=OutputType.DOCX,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec, flow=flow)

    assert feedback is not None
    assert "mellanliggande" in feedback.casefold()
    assert "template_fill" in feedback


class TestCriticInvariantLoop:
    """The critic delegates to a CRITIC_INVARIANTS registry whose entries
    carry their own evidence (callable) and remediation (Swedish prose),
    rather than hard-coded substring checks in the main function body.
    Covered here: the explicit-PDF-terminal-mismatch invariant.
    """

    def test_pdf_terminal_alignment_invariant_is_registered(self) -> None:
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            CRITIC_INVARIANTS,
            CriticInvariant,
        )

        ids = [inv.id for inv in CRITIC_INVARIANTS]
        assert "pdf_terminal_output_alignment" in ids

        pdf_inv = next(
            inv
            for inv in CRITIC_INVARIANTS
            if inv.id == "pdf_terminal_output_alignment"
        )
        assert isinstance(pdf_inv, CriticInvariant)
        assert callable(pdf_inv.evidence)
        assert "PDF" in pdf_inv.remediation

    def test_render_critic_issues_fires_pdf_terminal_alignment_on_mismatch(
        self,
    ) -> None:
        """The loop runs the pdf-terminal-alignment evidence and returns its
        remediation when the user chose PDF but the terminal step does not
        output PDF."""
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            CriticContext,
            render_critic_issues,
        )
        from intric.flows.ai_builder.ai_builder_framework_policy import (
            OutputIntentResolution,
        )
        from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
            PlannerPatternSignals,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[
                _step("step_a", "Skriv rapport", "Skriv.", output_type=OutputType.TEXT)
            ],
        )
        context = CriticContext(
            spec=spec,
            flow=None,
            answer_signals={},
            text="",
            requirements_text="",
            signal_text="",
            planner_patterns=PlannerPatternSignals(),
            output_intent=OutputIntentResolution(terminal_output="pdf_document"),
            mixed_audio_doc_input=False,
        )

        issues = render_critic_issues(context)

        assert any("PDF" in issue for issue in issues)

    def test_render_critic_issues_stays_silent_when_terminal_matches(self) -> None:
        """The invariant must not fire when the terminal step already produces PDF."""
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            CriticContext,
            render_critic_issues,
        )
        from intric.flows.ai_builder.ai_builder_framework_policy import (
            OutputIntentResolution,
        )
        from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
            PlannerPatternSignals,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[
                _step(
                    "step_a",
                    "Generera PDF",
                    "Skapa PDF.",
                    output_type=OutputType.PDF,
                )
            ],
        )
        context = CriticContext(
            spec=spec,
            flow=None,
            answer_signals={},
            text="",
            requirements_text="",
            signal_text="",
            planner_patterns=PlannerPatternSignals(),
            output_intent=OutputIntentResolution(terminal_output="pdf_document"),
            mixed_audio_doc_input=False,
        )

        assert render_critic_issues(context) == []

    def test_render_critic_issues_stays_silent_without_pdf_intent(self) -> None:
        """The invariant requires explicit PDF intent; absent it, no issue fires."""
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            CriticContext,
            render_critic_issues,
        )
        from intric.flows.ai_builder.ai_builder_framework_policy import (
            OutputIntentResolution,
        )
        from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
            PlannerPatternSignals,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[_step("step_a", "Skriv", "Skriv.", output_type=OutputType.TEXT)],
        )
        context = CriticContext(
            spec=spec,
            flow=None,
            answer_signals={},
            text="",
            requirements_text="",
            signal_text="",
            planner_patterns=PlannerPatternSignals(),
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

        assert render_critic_issues(context) == []


class TestCriticInvariantRegistry:
    """The flat `CRITIC_INVARIANTS` tuple is the sole public registry.

    Ordering matters because the planner reads issues in the order the critic
    surfaces them; a regression test here pins that contract so a future
    reorder must be deliberate.
    """

    def test_critic_invariants_registered_in_stable_order(self) -> None:
        """Full flat-registry ordering lockdown. Any intentional reorder must
        update this list and justify the shift in the commit message.
        """
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            CRITIC_INVARIANTS,
        )

        assert [inv.id for inv in CRITIC_INVARIANTS] == [
            "runtime_metadata_requires_form_fields",
            "sectioned_form_intake_requires_form_fields",
            "rich_workflow_requires_form_fields",
            "rich_workflow_requires_json_contract_step",
            "rich_workflow_requires_multiple_steps",
            "pdf_terminal_output_alignment",
            "docx_terminal_output_alignment",
            "non_terminal_step_document_conversion_forbidden",
            "non_terminal_step_template_fill_forbidden",
            "structured_extraction_requires_json_contract_step",
            "explicit_json_contract_request_without_step",
            "standalone_audio_requires_transcription_step",
            "field_reuse_requires_input_bindings",
            "multi_document_compare_requires_all_previous_steps",
            "template_fill_docx_requires_template_fill_step",
            "generated_docx_rejects_template_fill",
            "mixed_audio_doc_rejects_file_degradation",
            "mixed_audio_doc_rejects_pseudo_transcription",
            "mixed_audio_doc_requires_real_transcription_step",
        ]

    def test_render_critic_issues_accepts_custom_invariant_subset(self) -> None:
        """`render_critic_issues` evaluates whatever tuple is passed via
        `invariants=`; callers can build their own subset without relying on
        pre-defined cluster tuples.
        """
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            CRITIC_INVARIANTS,
            CriticContext,
            render_critic_issues,
        )
        from intric.flows.ai_builder.ai_builder_framework_policy import (
            OutputIntentResolution,
        )
        from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
            PlannerPatternSignals,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[
                _step(
                    "step_a",
                    "Skriv rapport",
                    "Skriv.",
                    output_type=OutputType.TEXT,
                )
            ],
        )
        context = CriticContext(
            spec=spec,
            flow=None,
            answer_signals={},
            text="",
            requirements_text="",
            signal_text="",
            planner_patterns=PlannerPatternSignals(),
            output_intent=OutputIntentResolution(
                terminal_output="docx_document",
                docx_output_mode="template_fill_docx",
            ),
            mixed_audio_doc_input=False,
        )
        template_fill_only = tuple(
            inv
            for inv in CRITIC_INVARIANTS
            if inv.id
            in {
                "template_fill_docx_requires_template_fill_step",
                "generated_docx_rejects_template_fill",
            }
        )

        default_issues = render_critic_issues(context)
        filtered_issues = render_critic_issues(context, invariants=template_fill_only)

        assert any("DOCX som slutartefakt" in issue for issue in default_issues)
        assert any("template_fill" in issue for issue in default_issues)
        assert filtered_issues == [
            issue for issue in default_issues if "template_fill" in issue
        ]

    def test_public_helper_importable_from_invariants(self) -> None:
        """`has_json_contract_step` stays public because external callers can
        reuse the same semantics when composing their own invariants.
        """
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            has_json_contract_step,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[_step("step_a", "Skriv", "Skriv.", output_type=OutputType.TEXT)],
        )

        assert has_json_contract_step(spec) is False
