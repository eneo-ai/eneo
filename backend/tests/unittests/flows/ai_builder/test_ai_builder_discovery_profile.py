from __future__ import annotations

from uuid import uuid4

from intric.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    build_flow_capability_profile,
)
from intric.flows.ai_builder.ai_builder_discovery_profile_builder import (
    build_discovery_profile,
    expresses_task_intent,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_edit_scope import has_change_semantics
from intric.flows.domain.flow import Flow, FlowStep


def _make_flow_step(
    *,
    step_order: int,
    user_description: str,
    input_source: str,
    input_type: str,
    output_mode: str,
    output_type: str,
    input_config: dict | None = None,
    input_bindings: dict | None = None,
    input_contract: dict | None = None,
    output_contract: dict | None = None,
    output_config: dict | None = None,
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
        input_config=input_config,
        input_bindings=input_bindings,
        input_contract=input_contract,
        output_contract=output_contract,
        output_config=output_config,
        mcp_policy="inherit",
    )


def _make_flow(*steps: FlowStep, metadata_json: dict | None = None) -> Flow:
    return Flow(
        id=uuid4(),
        name="Filanalys",
        description="Analyserar underlag och skriver rapport.",
        tenant_id=uuid4(),
        user_id=uuid4(),
        space_id=uuid4(),
        steps=list(steps),
        metadata_json=metadata_json,
        published=False,
        published_version=None,
        draft_revision=3,
    )


def test_build_flow_capability_profile_tracks_entry_points_and_step_capabilities() -> (
    None
):
    flow = _make_flow(
        _make_flow_step(
            step_order=1,
            user_description="Extrahera text från fil",
            input_source="flow_input",
            input_type="file",
            output_mode="pass_through",
            output_type="text",
            input_config={"runtime_input": {"enabled": True, "max_files": 5}},
            output_config={"citation_mode": "inline_inref_sidecar"},
        ),
        _make_flow_step(
            step_order=2,
            user_description="Strukturera innehåll",
            input_source="previous_step",
            input_type="text",
            output_mode="pass_through",
            output_type="json",
            input_bindings={"question": "{{ step_1.output.text }}"},
            output_contract={
                "type": "object",
                "properties": {"summary": {"type": "string"}},
            },
        ),
        _make_flow_step(
            step_order=3,
            user_description="Valfri extra text",
            input_source="flow_input",
            input_type="text",
            output_mode="pass_through",
            output_type="text",
        ),
        _make_flow_step(
            step_order=4,
            user_description="Skriv slutrapport",
            input_source="all_previous_steps",
            input_type="json",
            output_mode="template_fill",
            output_type="docx",
            output_config={
                "template_file_id": str(uuid4()),
                "bindings": {"summary": "{{ step_2.output.summary }}"},
            },
        ),
        metadata_json={
            "form_schema": {"fields": [{"name": "referensnummer", "type": "text"}]}
        },
    )

    profile = build_flow_capability_profile(flow)

    assert tuple(signature.step_order for signature in profile.flow_input_steps) == (
        1,
        3,
    )
    assert profile.runtime_input_mode == "text_and_documents"
    assert profile.document_material_scope == "multiple_documents_case"
    assert profile.upload_pattern == "multiple_pdfs"
    assert profile.final_output_type == "docx"
    assert profile.final_output_mode == "docx_document"
    assert profile.final_output_generation_mode == "template_fill"
    assert profile.citation_step_orders == (1,)
    assert profile.contract_step_orders == (2,)
    assert profile.variable_binding_step_orders == (2, 4)
    assert profile.all_previous_steps_orders == (4,)
    assert profile.settled_families == frozenset(
        {"output_artifact", "runtime_metadata"}
    )


def test_build_discovery_profile_uses_settled_flow_state_to_keep_docx_edit_output_scoped() -> (
    None
):
    flow = _make_flow(
        _make_flow_step(
            step_order=1,
            user_description="Extrahera text från fil",
            input_source="flow_input",
            input_type="file",
            output_mode="pass_through",
            output_type="text",
            input_config={"runtime_input": {"enabled": True, "max_files": 3}},
        ),
        _make_flow_step(
            step_order=2,
            user_description="Generera rapport",
            input_source="previous_step",
            input_type="text",
            output_mode="pass_through",
            output_type="pdf",
        ),
    )

    profile = build_discovery_profile(
        [
            ConversationMessage(
                role="user",
                content="Ändra bara sista steget så att slutrapporten genereras som DOCX i stället för PDF.",
            )
        ],
        flow=flow,
    )

    assert profile.input_intent.document_runtime_input_requested is True
    assert profile.capabilities.settled_families == frozenset(
        {"input_shape", "output_artifact"}
    )
    assert profile.edit_scope.active_families == frozenset({"output_artifact"})
    assert "input_shape" not in profile.edit_scope.active_families


def test_build_discovery_profile_merges_short_follow_up_into_active_request_window() -> (
    None
):
    flow = _make_flow(
        _make_flow_step(
            step_order=1,
            user_description="Extrahera text",
            input_source="flow_input",
            input_type="file",
            output_mode="pass_through",
            output_type="text",
            input_config={"runtime_input": {"enabled": True, "max_files": 1}},
        ),
        _make_flow_step(
            step_order=2,
            user_description="Generera rapport",
            input_source="previous_step",
            input_type="text",
            output_mode="pass_through",
            output_type="pdf",
        ),
    )

    profile = build_discovery_profile(
        [
            ConversationMessage(
                role="user",
                content="Ändra sista steget till DOCX i stället för PDF.",
            ),
            ConversationMessage(role="user", content="Kortare."),
        ],
        flow=flow,
    )

    assert profile.edit_scope.merged_previous_request is True
    assert "docx" in profile.active_request_text
    assert "kortare" in profile.active_request_text


def test_expresses_task_intent_uses_token_prefixes_not_raw_substrings() -> None:
    assert expresses_task_intent("Jag vill ha ett OCR-flöde.") is True
    assert expresses_task_intent("Jag vill producera något från min text.") is True
    assert expresses_task_intent("Skriv en kort rapport.") is True

    assert expresses_task_intent("Det här är en medioker produkt.") is False
    assert expresses_task_intent("Kan jag ha ett skrivbord där?") is False
    assert expresses_task_intent("Vad betyder transcribe_only?") is False


def test_build_discovery_profile_keeps_docx_output_intent_when_input_mentions_pdf() -> (
    None
):
    profile = build_discovery_profile(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som tar emot ett dokumentpaket med flera PDF-filer i ett ärende. "
                    "Steg 1 extraherar text ur alla dokument. Steg 2 identifierar risker och möjligheter som "
                    "strukturerad JSON. Steg 3 genererar en strukturerad DOCX-rapport utan mall."
                ),
            )
        ]
    )

    assert profile.output_intent.terminal_output == "docx_document"
    assert profile.output_intent.docx_output_mode == "generated_docx"
    assert (
        profile.planning_state.resolved_slots.get("document_material_scope") is not None
    )


def test_build_discovery_profile_exposes_runtime_metadata_and_structured_analysis_slots() -> (
    None
):
    profile = build_discovery_profile(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som analyserar flera PDF-dokument i samma ärende. "
                    "Användaren ska ange intern referens och önskat språk. "
                    "Strukturerad data ska användas där det förbättrar kvaliteten."
                ),
            )
        ]
    )

    runtime_metadata = profile.planning_state.resolved_slots.get(
        "runtime_metadata_fields"
    )
    structured_analysis = profile.planning_state.resolved_slots.get(
        "structured_analysis_need"
    )

    assert runtime_metadata is not None
    assert structured_analysis is not None


def test_has_change_semantics_recognizes_substitution_phrase() -> None:
    assert (
        has_change_semantics("ändra sista steget till docx i stället för pdf") is True
    )
    assert has_change_semantics("analysera docx-filer och skriv en rapport") is False


def test_profile_prefers_structured_intermediate_for_audio_artifact_analysis_report() -> (
    None
):
    profile = build_discovery_profile(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Create a flow that transcribes meeting audio, analyzes the "
                    "discussion topics, and produces a DOCX meeting report."
                ),
            )
        ]
    )

    assert profile.audio_like_input is True
    assert profile.output_intent.terminal_output == "docx_document"
    assert profile.prefer_structured_intermediate is True


def test_profile_does_not_force_structured_intermediate_for_simple_audio_docx_transcript() -> (
    None
):
    profile = build_discovery_profile(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Create a flow that transcribes meeting audio and produces "
                    "a DOCX file with the transcription."
                ),
            )
        ]
    )

    assert profile.audio_like_input is True
    assert profile.output_intent.terminal_output == "docx_document"
    assert profile.prefer_structured_intermediate is False
