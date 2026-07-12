from __future__ import annotations

from uuid import uuid4

from eneo.flows.ai_builder.ai_builder_discovery import analyze_discovery
from eneo.flows.ai_builder.ai_builder_discovery_profile_builder import (
    build_discovery_profile,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_edit_scope import build_active_request_window
from eneo.flows.domain.flow import Flow, FlowStep


def _make_flow_step(
    *,
    step_order: int,
    user_description: str,
    input_source: str,
    input_type: str,
    output_mode: str,
    output_type: str,
    input_config: dict | None = None,
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
    )


def _make_flow(*steps: FlowStep) -> Flow:
    return Flow(
        id=uuid4(),
        name="Filanalys",
        description="Analyserar underlag och skriver rapport.",
        tenant_id=uuid4(),
        user_id=uuid4(),
        space_id=uuid4(),
        steps=list(steps),
        metadata_json=None,
        published=False,
        published_version=None,
        draft_revision=3,
    )


class TestEditScopePolicy:
    def test_output_only_edit_does_not_reopen_document_scope_for_existing_flow(
        self,
    ) -> None:
        flow = _make_flow(
            _make_flow_step(
                step_order=1,
                user_description="Extrahera text från fil",
                input_source="flow_input",
                input_type="file",
                output_mode="pass_through",
                output_type="text",
            ),
            _make_flow_step(
                step_order=2,
                user_description="Generera rapport",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            ),
        )
        conversation = [
            ConversationMessage(
                role="user",
                content="Ändra sista steget till en pdf rapport istället för text output",
            )
        ]

        analysis = analyze_discovery(conversation, flow=flow)
        question_ids = {
            issue.suggestion.question_id
            for issue in analysis.issues
            if issue.suggestion is not None
        }

        assert "document_material_scope" not in question_ids
        assert "input_material_mode" not in question_ids

    def test_output_only_workflow_wording_does_not_reopen_input_question(
        self,
    ) -> None:
        flow = _make_flow(
            _make_flow_step(
                step_order=1,
                user_description="Extrahera text från fil",
                input_source="flow_input",
                input_type="file",
                output_mode="pass_through",
                output_type="text",
            ),
            _make_flow_step(
                step_order=2,
                user_description="Generera rapport",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            ),
        )
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Ändra bara sista steget till ett sammanfattningsflöde "
                    "med kort text output."
                ),
            )
        ]

        analysis = analyze_discovery(conversation, flow=flow)
        question_ids = {
            issue.suggestion.question_id
            for issue in analysis.issues
            if issue.suggestion is not None
        }

        assert "input_material_mode" not in question_ids

    def test_output_only_docx_edit_keeps_only_output_family_questions_active(
        self,
    ) -> None:
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
        conversation = [
            ConversationMessage(
                role="user",
                content="Ändra bara sista steget så att slutrapporten genereras som DOCX i stället för PDF.",
            )
        ]

        analysis = analyze_discovery(conversation, flow=flow)
        question_ids = {
            issue.suggestion.question_id
            for issue in analysis.issues
            if issue.suggestion is not None
        }

        assert "docx_output_mode" not in question_ids
        assert "input_material_mode" not in question_ids
        assert "document_kind" not in question_ids
        assert "document_material_scope" not in question_ids

    def test_word_instead_of_pdf_edit_defaults_generated_docx_without_reopening_question(
        self,
    ) -> None:
        flow = _make_flow(
            _make_flow_step(
                step_order=1,
                user_description="Transkribera ljud",
                input_source="flow_input",
                input_type="audio",
                output_mode="transcribe_only",
                output_type="text",
            ),
            _make_flow_step(
                step_order=2,
                user_description="Tematisk sammanfattning",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            ),
            _make_flow_step(
                step_order=3,
                user_description="Skriv slutrapport",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="pdf",
            ),
        )

        analysis = analyze_discovery(
            [
                ConversationMessage(
                    role="user",
                    content="ändra så att jag får ut en word dokument istället för en pdf",
                )
            ],
            flow=flow,
        )

        question_ids = {
            issue.suggestion.question_id
            for issue in analysis.issues
            if issue.suggestion is not None
        }

        assert "docx_output_mode" not in question_ids

    def test_requirements_confirmation_turn_merges_previous_output_change_request(
        self,
    ) -> None:
        flow = _make_flow(
            _make_flow_step(
                step_order=1,
                user_description="Transkribera ljud",
                input_source="flow_input",
                input_type="audio",
                output_mode="transcribe_only",
                output_type="text",
            ),
            _make_flow_step(
                step_order=2,
                user_description="Skapa strukturerad sammanfattning",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="pdf",
            ),
        )
        conversation = [
            ConversationMessage(
                role="user",
                content="ändra så att jag får ut en word dokument istället för en pdf",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="assistant",
                content="Jag förstår att du vill byta slutresultatet från PDF till DOCX.",
                tool_calls=[
                    {
                        "id": "call_requirements",
                        "name": "confirm_requirements",
                        "arguments": {
                            "summary": "Byt slutformat till DOCX.",
                            "key_decisions": [],
                            "input_description": "Ljudfil.",
                            "output_description": "DOCX.",
                        },
                    }
                ],
            ),
            ConversationMessage(
                role="tool",
                content="Requirements summary recorded.",
                tool_call_id="call_requirements",
            ),
            ConversationMessage(
                role="user",
                content="Ja, det stämmer. Bygg planen.",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": "v1",
                    "ui_language": "sv",
                },
            ),
        ]

        request_window = build_active_request_window(
            conversation,
            flow_defaults=build_discovery_profile(
                conversation[:1],
                flow=flow,
            ).flow_defaults,
        )

        assert "word dokument istället för en pdf" in request_window.text
        assert "ja, det stämmer. bygg planen." in request_window.text

    def test_requirements_confirmation_keeps_docx_mode_blocking_issue_active(
        self,
    ) -> None:
        flow = _make_flow(
            _make_flow_step(
                step_order=1,
                user_description="Transkribera ljud",
                input_source="flow_input",
                input_type="audio",
                output_mode="transcribe_only",
                output_type="text",
            ),
            _make_flow_step(
                step_order=2,
                user_description="Skapa strukturerad sammanfattning",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="pdf",
            ),
        )
        conversation = [
            ConversationMessage(
                role="user",
                content="ändra så att jag får ut en word dokument istället för en pdf",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="assistant",
                content="Jag förstår att du vill byta slutresultatet från PDF till DOCX.",
                tool_calls=[
                    {
                        "id": "call_requirements",
                        "name": "confirm_requirements",
                        "arguments": {
                            "summary": "Byt slutformat till DOCX.",
                            "key_decisions": [],
                            "input_description": "Ljudfil.",
                            "output_description": "DOCX.",
                        },
                    }
                ],
            ),
            ConversationMessage(
                role="tool",
                content="Requirements summary recorded.",
                tool_call_id="call_requirements",
            ),
            ConversationMessage(
                role="user",
                content="Ja, det stämmer. Bygg planen.",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": "v1",
                    "ui_language": "sv",
                },
            ),
        ]

        analysis = analyze_discovery(conversation, flow=flow)
        question_ids = {
            issue.suggestion.question_id
            for issue in analysis.issues
            if issue.suggestion is not None
        }

        assert "docx_output_mode" not in question_ids

    def test_rename_only_edit_does_not_reopen_input_questions(self) -> None:
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
                user_description="Grounded sammanfattning",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            ),
        )

        analysis = analyze_discovery(
            [
                ConversationMessage(
                    role="user",
                    content="Byt bara namn på steg 2 till Grounded sammanfattning med referenser.",
                )
            ],
            flow=flow,
        )

        assert analysis.issues == ()
        assert analysis.next_issue is None

    def test_citation_edit_does_not_reopen_input_questions(self) -> None:
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
                user_description="Grounded sammanfattning",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            ),
            _make_flow_step(
                step_order=3,
                user_description="Generera rapport",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="pdf",
            ),
        )

        analysis = analyze_discovery(
            [
                ConversationMessage(
                    role="user",
                    content="Aktivera källhänvisningar där det är mest logiskt men behåll slutleveransen som PDF.",
                )
            ],
            flow=flow,
        )
        question_ids = {
            issue.suggestion.question_id
            for issue in analysis.issues
            if issue.suggestion is not None
        }

        assert "document_kind" not in question_ids
        assert "document_material_scope" not in question_ids
        assert "input_material_mode" not in question_ids

    def test_processing_edit_does_not_reopen_input_questions(self) -> None:
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
                user_description="Sammanfatta innehållet",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            ),
            _make_flow_step(
                step_order=3,
                user_description="Generera rapport",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="pdf",
            ),
        )

        analysis = analyze_discovery(
            [
                ConversationMessage(
                    role="user",
                    content="Gör sammanfattningen kortare och lägg till ett steg för riskanalys före slutrapporten.",
                )
            ],
            flow=flow,
        )
        question_ids = {
            issue.suggestion.question_id
            for issue in analysis.issues
            if issue.suggestion is not None
        }

        assert "document_kind" not in question_ids
        assert "document_material_scope" not in question_ids
        assert "input_material_mode" not in question_ids

    def test_explicit_input_change_reactivates_input_family(self) -> None:
        flow = _make_flow(
            _make_flow_step(
                step_order=1,
                user_description="Extrahera text från fil",
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

        conversation = [
            ConversationMessage(
                role="user",
                content="Ändra flödet så att det tar emot flera dokument istället för ett.",
            )
        ]
        profile = build_discovery_profile(conversation, flow=flow)
        analysis = analyze_discovery(conversation, flow=flow)
        question_ids = {
            issue.suggestion.question_id
            for issue in analysis.issues
            if issue.suggestion is not None
        }

        assert "input_shape" in profile.edit_scope.active_families
        assert "final_pdf_type" not in question_ids
