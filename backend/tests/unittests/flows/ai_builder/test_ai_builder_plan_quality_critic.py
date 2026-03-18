from __future__ import annotations

from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    OutputMode,
    InputSource,
    InputType,
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
    output_contract: dict | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        name=name,
        assistant_spec=AssistantSpec(instructions=instructions),
        input_source=input_source,
        input_type=input_type,
        output_type=output_type,
        output_contract=output_contract,
    )


def test_flags_missing_form_fields_when_runtime_metadata_was_requested() -> None:
    conversation = [{
        "role": "user",
        "content": "Add basic metadata",
        "metadata": {
            "question_answer": {
                "question_id": "runtime_metadata_fields",
                "selected_values": ["basic_case_metadata"],
            }
        },
    }]
    spec = FlowDraftSpecCore(
        flow_name="Kommunanalys",
        steps=[
            _step(
                "step_a",
                "Analysera dokument",
                "Sammanfatta kommunärendet.",
                input_type=InputType.DOCUMENT,
            )
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "form_fields" in feedback


def test_flags_output_mismatch_against_explicit_pdf_choice() -> None:
    conversation = [{
        "role": "user",
        "content": "PDF document",
        "metadata": {
            "question_answer": {
                "question_id": "final_output_mode",
                "selected_values": ["pdf_document"],
            }
        },
    }]
    spec = FlowDraftSpecCore(
        flow_name="Rapport",
        steps=[_step("step_a", "Skriv rapport", "Skriv en rapport.", output_type=OutputType.TEXT)],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "PDF" in feedback


def test_flags_missing_structured_extraction_when_user_asked_for_structured_fields() -> None:
    conversation = [{
        "role": "user",
        "content": (
            "Flödet ska extrahera viktiga fakta, risker, möjligheter och rekommendationer "
            "och använda strukturerad data där det förbättrar kvaliteten."
        ),
    }]
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
    conversation = [{"role": "user", "content": "Summarize one uploaded document as plain text."}]
    spec = FlowDraftSpecCore(
        flow_name="Kort sammanfattning",
        steps=[_step("step_a", "Sammanfatta", "Skriv en kort sammanfattning.")],
    )

    assert build_conversation_aware_quality_feedback(conversation, spec) is None


def test_flags_edit_plan_that_fakes_audio_transcription_by_downgrading_to_generic_file() -> None:
    from intric.flows.flow import Flow, FlowStep
    from uuid import uuid4

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
    conversation = [{
        "role": "user",
        "content": (
            "Behåll samma flöde men lägg till ljudfiler och transkribera samtalet först, "
            "och skicka sedan in dokument som vanligt. Jag vill fortfarande ha PDF ut."
        ),
    }]
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
    assert "input_type=\"file\"" in feedback
    assert "transkriberingssteg" in feedback
    assert "flow_input" in feedback


def test_allows_audio_first_edit_when_plan_uses_real_transcription_step() -> None:
    from intric.flows.flow import Flow, FlowStep
    from uuid import uuid4

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
    conversation = [{
        "role": "user",
        "content": "Byt till ljud som primär indata och transkribera först. Behåll PDF ut.",
        "metadata": {
            "question_answer": {
                "question_id": "flow_input_architecture",
                "selected_value": "audio_primary_input",
            }
        },
    }]
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
                assistant_spec=AssistantSpec(instructions="Analysera transkriberingen."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.PDF,
            ),
        ],
    )

    assert build_conversation_aware_quality_feedback(conversation, spec, flow=flow) is None


# ── R7: Anti-over-structuring guardrail ──────────────────────────────────


def test_anti_over_structuring_simple_summary_no_json_warning() -> None:
    """R7: Simple summary -> text output, NO JSON warning."""
    conversation = [{"role": "user", "content": "Sammanfatta dokument som text."}]
    spec = FlowDraftSpecCore(
        flow_name="Sammanfattning",
        steps=[_step("step_a", "Sammanfatta", "Skriv en kort sammanfattning.", output_type=OutputType.TEXT)],
    )
    assert build_conversation_aware_quality_feedback(conversation, spec) is None


def test_flags_missing_json_contract_when_user_wants_structured_extraction() -> None:
    """Warns when conversation explicitly asks for JSON extraction but spec has none."""
    conversation = [{"role": "user", "content": "Extrahera fält som JSON och skicka vidare till nästa steg."}]
    spec = FlowDraftSpecCore(
        flow_name="Extraktion",
        steps=[
            _step("step_a", "Extrahera", "Extrahera data.", input_type=InputType.DOCUMENT),
            _step("step_b", "Rapport", "Skriv rapport.", input_source=InputSource.PREVIOUS_STEP),
        ],
    )
    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "json" in feedback.lower()


def test_no_json_warning_when_spec_already_has_json_step() -> None:
    """No warning when the spec already has a JSON contract step."""
    conversation = [{"role": "user", "content": "Extrahera fält som JSON och skicka vidare."}]
    spec = FlowDraftSpecCore(
        flow_name="Extraktion",
        steps=[
            _step(
                "step_a", "Extrahera", "Extrahera.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_contract={"type": "object", "properties": {"risk": {"type": "string"}}},
            ),
            _step("step_b", "Rapport", "Skriv rapport.", input_source=InputSource.PREVIOUS_STEP),
        ],
    )
    assert build_conversation_aware_quality_feedback(conversation, spec) is None


def test_flags_missing_input_bindings_for_field_reuse() -> None:
    conversation = [{
        "role": "user",
        "content": "Extrahera fält som JSON och använd de specifika fälten i nästa steg.",
    }]
    spec = FlowDraftSpecCore(
        flow_name="Fältåteranvändning",
        steps=[
            _step(
                "step_a",
                "Extrahera",
                "Extrahera.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_contract={"type": "object", "properties": {"risk": {"type": "string"}}},
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
    assert "input_bindings" in feedback


def test_flags_missing_all_previous_steps_for_multi_document_compare() -> None:
    conversation = [{
        "role": "user",
        "content": "Jämför flera dokument i samma körning och skriv en sammanfattning.",
    }]
    spec = FlowDraftSpecCore(
        flow_name="Jämförelse",
        steps=[
            _step("step_a", "Analysera", "Analysera dokument.", input_type=InputType.DOCUMENT),
            _step("step_b", "Sammanfatta", "Skriv sammanfattning.", input_source=InputSource.PREVIOUS_STEP),
        ],
    )
    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "all_previous_steps" in feedback


def test_flags_missing_audio_step_when_conversation_mentions_transcription() -> None:
    """Warns when audio/transcription is mentioned but no step handles audio."""
    conversation = [{"role": "user", "content": "Transkribera ljudinspelningen och sammanfatta."}]
    spec = FlowDraftSpecCore(
        flow_name="Transkribering",
        steps=[_step("step_a", "Sammanfatta", "Sammanfatta texten.")],
    )
    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "audio" in feedback.lower() or "transcribe_only" in feedback


def test_no_audio_warning_when_spec_has_transcription_step() -> None:
    """No warning when the spec already has a proper audio step."""
    conversation = [{"role": "user", "content": "Transkribera ljudinspelningen och sammanfatta."}]
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
            _step("step_b", "Sammanfatta", "Sammanfatta.", input_source=InputSource.PREVIOUS_STEP),
        ],
    )
    assert build_conversation_aware_quality_feedback(conversation, spec) is None


def test_does_not_require_template_fill_after_conversation_shifts_to_pdf_summary() -> None:
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
                assistant_spec=AssistantSpec(instructions="Skriv en strukturerad PDF-sammanfattning."),
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
                output_contract={"type": "object", "properties": {"summary": {"type": "string"}}},
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
