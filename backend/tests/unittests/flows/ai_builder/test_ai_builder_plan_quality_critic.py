from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from intric.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from intric.flows.ai_builder.ai_builder_critic_invariants import (
    CRITIC_INVARIANTS,
    enforce_architecture_critic_invariants,
    evaluate_critic_invariants,
)
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
    build_conversation_critic_context,
    build_quality_feedback_from_critic_context,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)

if TYPE_CHECKING:
    from intric.flows.ai_builder.ai_builder_critic_invariants import CriticContext
    from intric.flows.ai_builder.ai_builder_input_architecture_policy import (
        PrimaryRuntimeInput,
    )
    from intric.flows.ai_builder.planning_state import AggregationIntent


EXPECTED_CRITIC_INVARIANT_KINDS = {
    "runtime_metadata_requires_form_fields": "semantic",
    "sectioned_form_intake_requires_form_fields": "semantic",
    "rich_workflow_requires_form_fields": "semantic",
    "rich_workflow_requires_json_contract_step": "semantic",
    "rich_workflow_requires_multiple_steps": "semantic",
    "pdf_terminal_output_alignment": "architecture",
    "docx_terminal_output_alignment": "architecture",
    "non_terminal_step_document_conversion_forbidden": "architecture",
    "non_terminal_step_template_fill_forbidden": "architecture",
    "structured_extraction_requires_json_contract_step": "semantic",
    "explicit_json_contract_request_without_step": "semantic",
    "standalone_audio_requires_transcription_step": "architecture",
    "field_reuse_requires_input_bindings": "semantic",
    "multi_document_compare_requires_all_previous_steps": "architecture",
    "simple_text_transform_must_remain_single_step": "semantic",
    "mcp_selection_requires_semantic_support": "semantic",
    "json_input_rejects_all_previous_steps_source": "architecture",
    "prefer_targeted_underlag_over_all_previous_steps": "semantic",
    "final_text_step_must_reference_relevant_structured_outputs": "semantic",
    "form_fields_declared_must_be_referenced": "semantic",
    "template_fill_docx_requires_template_fill_step": "architecture",
    "generated_docx_rejects_template_fill": "architecture",
    "mixed_audio_doc_rejects_file_degradation": "architecture",
    "mixed_audio_doc_rejects_pseudo_transcription": "architecture",
    "mixed_audio_doc_requires_real_transcription_step": "architecture",
}


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


def _pdf_mismatch_context() -> "CriticContext":
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
    return build_conversation_critic_context(conversation, spec)


def test_critic_invariant_registry_has_stable_kind_map() -> None:
    assert {invariant.id: invariant.kind for invariant in CRITIC_INVARIANTS} == (
        EXPECTED_CRITIC_INVARIANT_KINDS
    )


def test_evaluate_critic_invariants_returns_issue_metadata() -> None:
    issues = evaluate_critic_invariants(_pdf_mismatch_context())

    assert [(issue.id, issue.kind) for issue in issues] == [
        ("pdf_terminal_output_alignment", "architecture")
    ]
    assert "PDF" in issues[0].remediation


def test_enforce_architecture_critic_invariants_raises_typed_error() -> None:
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        enforce_architecture_critic_invariants(_pdf_mismatch_context())

    assert exc_info.value.public_code == "architecture_critic_invariant_failed"
    assert (
        exc_info.value.log_context["critic_issue_ids"]
        == "pdf_terminal_output_alignment"
    )


def test_quality_feedback_from_context_can_exclude_architecture_issues() -> None:
    context = _pdf_mismatch_context()

    assert (
        build_quality_feedback_from_critic_context(
            context,
            include_architecture=False,
        )
        is None
    )
    assert (
        build_quality_feedback_from_critic_context(
            context,
            include_architecture=True,
        )
        is not None
    )


def test_quality_feedback_from_context_keeps_semantic_issues() -> None:
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
        flow_name="Dokumentanalys",
        steps=[
            _step(
                "step_a",
                "Analysera dokument",
                "Sammanfatta ärendet.",
                input_type=InputType.DOCUMENT,
            )
        ],
    )
    context = build_conversation_critic_context(conversation, spec)

    feedback = build_quality_feedback_from_critic_context(
        context,
        include_architecture=False,
    )

    assert feedback is not None
    assert "form_fields" in feedback


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
        flow_name="Dokumentanalys",
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


def test_no_input_fields_instruction_does_not_request_runtime_form_fields() -> None:
    conversation = [
        {
            "role": "user",
            "content": (
                "Jag vill bygga ett flöde där användaren skickar in mötesljud, "
                "flödet transkriberar ljudet och skapar en Word-rapport med "
                "rubriker. Inmatningsfält behövs inte."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Mötesrapport",
        steps=[
            _step(
                "step_a",
                "Transkribera ljud",
                "Transkribera mötesljudet.",
                input_type=InputType.AUDIO,
            ),
            _step(
                "step_b",
                "Skapa Word-rapport",
                "Skapa Word-rapporten från transkriptionen.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.DOCX,
            ),
        ],
    )
    context = build_conversation_critic_context(conversation, spec)

    issue_ids = {issue.id for issue in evaluate_critic_invariants(context)}

    assert "runtime_metadata_requires_form_fields" not in issue_ids
    assert "rich_workflow_requires_form_fields" not in issue_ids


def test_flags_unrelated_mcp_selection_when_requested_mcp_is_unavailable() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "svelte-server",
                "name": "Svelte mcp",
                "description": "Developer documentation helpers for Svelte apps.",
                "tools": [
                    {
                        "id": "svelte-docs",
                        "name": "get-documentation",
                        "description": "Fetch Svelte documentation sections.",
                    }
                ],
            }
        ],
    )
    conversation = [
        {
            "role": "user",
            "content": (
                "Bygg ett flöde som använder Time MCP för att hämta aktuell tid "
                "och konvertera den till Europe/Stockholm."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Konvertera tid via Time MCP",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Hämta aktuell tid via Time MCP",
                assistant_spec=AssistantSpec(
                    instructions="Hämta aktuell tid för angiven tidszon.",
                    mcp_server_refs=["svelte-server"],
                    mcp_tool_refs=["svelte-docs"],
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
            )
        ],
    )

    feedback = build_conversation_aware_quality_feedback(
        conversation,
        spec,
        resource_catalog=catalog,
    )

    assert feedback is not None
    assert "Planen hänvisar till MCP" in feedback
    assert "fråga om förtydligande" in feedback


def test_flags_named_mcp_step_without_attached_mcp_refs() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "svelte-server",
                "name": "Svelte mcp",
                "tools": [{"id": "svelte-docs", "name": "get-documentation"}],
            }
        ],
    )
    conversation = [
        {
            "role": "user",
            "content": "Använd Time MCP för att hämta aktuell tid.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Tid via Time MCP",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Hämta aktuell tid via Time MCP",
                assistant_spec=AssistantSpec(
                    instructions="Hämta aktuell tid via Time MCP.",
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
            )
        ],
    )

    feedback = build_conversation_aware_quality_feedback(
        conversation,
        spec,
        resource_catalog=catalog,
    )

    assert feedback is not None
    assert "Planen hänvisar till MCP" in feedback


def test_accepts_mcp_selection_when_resource_metadata_matches_step_intent() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "description": "Kan hämta tiden och konvertera tidszoner.",
                "tools": [
                    {
                        "id": "current-time",
                        "name": "get_current_time",
                        "description": "Get current time in a specific timezone.",
                    }
                ],
            }
        ],
    )
    conversation = [
        {
            "role": "user",
            "content": (
                "Bygg ett flöde som använder Time MCP för att hämta aktuell tid "
                "och konvertera den till Europe/Stockholm."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Konvertera tid via Time MCP",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Hämta aktuell tid via Time MCP",
                assistant_spec=AssistantSpec(
                    instructions="Hämta aktuell tid för angiven tidszon.",
                    mcp_server_refs=["time-server"],
                    mcp_tool_refs=["current-time"],
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
            )
        ],
    )

    assert (
        build_conversation_aware_quality_feedback(
            conversation,
            spec,
            resource_catalog=catalog,
        )
        is None
    )


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
                (
                    "Sammanställ sektionerna {{ planering_och_halsa }} "
                    "och {{ tidigare_insatser }} till ett DOCX."
                ),
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
        flow_name="Dokumentanalys",
        steps=[
            _step(
                "step_a",
                "Läs dokument",
                "Läs dokumentet och skriv en lång text.",
                input_type=InputType.DOCUMENT,
            ),
            _step(
                "step_b",
                "Skriv slutrapport",
                "Skriv en slutrapport baserat på föregående steg.",
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


def test_flags_direct_text_transform_with_unrequested_json_and_steps() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Översätt den här meningen till engelska: Vi ses imorgon.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Översättning",
        steps=[
            _step(
                "step_a",
                "Analysera språk",
                "Identifiera språk och ton.",
                output_type=OutputType.JSON,
                output_contract={"type": "object", "properties": {}},
            ),
            _step(
                "step_b",
                "Översätt",
                "Översätt till engelska.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
            ),
        ],
    )

    issues = evaluate_critic_invariants(
        build_conversation_critic_context(conversation, spec)
    )

    assert [
        issue.id
        for issue in issues
        if issue.id == "simple_text_transform_must_remain_single_step"
    ] == ["simple_text_transform_must_remain_single_step"]


def test_direct_text_transform_accepts_single_text_step() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Translate this sentence to English: Vi ses imorgon.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Translate sentence",
        steps=[_step("step_a", "Translate", "Translate the supplied text to English.")],
    )

    assert build_conversation_aware_quality_feedback(conversation, spec) is None


def test_direct_text_transform_restraint_does_not_collapse_quality_chain() -> None:
    conversation = [
        {
            "role": "user",
            "content": (
                "Translate the paragraph, let a separate critique step review "
                "clarity, and write a final version using the critique."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Reviewed translation",
        steps=[
            _step("step_a", "Translate", "Translate the paragraph."),
            _step(
                "step_b",
                "Critique",
                "Review clarity and factuality.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            _step(
                "step_c",
                "Final version",
                "Revise using the critique.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )

    issues = evaluate_critic_invariants(
        build_conversation_critic_context(conversation, spec)
    )

    assert not any(
        issue.id == "simple_text_transform_must_remain_single_step" for issue in issues
    )


def test_direct_text_transform_restraint_ignores_form_field_driven_transform() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Translate the text provided in the runtime input field target_text.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Translate runtime text",
        form_fields=[
            FormFieldSpec(
                name="target_text",
                label="Target text",
                type="text",
            )
        ],
        steps=[_step("step_a", "Translate", "Translate the target_text value.")],
    )

    issues = evaluate_critic_invariants(
        build_conversation_critic_context(conversation, spec)
    )

    assert not any(
        issue.id == "simple_text_transform_must_remain_single_step" for issue in issues
    )


def test_direct_text_transform_restraint_applies_in_edit_context() -> None:
    from uuid import uuid4

    from intric.flows.flow import Flow, FlowStep

    flow = Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Translate text",
        steps=[
            FlowStep(
                assistant_id=uuid4(),
                step_order=1,
                user_description="Translate text",
                input_source="flow_input",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
                mcp_policy="inherit",
            )
        ],
    )
    conversation = [
        {
            "role": "user",
            "content": "Ändra flödet så att det översätter meningen till franska.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Translate text",
        steps=[
            _step(
                "step_a",
                "Analysera språk",
                "Identifiera språk innan översättning.",
                output_type=OutputType.JSON,
                output_contract={"type": "object", "properties": {}},
            ),
            _step(
                "step_b",
                "Translate",
                "Translate to French.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
            ),
        ],
    )

    issues = evaluate_critic_invariants(
        build_conversation_critic_context(conversation, spec, flow=flow)
    )

    assert any(
        issue.id == "simple_text_transform_must_remain_single_step" for issue in issues
    )


def test_flags_edit_plan_that_fakes_audio_transcription_by_downgrading_to_generic_file() -> (
    None
):
    from uuid import uuid4

    from intric.flows.flow import Flow, FlowStep

    flow = Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Dokumentanalys",
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
        flow_name="Dokumentanalys",
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
        name="Dokumentanalys",
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
        flow_name="Dokumentanalys",
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
    feedback = build_conversation_aware_quality_feedback(
        conversation,
        spec,
        aggregation_intent="compare",
    )
    assert feedback is not None
    assert "all_previous_steps" in feedback


def test_does_not_infer_fan_in_from_conversation_words_without_architecture() -> None:
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

    assert build_conversation_aware_quality_feedback(conversation, spec) is None


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


class TestJsonInputRejectsAllPreviousStepsSourceInvariant:
    """When any step declares `input_type=json` with
    `input_source=all_previous_steps`, the critic must surface a remediation
    before the validator catches it. The concatenation the runtime performs on
    `all_previous_steps` produces plain text, which is not valid JSON, so this
    combination cannot run under any circumstance.
    """

    def test_invariant_is_registered(self) -> None:
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            CRITIC_INVARIANTS,
            CriticInvariant,
        )

        ids = [inv.id for inv in CRITIC_INVARIANTS]
        assert "json_input_rejects_all_previous_steps_source" in ids
        inv = next(
            item
            for item in CRITIC_INVARIANTS
            if item.id == "json_input_rejects_all_previous_steps_source"
        )
        assert isinstance(inv, CriticInvariant)
        assert callable(inv.evidence)
        assert "all_previous_steps" in inv.remediation
        assert "json" in inv.remediation.casefold()

    def test_render_critic_issues_fires_on_json_all_previous_steps_combo(
        self,
    ) -> None:
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
            flow_name="Sammanställning",
            steps=[
                _step(
                    "step_a",
                    "Hämta struktur",
                    "Läs struktur.",
                    input_type=InputType.DOCUMENT,
                    output_type=OutputType.JSON,
                ),
                _step(
                    "step_b",
                    "Sammanfatta",
                    "Sammanfatta tidigare JSON.",
                    input_source=InputSource.ALL_PREVIOUS_STEPS,
                    input_type=InputType.JSON,
                    output_type=OutputType.TEXT,
                ),
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
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

        issues = render_critic_issues(context)

        assert any("all_previous_steps" in issue for issue in issues)
        assert any("json" in issue.casefold() for issue in issues)

    def test_render_critic_issues_silent_when_json_step_uses_previous_step(
        self,
    ) -> None:
        """`input_type=json` with `input_source=previous_step` is the sanctioned
        alternative and must not trigger the invariant."""
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
            flow_name="Sammanställning",
            steps=[
                _step(
                    "step_a",
                    "Strukturera",
                    "Producera JSON.",
                    input_type=InputType.DOCUMENT,
                    output_type=OutputType.JSON,
                ),
                _step(
                    "step_b",
                    "Sammanfatta",
                    "Sammanfatta JSON.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.JSON,
                    output_type=OutputType.TEXT,
                ),
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
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

        assert render_critic_issues(context) == []

    def test_render_critic_issues_silent_when_text_step_uses_all_previous_steps(
        self,
    ) -> None:
        """`input_type=text` with `input_source=all_previous_steps` is legal
        when prior steps are also text — concatenation is the only available
        composition. The targeted-underlag invariant in
        `TestPreferTargetedUnderlagInvariant` only fires when prior steps
        emit structured JSON the final step could reference instead."""
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
            flow_name="Sammanställning",
            steps=[
                _step(
                    "step_a",
                    "Analysera",
                    "Analysera dokument.",
                    input_type=InputType.DOCUMENT,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_b",
                    "Sammanfatta",
                    "Sammanfatta alla tidigare steg.",
                    input_source=InputSource.ALL_PREVIOUS_STEPS,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
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
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

        assert render_critic_issues(context) == []


class TestPreferTargetedUnderlagInvariant:
    """A text-typed final step that reads `input_source=all_previous_steps`
    when prior steps emit structured JSON should instead read
    `previous_step` and compose its underlag explicitly via
    `{{ step_a.output.structured.field }}` references.

    `all_previous_steps` concatenates every prior step's text, monotonically
    inflating tokens with step count — for a 6-section JSON-emitting flow
    that is ~50k tokens of prompt against the final step before the
    instructions even begin. Targeted underlag scopes the input to the
    fields the final step actually consumes, preserving cross-section
    coherence without paying envelope cost for content the step never
    references.

    Suppression: when `aggregation_intent` is `aggregate` or `compare`,
    the existing `multi_document_compare_requires_all_previous_steps`
    invariant correctly demands `all_previous_steps`; the targeted-
    underlag rule must defer to it. Soft-cap at 6 prior content steps —
    beyond that the underlag template itself becomes unwieldy and the
    diagnostic stops being better than concatenation.
    """

    def test_invariant_is_registered(self) -> None:
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            CRITIC_INVARIANTS,
            CriticInvariant,
        )

        ids = [inv.id for inv in CRITIC_INVARIANTS]
        assert "prefer_targeted_underlag_over_all_previous_steps" in ids
        inv = next(
            item
            for item in CRITIC_INVARIANTS
            if item.id == "prefer_targeted_underlag_over_all_previous_steps"
        )
        assert isinstance(inv, CriticInvariant)
        assert callable(inv.evidence)
        assert "all_previous_steps" in inv.remediation
        assert "uses_previous_fields" in inv.remediation

    def test_render_critic_issues_fires_on_text_terminal_after_structured_priors(
        self,
    ) -> None:
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
            flow_name="Strukturerad rapport",
            steps=[
                _step(
                    "step_a",
                    "Extrahera A",
                    "Extrahera fakta som JSON.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Extrahera B",
                    "Extrahera fakta som JSON.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"detail": {"type": "string"}},
                    },
                ),
                _step(
                    "step_c",
                    "Skriv rapport",
                    "Sammanställ en rapport.",
                    input_source=InputSource.ALL_PREVIOUS_STEPS,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
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
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

        issues = render_critic_issues(context)

        assert any("uses_previous_fields" in issue for issue in issues)
        assert any("all_previous_steps" in issue for issue in issues)

    def test_render_critic_issues_silent_when_priors_are_text(
        self,
    ) -> None:
        """When prior content steps emit plain text, there are no
        structured fields to reference. `all_previous_steps` is the
        only composition path and the invariant must not fire."""

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
            flow_name="Texter ihop",
            steps=[
                _step(
                    "step_a",
                    "Skriv del 1",
                    "Skriv del 1.",
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_b",
                    "Skriv del 2",
                    "Skriv del 2.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_c",
                    "Sammanställ",
                    "Sammanställ båda.",
                    input_source=InputSource.ALL_PREVIOUS_STEPS,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
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
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

        ids = {
            issue
            for issue in render_critic_issues(context)
            if "uses_previous_fields" in issue
        }
        assert ids == set()

    def test_render_critic_issues_silent_when_aggregate_intent(
        self,
    ) -> None:
        """`multi_document_compare_requires_all_previous_steps` owns the
        aggregate / compare cases. The targeted-underlag rule must
        defer rather than contradict."""

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
            flow_name="Jämförelse",
            steps=[
                _step(
                    "step_a",
                    "Extrahera",
                    "Extrahera fakta.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"x": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Sammanställ",
                    "Sammanställ alla.",
                    input_source=InputSource.ALL_PREVIOUS_STEPS,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
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
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
            aggregation_intent="compare",
        )

        ids = {
            issue
            for issue in render_critic_issues(context)
            if "prefer" in issue.lower() and "targeted" in issue.lower()
        }
        assert ids == set()

    def test_render_critic_issues_silent_when_too_many_text_priors(
        self,
    ) -> None:
        # Pins 78bf7994: JSON priors do not count against the text-prior cap.

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

        text_priors = [
            _step(
                f"step_{chr(ord('a') + idx)}",
                f"Skriv del {idx + 1}",
                "Skriv del.",
                input_source=InputSource.PREVIOUS_STEP
                if idx > 0
                else InputSource.FLOW_INPUT,
                output_type=OutputType.TEXT,
            )
            for idx in range(7)
        ]
        json_anchor = _step(
            "step_h",
            "Extrahera fakta",
            "Extrahera fakta.",
            input_source=InputSource.PREVIOUS_STEP,
            output_type=OutputType.JSON,
            output_contract={
                "type": "object",
                "properties": {"title": {"type": "string"}},
            },
        )
        spec = FlowDraftSpecCore(
            flow_name="Många textsteg",
            steps=[
                *text_priors,
                json_anchor,
                _step(
                    "step_i",
                    "Sammanställ",
                    "Sammanställ allt.",
                    input_source=InputSource.ALL_PREVIOUS_STEPS,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
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
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

        ids = {
            issue
            for issue in render_critic_issues(context)
            if "uses_previous_fields" in issue
        }
        assert ids == set()

    def test_render_critic_issues_fires_when_many_json_priors_under_text_cap(
        self,
    ) -> None:
        # Pins 78bf7994: many JSON priors still trigger targeted-underlag.

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

        transcription = _step(
            "step_a",
            "Transkribera ljudet",
            "Transkribera ljudet.",
            input_type=InputType.AUDIO,
            output_type=OutputType.TEXT,
            output_mode=OutputMode.TRANSCRIBE_ONLY,
        )
        json_priors = [
            _step(
                f"step_{chr(ord('b') + idx)}",
                f"Extrahera del {idx + 1}",
                "Extrahera del.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {f"field_{idx}": {"type": "string"}},
                },
            )
            for idx in range(8)
        ]
        spec = FlowDraftSpecCore(
            flow_name="Många JSON-extraktioner",
            steps=[
                transcription,
                *json_priors,
                _step(
                    "step_j",
                    "Sammanställ",
                    "Sammanställ allt.",
                    input_source=InputSource.ALL_PREVIOUS_STEPS,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
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
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

        issues = render_critic_issues(context)
        assert any("uses_previous_fields" in issue for issue in issues), (
            "rule must fire when many JSON priors are available even past the "
            "old all-priors cap; structured field refs scale, body coalesce does not"
        )

    def test_render_critic_issues_targets_composer_step_before_renderer(
        self,
    ) -> None:
        """When the final step is a template_fill / DOCX / PDF renderer,
        the actual content composer is the step before it. The rule must
        evaluate the composer's input wiring, not the renderer's — a
        renderer reading `previous_step` is structurally fine, but the
        composer behind it can still be over-fanning into all_previous_steps.
        """

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
            flow_name="Rapport med template-fill DOCX",
            steps=[
                _step(
                    "step_a",
                    "Extrahera A",
                    "Extrahera fakta som JSON.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Extrahera B",
                    "Extrahera fakta som JSON.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"detail": {"type": "string"}},
                    },
                ),
                _step(
                    "step_c",
                    "Skriv rapport",
                    "Sammanställ en rapport.",
                    input_source=InputSource.ALL_PREVIOUS_STEPS,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_d",
                    "Fyll mall",
                    "Fyll DOCX-mallen.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.DOCX,
                    output_mode=OutputMode.TEMPLATE_FILL,
                ),
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
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

        issues = render_critic_issues(context)

        targeted_issue = next(
            (issue for issue in issues if "uses_previous_fields" in issue),
            None,
        )
        assert targeted_issue is not None, (
            "rule must look past the template_fill renderer and flag the "
            "composer step (step_c) reading all_previous_steps"
        )
        assert "komponerande" in targeted_issue, (
            "remediation must address the composer step, not falsely claim "
            "the terminal renderer itself has all_previous_steps"
        )
        assert "Det sista steget" not in targeted_issue, (
            "old wording referred to the final step; the rule now evaluates "
            "the composer behind a renderer terminal — wording must follow"
        )

    def test_render_critic_issues_targets_nonterminal_body_composer_before_review(
        self,
    ) -> None:
        """A body composer followed by a review step is still eligible for the
        targeted-underlag invariant. Restricting the rule to the last
        compositional step misses the C2 live-eval shape.
        """

        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            CriticContext,
        )
        from intric.flows.ai_builder.ai_builder_framework_policy import (
            OutputIntentResolution,
        )
        from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
            PlannerPatternSignals,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport med granskning",
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
                    "Extrahera bakgrund",
                    "Extrahera bakgrund som JSON.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"background": {"type": "string"}},
                    },
                ),
                _step(
                    "step_c",
                    "Extrahera risker",
                    "Extrahera risker som JSON.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"risks": {"type": "string"}},
                    },
                ),
                _step(
                    "step_d",
                    "Förbered rapporttext",
                    "Skriv rapporttext.",
                    input_source=InputSource.ALL_PREVIOUS_STEPS,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_e",
                    "Granska rapporttext",
                    "Granska rapporttexten.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_f",
                    "Skapa PDF",
                    "Skapa PDF.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.PDF,
                ),
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
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

        issues = evaluate_critic_invariants(context, invariants=CRITIC_INVARIANTS)
        targeted_issue = next(
            (
                issue
                for issue in issues
                if issue.id == "prefer_targeted_underlag_over_all_previous_steps"
            ),
            None,
        )
        assert targeted_issue is not None
        assert "Det sista komponerande textsteget" not in targeted_issue.remediation
        assert "Ett komponerande textsteg" in targeted_issue.remediation

    def test_render_critic_issues_silent_when_question_targets_prior_fields(
        self,
    ) -> None:
        """A spec whose composer reads `all_previous_steps` nominally but
        whose `input_bindings.question` already references prior structured
        fields via `{{ step_x.output.structured.field }}` is effectively
        using targeted underlag. The runtime context window is wide, but
        the prompt is narrow — nudging the planner to switch source would
        produce no real change. The rule stays silent."""

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
            flow_name="Effektiv targeted underlag",
            steps=[
                _step(
                    "step_a",
                    "Extrahera",
                    "Extrahera fakta.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                    },
                ),
                StepSpec(
                    plan_step_ref="step_b",
                    name="Skriv rapport",
                    assistant_spec=AssistantSpec(
                        instructions=(
                            "Skriv en rapport baserat på "
                            "{{ step_a.output.structured.summary }}."
                        ),
                    ),
                    input_source=InputSource.ALL_PREVIOUS_STEPS,
                    input_type=InputType.TEXT,
                    output_mode=OutputMode.PASS_THROUGH,
                    output_type=OutputType.TEXT,
                    input_bindings={
                        "question": (
                            "Använd sammanfattningen i "
                            "{{ step_a.output.structured.summary }} "
                            "för att skriva en rapport."
                        )
                    },
                ),
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
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

        ids = {
            issue
            for issue in render_critic_issues(context)
            if "uses_previous_fields" in issue
        }
        assert ids == set()

    @pytest.mark.parametrize(
        "question",
        [
            # Nested structured path — analyze_template walks the dotted tail
            # past `output.structured.` and only the head/order/non-empty path
            # need to validate.
            "Använd {{ step_a.output.structured.sections.introduction }} som underlag.",
            # JSON-escaped form the planner emits when authoring bindings via
            # JSON-serialized tool calls.
            ('Använd \\"{{ step_a.output.structured.summary }}\\" som rubrik.'),
        ],
    )
    def test_render_critic_issues_silent_when_question_uses_nested_or_escaped_selectors(
        self,
        question: str,
    ) -> None:
        """Targeted-underlag suppression must accept both nested structured
        paths (`...structured.sections.introduction`) and the JSON-escaped
        quote form the planner produces inside serialized tool calls — the
        canonical template parser covers both shapes."""

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
            flow_name="Targeted underlag selektorer",
            steps=[
                _step(
                    "step_a",
                    "Extrahera",
                    "Extrahera fakta.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string"},
                            "sections": {
                                "type": "object",
                                "properties": {
                                    "introduction": {"type": "string"},
                                },
                            },
                        },
                    },
                ),
                StepSpec(
                    plan_step_ref="step_b",
                    name="Skriv rapport",
                    assistant_spec=AssistantSpec(instructions="Skriv en rapport."),
                    input_source=InputSource.ALL_PREVIOUS_STEPS,
                    input_type=InputType.TEXT,
                    output_mode=OutputMode.PASS_THROUGH,
                    output_type=OutputType.TEXT,
                    input_bindings={"question": question},
                ),
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
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

        issues = [
            issue
            for issue in render_critic_issues(context)
            if "uses_previous_fields" in issue
        ]
        assert issues == []

    @pytest.mark.parametrize(
        "question",
        [
            # Future-step reference: composer is step_b (index 1); a selector
            # pointing at step_b itself or step_c does not constitute a prior
            # structured read and must NOT suppress the nudge.
            "Skriv en rapport baserat på {{ step_b.output.structured.summary }}.",
            "Skriv en rapport baserat på {{ step_c.output.structured.summary }}.",
            # Malformed selector: empty structured path (`output.structured.`
            # alone) does not target any field.
            "Skriv en rapport baserat på {{ step_a.output.structured. }}.",
            # No selector at all — plain text question.
            "Skriv en rapport.",
        ],
    )
    def test_render_critic_issues_fires_when_question_lacks_valid_prior_field_selector(
        self,
        question: str,
    ) -> None:
        """Suppression requires a *valid* selector pointing at a prior step's
        non-empty structured path. Future-step references, current-step
        references, malformed selectors, and plain text do not qualify and
        must let the nudge fire."""

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
            flow_name="Saknar giltig selektor",
            steps=[
                _step(
                    "step_a",
                    "Extrahera",
                    "Extrahera fakta.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                    },
                ),
                StepSpec(
                    plan_step_ref="step_b",
                    name="Skriv rapport",
                    assistant_spec=AssistantSpec(instructions="Skriv en rapport."),
                    input_source=InputSource.ALL_PREVIOUS_STEPS,
                    input_type=InputType.TEXT,
                    output_mode=OutputMode.PASS_THROUGH,
                    output_type=OutputType.TEXT,
                    input_bindings={"question": question},
                ),
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
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

        issues = [
            issue
            for issue in render_critic_issues(context)
            if "uses_previous_fields" in issue
        ]
        assert issues, (
            "no valid prior-structured-field selector means suppression "
            f"should not apply; question={question!r}"
        )

    def test_render_critic_issues_silent_when_final_uses_previous_step(
        self,
    ) -> None:
        """The compliant shape: `previous_step` + an underlag template
        that references prior structured fields. The invariant is the
        nudge toward this; once adopted it must stay silent."""

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
            flow_name="Selektiv sammansättning",
            steps=[
                _step(
                    "step_a",
                    "Extrahera",
                    "Extrahera fakta.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Skriv rapport",
                    "Skriv en kort rapport.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
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
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

        ids = {
            issue
            for issue in render_critic_issues(context)
            if "uses_previous_fields" in issue
        }
        assert ids == set()


_FINAL_TEXT_STEP_INVARIANT_ID = (
    "final_text_step_must_reference_relevant_structured_outputs"
)


def _final_text_step_critic_context(
    spec: FlowDraftSpecCore,
    *,
    aggregation_intent: str = "linear",
) -> "CriticContext":
    from intric.flows.ai_builder.ai_builder_critic_invariants import (
        CriticContext,
    )
    from intric.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )
    from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
        PlannerPatternSignals,
    )

    return CriticContext(
        spec=spec,
        flow=None,
        answer_signals={},
        text="",
        requirements_text="",
        signal_text="",
        planner_patterns=PlannerPatternSignals(),
        output_intent=OutputIntentResolution(terminal_output=None),
        mixed_audio_doc_input=False,
        aggregation_intent=cast("AggregationIntent", aggregation_intent),
    )


class TestFinalTextStepReferencesRelevantStructuredOutputs:
    """`final_text_step_must_reference_relevant_structured_outputs` is the
    defense-in-depth complement of `prefer_targeted_underlag_over_all_previous_steps`.

    `prefer_targeted_underlag` fires on the over-fanned shape
    (`input_source=all_previous_steps`). This rule fires on the opposite
    shape: a final text composer reading `input_source=previous_step`
    that visually only sees the most recent JSON predecessor — even
    though earlier predecessors also emit structured fields the
    composer almost certainly needs.

    Pattern: parallel multi-aspect extractions that fan-in to a single
    text rendering. Each prior step extracts a distinct structured slice
    of the source; a `previous_step` composer that does not pull
    `{{ step_n.output.structured.* }}` selectors from at least two
    of those priors is silently dropping data on the floor. The
    upstream auto-binder usually rewrites this in create-mode, but the
    invariant exists for the cases where the auto-binder cannot fire:
    edit-mode, planner-authored selectors that miss priors, or future
    create-mode shapes the auto-binder does not yet cover.

    Suppression mirrors `prefer_targeted_underlag`:
    - `aggregation_intent` in {aggregate, compare}: those flows go
      through `multi_document_compare_requires_all_previous_steps`.
    - >`TARGETED_UNDERLAG_SOFT_CAP` prior content steps: an explicit
      template stops being more legible than concatenation.
    - All priors are text-typed: there are no structured fields to
      pull, so no nudge is possible.
    - The composer's `input_bindings.question` already targets ≥2
      distinct prior structured fields: the spec is already doing the
      right thing despite the nominal `previous_step` source.
    """

    def test_invariant_is_registered(self) -> None:
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            CRITIC_INVARIANTS,
            CriticInvariant,
        )

        ids = [inv.id for inv in CRITIC_INVARIANTS]
        assert _FINAL_TEXT_STEP_INVARIANT_ID in ids
        inv = next(
            item
            for item in CRITIC_INVARIANTS
            if item.id == _FINAL_TEXT_STEP_INVARIANT_ID
        )
        assert isinstance(inv, CriticInvariant)
        assert callable(inv.evidence)
        assert "uses_previous_fields" in inv.remediation

    def test_fires_on_previous_step_composer_with_multiple_json_priors(
        self,
    ) -> None:
        """The user-reported regression: a multi-step extraction chain ends
        in a `previous_step` composer that only sees the immediate predecessor.
        The composer should read at least two priors' structured fields."""

        spec = FlowDraftSpecCore(
            flow_name="Sammanställ extraktioner",
            steps=[
                _step(
                    "step_a",
                    "Extrahera produktdata",
                    "Extrahera produktdata som JSON.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"produkt": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Extrahera kunddata",
                    "Extrahera kunddata som JSON.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"kund": {"type": "string"}},
                    },
                ),
                _step(
                    "step_c",
                    "Extrahera leveransdata",
                    "Extrahera leveransdata som JSON.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"leverans": {"type": "string"}},
                    },
                ),
                _step(
                    "step_d",
                    "Skriv sammanfattning",
                    "Skriv en kort sammanfattning.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues), (
            "rule must nudge a previous_step composer with two JSON priors "
            "to pull structured fields from earlier predecessors"
        )

    def test_silent_on_single_json_prior_refinement_chain(self) -> None:
        """The classic 2-step refinement (extract → render) only has one
        JSON prior. There is no fan-in — `previous_step` is the canonical
        shape and the rule must not fire."""

        spec = FlowDraftSpecCore(
            flow_name="Enkel raffineringskedja",
            steps=[
                _step(
                    "step_a",
                    "Extrahera fakta",
                    "Extrahera fakta som JSON.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Skriv rapport",
                    "Skriv en kort rapport.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_silent_when_question_already_targets_two_prior_structured_fields(
        self,
    ) -> None:
        """When the composer's `input_bindings.question` already references
        at least two distinct prior steps' structured fields via
        `{{ step_n.output.structured.field }}`, the spec is doing what
        the rule would suggest. The rule must stay silent."""

        spec = FlowDraftSpecCore(
            flow_name="Redan riktade selektorer",
            steps=[
                _step(
                    "step_a",
                    "Extrahera produktdata",
                    "Extrahera produktdata.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"produkt": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Extrahera kunddata",
                    "Extrahera kunddata.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"kund": {"type": "string"}},
                    },
                ),
                StepSpec(
                    plan_step_ref="step_c",
                    name="Skriv sammanfattning",
                    assistant_spec=AssistantSpec(
                        instructions="Skriv en kort sammanfattning."
                    ),
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_mode=OutputMode.PASS_THROUGH,
                    output_type=OutputType.TEXT,
                    input_bindings={
                        "question": (
                            "Använd {{ step_a.output.structured.produkt }} "
                            "och {{ step_b.output.structured.kund }} för att "
                            "skriva en kort sammanfattning."
                        )
                    },
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_fires_when_question_targets_only_one_prior_structured_field(
        self,
    ) -> None:
        """A composer that pulls a selector from only ONE prior is still
        dropping data — the rule must fire. Suppression requires ≥2
        distinct prior steps referenced."""

        spec = FlowDraftSpecCore(
            flow_name="Bara en selektor",
            steps=[
                _step(
                    "step_a",
                    "Extrahera produktdata",
                    "Extrahera produktdata.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"produkt": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Extrahera kunddata",
                    "Extrahera kunddata.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"kund": {"type": "string"}},
                    },
                ),
                StepSpec(
                    plan_step_ref="step_c",
                    name="Skriv sammanfattning",
                    assistant_spec=AssistantSpec(
                        instructions="Skriv en kort sammanfattning."
                    ),
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_mode=OutputMode.PASS_THROUGH,
                    output_type=OutputType.TEXT,
                    input_bindings={
                        "question": (
                            "Använd {{ step_b.output.structured.kund }} för att "
                            "skriva en kort sammanfattning."
                        )
                    },
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    @pytest.mark.parametrize("intent", ["aggregate", "compare"])
    def test_silent_on_aggregate_or_compare_intent(self, intent: str) -> None:
        """`multi_document_compare_requires_all_previous_steps` owns the
        aggregate / compare cases. This rule must defer rather than nudge
        toward `previous_step` against the aggregate-shape requirement."""

        spec = FlowDraftSpecCore(
            flow_name="Aggregeringsflöde",
            steps=[
                _step(
                    "step_a",
                    "Extrahera produktdata",
                    "Extrahera produktdata.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"produkt": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Extrahera kunddata",
                    "Extrahera kunddata.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"kund": {"type": "string"}},
                    },
                ),
                _step(
                    "step_c",
                    "Skriv sammanfattning",
                    "Skriv en kort sammanfattning.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(
            _final_text_step_critic_context(spec, aggregation_intent=intent)
        )

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_silent_when_priors_are_text(self) -> None:
        """Priors that emit plain text expose no structured fields. The
        composer cannot pull `{{ step_n.output.structured.* }}` from them.
        `previous_step` is the only sensible source — the rule stays silent."""

        spec = FlowDraftSpecCore(
            flow_name="Texter ihop",
            steps=[
                _step(
                    "step_a",
                    "Skriv del 1",
                    "Skriv del 1.",
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_b",
                    "Skriv del 2",
                    "Skriv del 2.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_c",
                    "Sammanställ",
                    "Sammanställ båda.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_silent_when_too_many_text_priors(self) -> None:
        # Pins 78bf7994: the under-bind rule uses the same text-prior cap.

        text_priors = [
            _step(
                f"step_{chr(ord('a') + idx)}",
                f"Skriv del {idx + 1}",
                "Skriv del.",
                input_source=InputSource.PREVIOUS_STEP
                if idx > 0
                else InputSource.FLOW_INPUT,
                output_type=OutputType.TEXT,
            )
            for idx in range(7)
        ]
        json_anchors = [
            _step(
                "step_h",
                "Extrahera fakta A",
                "Extrahera fakta.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                },
            ),
            _step(
                "step_i",
                "Extrahera fakta B",
                "Extrahera fakta.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"b": {"type": "string"}},
                },
            ),
        ]
        spec = FlowDraftSpecCore(
            flow_name="För många textpriors",
            steps=[
                *text_priors,
                *json_anchors,
                _step(
                    "step_j",
                    "Skriv sammanfattning",
                    "Skriv en kort sammanfattning.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_fires_when_many_json_priors_under_text_cap(self) -> None:
        # Pins 78bf7994: JSON-heavy chains still need structured fan-in.

        transcription = _step(
            "step_a",
            "Transkribera",
            "Transkribera ljudet.",
            input_type=InputType.AUDIO,
            output_type=OutputType.TEXT,
            output_mode=OutputMode.TRANSCRIBE_ONLY,
        )
        json_priors = [
            _step(
                f"step_{chr(ord('b') + idx)}",
                f"Extrahera del {idx + 1}",
                "Extrahera del.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {f"f_{idx}": {"type": "string"}},
                },
            )
            for idx in range(8)
        ]
        spec = FlowDraftSpecCore(
            flow_name="Många JSON-extraktioner",
            steps=[
                transcription,
                *json_priors,
                _step(
                    "step_j",
                    "Skriv sammanfattning",
                    "Skriv en kort sammanfattning.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues), (
            "rule must fire when many JSON priors are available even past the "
            "old all-priors cap; the composer is dropping fields from earlier "
            "predecessors"
        )

    def test_silent_when_input_source_is_all_previous_steps(self) -> None:
        """The over-fan shape is owned by `prefer_targeted_underlag_over_all_previous_steps`.
        This rule fires only on the under-bind shape (`previous_step` with
        ≥2 JSON priors)."""

        spec = FlowDraftSpecCore(
            flow_name="All previous steps shape",
            steps=[
                _step(
                    "step_a",
                    "Extrahera produktdata",
                    "Extrahera produktdata.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"produkt": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Extrahera kunddata",
                    "Extrahera kunddata.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"kund": {"type": "string"}},
                    },
                ),
                _step(
                    "step_c",
                    "Skriv sammanfattning",
                    "Skriv en kort sammanfattning.",
                    input_source=InputSource.ALL_PREVIOUS_STEPS,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_silent_when_terminal_is_renderer_and_composer_has_no_priors(
        self,
    ) -> None:
        """A 2-step DOCX-fill flow has the renderer as the terminal step
        but the composer is step 0 — there are no priors before it.
        The rule must not fire on this canonical 2-step shape."""

        spec = FlowDraftSpecCore(
            flow_name="DOCX-fill med en JSON-extraktion",
            steps=[
                _step(
                    "step_a",
                    "Extrahera fakta",
                    "Extrahera fakta.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Fyll mall",
                    "Fyll DOCX-mallen.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.DOCX,
                    output_mode=OutputMode.TEMPLATE_FILL,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)


class TestStandaloneAudioInvariant:
    """`standalone_audio_requires_transcription_step` fires when the slot
    classifier has resolved the runtime input to `audio` and the spec has
    no transcription step.

    The invariant defers to the slot classifier
    (`resolve_input_intent.primary_runtime_input`) instead of doing its
    own keyword scan. This keeps the architecture rule and the discovery
    layer aligned: a prompt that the slot classifier reads as text input
    (e.g. "indata: originaltranskribering") is a text flow, not a
    forgotten transcription. The user is responsible for declaring audio
    explicitly when they want the recording to enter the flow as audio
    (e.g. "ladda upp ljudfilen", "audio file upload"). When they do, the
    slot flips to `audio` and this invariant catches a missing
    transcription step.
    """

    def _build_context(
        self,
        spec: FlowDraftSpecCore,
        *,
        primary_runtime_input: str = "unknown",
        mixed_audio_doc_input: bool = False,
        text: str = "",
    ) -> "CriticContext":
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            CriticContext,
        )
        from intric.flows.ai_builder.ai_builder_framework_policy import (
            OutputIntentResolution,
        )
        from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
            PlannerPatternSignals,
        )

        return CriticContext(
            spec=spec,
            flow=None,
            answer_signals={},
            text=text,
            requirements_text="",
            signal_text="",
            planner_patterns=PlannerPatternSignals(),
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=mixed_audio_doc_input,
            primary_runtime_input=cast("PrimaryRuntimeInput", primary_runtime_input),
        )

    def test_fires_when_primary_runtime_input_is_audio_and_no_audio_step(
        self,
    ) -> None:
        issues = evaluate_critic_invariants(
            self._build_context(
                FlowDraftSpecCore(
                    flow_name="Sammanfatta möte",
                    steps=[
                        _step(
                            "step_a",
                            "Sammanfatta",
                            "Sammanfatta innehållet.",
                            input_type=InputType.TEXT,
                            output_type=OutputType.TEXT,
                        )
                    ],
                ),
                primary_runtime_input="audio",
            )
        )

        assert any(
            issue.id == "standalone_audio_requires_transcription_step"
            for issue in issues
        )

    def test_silent_when_primary_runtime_input_is_text_even_with_transcription_word(
        self,
    ) -> None:
        """Regression for the user-reported failure: a prompt whose slot
        classifier reading is "text" (e.g. "indata: originaltranskribering",
        "läs hela den transkriberade mötestexten") must NOT trigger the
        audio rule. The user has named transcribed text as their data,
        not audio as their input. Firing here would push the planner to
        graft an audio step onto a text flow and surface as
        `architecture_critic_invariant_failed` to the end user.
        """
        issues = evaluate_critic_invariants(
            self._build_context(
                FlowDraftSpecCore(
                    flow_name="Mötesrapport från transkribering",
                    steps=[
                        _step(
                            "step_a",
                            "Etablera möteskontext",
                            "Läs hela den transkriberade mötestexten.",
                            input_type=InputType.TEXT,
                            output_type=OutputType.JSON,
                            output_contract={"type": "object"},
                        ),
                        _step(
                            "step_b",
                            "Skriv mötesrapport",
                            "Skriv en strukturerad mötesrapport.",
                            input_source=InputSource.PREVIOUS_STEP,
                            input_type=InputType.TEXT,
                            output_type=OutputType.TEXT,
                        ),
                    ],
                ),
                primary_runtime_input="text",
                text=(
                    "mötesrapport från transkribering. indata: "
                    "originaltranskribering. läs hela den transkriberade "
                    "mötestexten."
                ),
            )
        )

        assert not any(
            issue.id == "standalone_audio_requires_transcription_step"
            for issue in issues
        )

    def test_silent_when_primary_runtime_input_is_unknown(self) -> None:
        """Default-state contexts (no slot resolution) must not fire.
        The invariant only acts on a positive `audio` resolution — a
        soft contract that protects every other test fixture from
        accidentally tripping the audio rule.
        """
        issues = evaluate_critic_invariants(
            self._build_context(
                FlowDraftSpecCore(
                    flow_name="Generic flow",
                    steps=[
                        _step(
                            "step_a",
                            "Sammanfatta",
                            "Sammanfatta innehållet.",
                            input_type=InputType.TEXT,
                            output_type=OutputType.TEXT,
                        )
                    ],
                ),
                primary_runtime_input="unknown",
            )
        )

        assert not any(
            issue.id == "standalone_audio_requires_transcription_step"
            for issue in issues
        )

    def test_silent_when_spec_already_has_audio_step(self) -> None:
        """An explicit audio step (`input_type=audio` or
        `output_mode=transcribe_only`) satisfies the invariant even when
        the slot classifier resolves to `audio`.
        """
        issues = evaluate_critic_invariants(
            self._build_context(
                FlowDraftSpecCore(
                    flow_name="Transkribera och sammanfatta",
                    steps=[
                        _step(
                            "step_a",
                            "Transkribera",
                            "Transkribera ljudet.",
                            input_type=InputType.AUDIO,
                            output_type=OutputType.TEXT,
                            output_mode=OutputMode.TRANSCRIBE_ONLY,
                        ),
                        _step(
                            "step_b",
                            "Sammanfatta",
                            "Sammanfatta transkriptet.",
                            input_source=InputSource.PREVIOUS_STEP,
                            input_type=InputType.TEXT,
                            output_type=OutputType.TEXT,
                        ),
                    ],
                ),
                primary_runtime_input="audio",
            )
        )

        assert not any(
            issue.id == "standalone_audio_requires_transcription_step"
            for issue in issues
        )

    def test_silent_when_mixed_audio_doc_input_handles_clarification(self) -> None:
        """Mixed audio+document prompts are handled by the dedicated
        mixed-input invariants. The standalone rule must yield to them
        rather than double-firing on the same root cause.
        """
        issues = evaluate_critic_invariants(
            self._build_context(
                FlowDraftSpecCore(
                    flow_name="Sammanfatta möte",
                    steps=[
                        _step(
                            "step_a",
                            "Sammanfatta",
                            "Sammanfatta innehållet.",
                            input_type=InputType.TEXT,
                            output_type=OutputType.TEXT,
                        )
                    ],
                ),
                primary_runtime_input="audio",
                mixed_audio_doc_input=True,
            )
        )

        assert not any(
            issue.id == "standalone_audio_requires_transcription_step"
            for issue in issues
        )

    def test_remediation_gives_planner_a_concrete_step_shape(self) -> None:
        """The original one-liner "add a dedicated transcription step"
        was too vague for the planner to converge when several
        text-processing steps already existed. The remediation must
        spell out the four required fields, the position (first step),
        and how downstream steps should consume the transcript.
        """
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            CRITIC_INVARIANTS,
        )

        inv = next(
            item
            for item in CRITIC_INVARIANTS
            if item.id == "standalone_audio_requires_transcription_step"
        )

        for required_token in (
            "audio",
            "transcribe_only",
            "flow_input",
            "previous_step",
        ):
            assert required_token in inv.remediation, (
                f"remediation missing concrete shape token: {required_token}"
            )
        assert "första steg" in inv.remediation, (
            "remediation must tell the planner WHERE to add the step "
            "(first step / position 0); without positioning the LLM "
            "tends to graft audio handling onto an existing step instead"
        )


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
            "simple_text_transform_must_remain_single_step",
            "mcp_selection_requires_semantic_support",
            "json_input_rejects_all_previous_steps_source",
            "prefer_targeted_underlag_over_all_previous_steps",
            "final_text_step_must_reference_relevant_structured_outputs",
            "form_fields_declared_must_be_referenced",
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


class TestRichWorkflowInvariants:
    """Fire/quiet coverage for the rich-workflow invariants declared at
    `ai_builder_critic_invariants.py:334/358/384`.

    The id-order lockdown in `TestCriticInvariantRegistry` pins *which*
    invariants exist; these tests pin their *behavior* — each invariant
    fires only when all of its planner-pattern signals agree AND the
    spec is missing the required structure, and stays silent the moment
    any precondition flips. The `generated_docx_without_structure` case
    exists because a user who asks for a plain generated DOCX must not
    be nagged about JSON steps or quality chains — that is the most
    common false-positive shape for these three.
    """

    def _context_with_signals(
        self,
        spec: FlowDraftSpecCore,
        *,
        rich: bool = True,
        needs_form_fields: bool = False,
        prefers_structured_intermediate: bool = False,
        prefers_quality_step: bool = False,
    ) -> CriticContext:
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            CriticContext,
        )
        from intric.flows.ai_builder.ai_builder_framework_policy import (
            OutputIntentResolution,
        )
        from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
            PlannerPatternSignals,
        )

        return CriticContext(
            spec=spec,
            flow=None,
            answer_signals={},
            text="",
            requirements_text="",
            signal_text="",
            planner_patterns=PlannerPatternSignals(
                needs_form_fields=needs_form_fields,
                prefers_structured_intermediate=prefers_structured_intermediate,
                prefers_quality_step=prefers_quality_step,
                rich_document_workflow=rich,
            ),
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

    def test_rich_workflow_requires_form_fields_fires_when_form_fields_missing(
        self,
    ) -> None:
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            render_critic_issues,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[
                _step(
                    "step_a",
                    "Analysera dokument",
                    "Läs dokumentet och skriv rapport.",
                    input_type=InputType.DOCUMENT,
                )
            ],
        )
        context = self._context_with_signals(spec, needs_form_fields=True)

        issues = render_critic_issues(context)

        assert any("form_fields" in issue for issue in issues)

    def test_rich_workflow_requires_form_fields_silent_when_form_fields_declared(
        self,
    ) -> None:
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            render_critic_issues,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            form_fields=[
                FormFieldSpec(
                    name="ansvarig_enhet", type="text", label="Ansvarig enhet"
                )
            ],
            steps=[
                _step(
                    "step_a",
                    "Analysera dokument",
                    ("Läs dokumentet och skriv rapport för {{ ansvarig_enhet }}."),
                    input_type=InputType.DOCUMENT,
                )
            ],
        )
        context = self._context_with_signals(spec, needs_form_fields=True)

        issues = render_critic_issues(context)

        assert not any(
            "formulärfält" in issue or "form_fields" in issue for issue in issues
        )

    def test_transcript_derived_headings_do_not_require_form_fields(self) -> None:
        prompt = (
            "Bygg ett flöde där användaren laddar upp en ljudfil vid körning. "
            "Ljudfilen är en inspelning från ett kommunfullmäktigemöte. Flödet "
            "ska först transkribera ljudfilen till svensk text. Därefter ska "
            "transkriptionen analyseras och struktureras till ett "
            "mötesprotokoll. Rubrikerna ska inte vara inmatningsfält för "
            "användaren, utan ska skapas och fyllas i utifrån transkriptionen. "
            "Om mötestitel, organisationsnamn eller sekreterare inte framgår "
            "tydligt av transkriptionen ska flödet skriva “Ej angivet i "
            "transkriptionen” i rätt sektion, inte fråga användaren om det vid "
            "körning. Slutresultatet ska vara ett Word-dokument."
        )
        spec = FlowDraftSpecCore(
            flow_name="Mötesprotokoll",
            steps=[
                _step(
                    "step_audio",
                    "Transkribera ljud",
                    "Transkribera ljudfilen till svensk text.",
                    input_type=InputType.AUDIO,
                    output_type=OutputType.TEXT,
                    output_mode=OutputMode.TRANSCRIBE_ONLY,
                ),
                _step(
                    "step_protocol",
                    "Strukturera mötesprotokoll",
                    (
                        "Skapa rubriker från transkriptionen och skriv "
                        "Ej angivet i transkriptionen när uppgift saknas."
                    ),
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "required": ["protocol_sections"],
                        "properties": {"protocol_sections": {"type": "object"}},
                        "additionalProperties": False,
                    },
                ),
                _step(
                    "step_docx",
                    "Skapa DOCX",
                    "Skapa ett Word-dokument från mötesprotokollet.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.JSON,
                    output_type=OutputType.DOCX,
                ),
            ],
        )

        feedback = build_conversation_aware_quality_feedback(
            [{"role": "user", "content": prompt}],
            spec,
        )

        assert feedback is None

    def test_rich_workflow_requires_json_contract_step_fires_when_missing(
        self,
    ) -> None:
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            render_critic_issues,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[
                _step(
                    "step_a",
                    "Analysera dokument",
                    "Läs och skriv rapport direkt.",
                    input_type=InputType.DOCUMENT,
                    output_type=OutputType.DOCX,
                )
            ],
        )
        context = self._context_with_signals(spec, prefers_structured_intermediate=True)

        issues = render_critic_issues(context)

        assert any(
            "output_contract" in issue or "JSON-steg" in issue for issue in issues
        )

    def test_rich_workflow_requires_json_contract_step_silent_for_generated_docx_without_structure(
        self,
    ) -> None:
        """Edge case: a plain generated DOCX with no structured-intermediate
        signal must not be nagged about JSON steps. This is the most
        common false-positive shape — user wants a simple
        document-in/document-out workflow, planner obliged, no
        downstream reuse was ever requested.
        """
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            render_critic_issues,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[
                _step(
                    "step_a",
                    "Analysera dokument",
                    "Skriv rapport direkt från dokumentet.",
                    input_type=InputType.DOCUMENT,
                    output_type=OutputType.DOCX,
                )
            ],
        )
        context = self._context_with_signals(
            spec, prefers_structured_intermediate=False
        )

        issues = render_critic_issues(context)

        assert not any("output_contract" in issue for issue in issues)
        assert not any("JSON-steg" in issue for issue in issues)

    def test_rich_workflow_requires_multiple_steps_fires_below_three_steps(
        self,
    ) -> None:
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            render_critic_issues,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[
                _step(
                    "step_a",
                    "Analysera dokument",
                    "Analysera.",
                    input_type=InputType.DOCUMENT,
                ),
                _step(
                    "step_b",
                    "Skriv rapport",
                    "Skriv.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.DOCX,
                ),
            ],
        )
        context = self._context_with_signals(spec, prefers_quality_step=True)

        issues = render_critic_issues(context)

        assert any("mellanliggande" in issue.casefold() for issue in issues)

    def test_rich_workflow_requires_multiple_steps_silent_when_three_steps_present(
        self,
    ) -> None:
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            render_critic_issues,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[
                _step(
                    "step_a",
                    "Analysera dokument",
                    "Analysera.",
                    input_type=InputType.DOCUMENT,
                    output_type=OutputType.JSON,
                    output_contract={"type": "object"},
                ),
                _step(
                    "step_b",
                    "Granska analysen",
                    "Granska.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.JSON,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_c",
                    "Skriv rapport",
                    "Skriv.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.DOCX,
                ),
            ],
        )
        context = self._context_with_signals(spec, prefers_quality_step=True)

        issues = render_critic_issues(context)

        assert not any("mellanliggande" in issue.casefold() for issue in issues)

    def test_rich_workflow_invariants_all_silent_when_not_a_rich_workflow(
        self,
    ) -> None:
        """When `rich_document_workflow` is False, none of the three
        invariants may fire — even if the underlying sub-signals are set.
        This guards against a regression where a sub-signal alone (e.g.
        a stray quality keyword on a non-document flow) re-triggers the
        nags.
        """
        from intric.flows.ai_builder.ai_builder_critic_invariants import (
            render_critic_issues,
        )

        spec = FlowDraftSpecCore(
            flow_name="Kort sammanfattning",
            steps=[
                _step(
                    "step_a",
                    "Skriv sammanfattning",
                    "Sammanfatta texten.",
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                )
            ],
        )
        context = self._context_with_signals(
            spec,
            rich=False,
            needs_form_fields=True,
            prefers_structured_intermediate=True,
            prefers_quality_step=True,
        )

        issues = render_critic_issues(context)

        assert not any("rich" in issue.casefold() for issue in issues)
        assert not any("mellanliggande" in issue.casefold() for issue in issues)
        assert not any(
            "återanvända strukturerad" in issue.casefold() for issue in issues
        )
