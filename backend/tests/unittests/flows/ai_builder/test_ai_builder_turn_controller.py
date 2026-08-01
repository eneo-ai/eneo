from __future__ import annotations

from datetime import datetime, timezone
from typing import get_args
from uuid import UUID

import pytest

from eneo.files.file_models import FileType
from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContext,
    AIBuilderAttachmentEvidence,
    AIBuilderAttachmentSchemaDiscovery,
)
from eneo.flows.ai_builder.ai_builder_conversation_compaction import (
    MAX_SESSION_MESSAGE_BYTES,
    compact_ai_builder_conversation,
    conversation_serialized_size_bytes,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    make_persisted_assistant_tool_call,
    metadata_for_assistant_question,
    metadata_for_user_message,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    build_requirements_version,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    build_declared_schema_candidate,
    build_schema_evidence,
    resolve_structured_schema_direction,
    schema_direction_option_values,
)
from eneo.flows.ai_builder.ai_builder_tool_names import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
)
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    AskCanonicalQuestion,
    CommitArchitecture,
    ConfirmRequirements,
    ReviseArchitecture,
    resolve_turn_control,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommit,
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


def _slot(
    name: str,
    value: str,
    *,
    source: SlotSource = "structured_answer",
    confidence: SlotConfidence = "high",
) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source=source,
        evidence=[f"{source}:{name}"],
        confidence=confidence,
    )


def _state(**slots: str) -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots = {name: _slot(name, value) for name, value in slots.items()}
    return state


def _finalized_commit_for_state(state: PlanningState) -> ArchitectureCommit:
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    return finalize_architecture_commit(
        draft,
        now=lambda: datetime(2026, 4, 24, tzinfo=timezone.utc),
    )


def _decision(
    *,
    state: PlanningState,
    ui_language: str | None,
    requirements_confirmed: bool = False,
    discovery_assumptions: tuple[str, ...] = (),
) -> object:
    confirmed_attachment_evidence_fingerprint: str | None = None
    if requirements_confirmed:
        unconfirmed = resolve_turn_control(
            session_state=state,
            selected_discovery_question_ids=(),
            confirmed_attachment_evidence_fingerprint=None,
            ui_language=ui_language,
            discovery_assumptions=discovery_assumptions,
        ).decision
        if isinstance(unconfirmed, ConfirmRequirements):
            confirmed_attachment_evidence_fingerprint = (
                unconfirmed.attachment_evidence_fingerprint
            )
    return resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_attachment_evidence_fingerprint=(
            confirmed_attachment_evidence_fingerprint
        ),
        ui_language=ui_language,
        discovery_assumptions=discovery_assumptions,
    ).decision


def test_server_builds_ask_question_for_allowed_target() -> None:
    state = _state(primary_runtime_input="documents", terminal_output="text")
    decision = _decision(state=state, ui_language="en")

    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "document_material_scope"
    assert "uploaded source material" in decision.prompt


@pytest.mark.parametrize("ui_language", ["en", "sv"])
@pytest.mark.parametrize("field_fill", ["\0", '"', "\\", "😀"])
def test_schema_direction_maximum_question_covers_complete_set_and_fits_limit(
    ui_language: str,
    field_fill: str,
) -> None:
    candidates = tuple(
        build_declared_schema_candidate(
            {
                "type": "object",
                "properties": {
                    f"{candidate_index}-{field_index}-{field_fill * 76}": {
                        "type": "string"
                    }
                    for field_index in range(8)
                },
            },
            source_file_ids=(UUID(int=candidate_index + 1),),
            provenance=(
                f"file:{UUID(int=candidate_index + 1)}:json_schema_attachment",
            ),
        )
        for candidate_index in range(100)
    )
    attachment_context = AIBuilderAttachmentContext(
        context=None,
        evidence=tuple(
            AIBuilderAttachmentEvidence(
                file_id=UUID(int=index + 1),
                filename="😀" * 80,
                file_type=FileType.TEXT,
                mimetype="application/json",
                has_readable_text=True,
                excerpt=None,
                coverage="fully_seen",
            )
            for index in range(100)
        ),
        included_file_ids=[],
        total_chars=0,
        truncated=False,
        schema_discovery=AIBuilderAttachmentSchemaDiscovery(candidates=candidates),
    )

    decision = resolve_turn_control(
        session_state=PlanningState.empty(),
        selected_discovery_question_ids=(),
        confirmed_attachment_evidence_fingerprint=None,
        ui_language=ui_language,
        attachment_context=attachment_context,
        schema_candidates=candidates,
        schema_direction_pending=True,
    ).decision

    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "schema_direction"
    assert decision.question is not None
    question = decision.question
    tool_call = make_persisted_assistant_tool_call(
        tool_call_id="schema_direction",
        tool_name=ASK_STRUCTURED_QUESTION_TOOL_NAME,
        arguments=question.question_data.model_dump(
            mode="json",
            exclude_none=False,
            exclude_unset=True,
        ),
    )
    assistant_message = ConversationMessage(
        role="assistant",
        content=question.assistant_text,
        metadata=metadata_for_assistant_question(question.question_data),
        tool_calls=[tool_call.model_dump(mode="json")],
    )
    selected_fingerprint = candidates[-1].fingerprint
    answer_message = ConversationMessage(
        role="user",
        content="Use this schema for the result.",
        metadata=metadata_for_user_message(
            question_answer={
                "question_id": "schema_direction",
                "selected_values": [f"output:{selected_fingerprint}"],
            }
        ),
    )
    persisted_conversation = [
        message.model_dump(mode="json")
        for message in (assistant_message, answer_message)
    ]
    restored_conversation = [
        ConversationMessage.from_persisted(message)
        for message in persisted_conversation
    ]
    selected_direction = resolve_structured_schema_direction(
        conversation=restored_conversation,
        candidates=candidates,
    )

    assert tuple(option.id for option in question.question_data.options) == (
        schema_direction_option_values(candidates)
    )
    assert question.question_data.selection_mode == "multi"
    assert question.question_data.requires_confirm is True
    assert question.question_data.allow_custom is False
    assert all(
        option.description is not None and "…" in option.description
        for option in question.question_data.options
        if option.id != "reference_only"
    )
    assert (
        conversation_serialized_size_bytes([assistant_message])
        < MAX_SESSION_MESSAGE_BYTES
    )
    assert compact_ai_builder_conversation([assistant_message]) == [assistant_message]
    assert selected_direction is not None
    assert selected_direction.output_fingerprint == selected_fingerprint


def test_server_builds_commit_when_no_questions_remain() -> None:
    state = _state(
        primary_runtime_input="documents",
        terminal_output="text",
        document_material_scope="flexible_document_case",
    )
    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, CommitArchitecture)
    assert decision.architecture_commit.tuples_chain


def test_server_commit_for_text_docx_has_resolvable_pattern() -> None:
    state = _state(
        primary_runtime_input="text",
        terminal_output="docx_document",
    )
    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, CommitArchitecture)
    assert decision.architecture_commit.chosen_patterns == ["text_to_artifact_report"]
    assert decision.architecture_commit.tuples_chain[0].output_mode == "render_verbatim"


def test_server_builds_confirm_requirements_checkpoint_after_commit() -> None:
    state = _state(
        primary_runtime_input="documents",
        terminal_output="docx_document",
        document_material_scope="flexible_document_case",
        docx_output_mode="generated_docx",
        runtime_metadata_fields="no_extra_metadata",
    )
    state.architecture_commit = _finalized_commit_for_state(state)
    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ConfirmRequirements)
    payload = decision.payload
    assert (
        payload.summary
        == "Flödet ska ta emot Dokument vid körning och leverera DOCX-dokument."
    )
    assert payload.input_description == "Primär indata vid körning: Dokument."
    assert payload.output_description == "Huvudsakligt slutresultat: DOCX-dokument."
    assert {decision.topic for decision in payload.key_decisions} >= {
        "DOCX-resultat",
        "Indata vid körning",
        "Planerad bearbetning",
        "Slutresultat",
    }
    assert {decision.decision for decision in payload.key_decisions} >= {
        "Genererad DOCX utan mall",
        "Ibland ett, ibland flera dokument",
        "Inga extra fält",
        "Skapa DOCX",
    }
    assert "Docx Output Mode" not in {
        decision.topic for decision in payload.key_decisions
    }


def test_server_confirmation_discloses_truncated_template_placeholders_in_swedish() -> (
    None
):
    state = _state(primary_runtime_input="text", terminal_output="docx_document")
    state.output_schema_evidence = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {f"field_{index}": {"type": "string"} for index in range(8)},
        },
        source="template_placeholders",
        source_file_ids=("00000000-0000-0000-0000-000000000001",),
        confidence="medium",
        evidence=("file:00000000-0000-0000-0000-000000000001:placeholder",),
        total_count=12,
        truncated=True,
    )
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ConfirmRequirements)
    assert (
        "Mallen innehåller 12 unika platshållare; 8 visas i planeringsunderlaget."
        in decision.payload.summary
    )


def test_server_confirmation_discloses_truncated_template_placeholders_in_english() -> (
    None
):
    state = _state(primary_runtime_input="text", terminal_output="docx_document")
    state.output_schema_evidence = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {f"field_{index}": {"type": "string"} for index in range(8)},
        },
        source="template_placeholders",
        source_file_ids=("00000000-0000-0000-0000-000000000001",),
        confidence="medium",
        evidence=("file:00000000-0000-0000-0000-000000000001:placeholder",),
        total_count=12,
        truncated=True,
    )
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(state=state, ui_language="en")

    assert isinstance(decision, ConfirmRequirements)
    assert (
        "The template contains 12 unique placeholders; 8 are shown in the planning evidence."
        in decision.payload.summary
    )


@pytest.mark.parametrize(
    ("ui_language", "misleading_fragment"),
    [
        ("en", "controls the JSON result"),
        ("sv", "styr JSON-resultatet"),
    ],
)
def test_confirmation_presents_input_schema_without_calling_it_a_docx_contract(
    ui_language: str,
    misleading_fragment: str,
) -> None:
    state = _state(primary_runtime_input="text", terminal_output="docx_document")
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
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(state=state, ui_language=ui_language)

    assert isinstance(decision, ConfirmRequirements)
    assert misleading_fragment not in decision.payload.summary
    assert (
        "indataschema" if ui_language == "sv" else "input schema"
    ) in decision.payload.summary


@pytest.mark.parametrize(
    ("ui_language", "summary_fragment", "layout_fragment"),
    [
        (
            "en",
            "A conservative output shape was inferred from the selected example",
            "does not promise exact visual layout",
        ),
        (
            "sv",
            "En försiktig utdatastruktur har härletts från valt exempelresultat",
            "lovar inte exakt visuell layout",
        ),
    ],
)
def test_server_confirmation_discloses_inferred_example_structure_and_style(
    ui_language: str,
    summary_fragment: str,
    layout_fragment: str,
) -> None:
    file_id = UUID("00000000-0000-0000-0000-000000000711")
    state = _state(primary_runtime_input="text", terminal_output="structured_json")
    state.architecture_commit = _finalized_commit_for_state(state)
    state.file_roles = [
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
    ]
    constraints = ExampleOutputConstraintEvidence(
        source_file_ids=[file_id],
        source_coverage=[
            ExampleOutputSourceCoverage(
                file_id=file_id,
                coverage="fully_seen",
            )
        ],
        headings=["Summary", "Decision", "Next steps"],
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
    )
    schema_evidence = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {
                "decision": {"type": "string"},
                "count": {"type": "integer"},
            },
        },
        source="inferred_example",
        source_file_ids=(file_id,),
        confidence="medium",
        evidence=(f"file:{file_id}:inferred_example_shape",),
    )
    state = PlanningState.model_validate(
        {
            **dict(state),
            "example_output_constraints": constraints,
            "schema_resolution": SchemaResolution.from_evidence(
                input_evidence=None,
                output_evidence=schema_evidence,
            ),
            "example_output_schema_inference": ExampleOutputSchemaInferenceOutcome(
                status="inferred",
                source_file_ids=[file_id],
            ),
        }
    )

    decision = _decision(state=state, ui_language=ui_language)

    assert isinstance(decision, ConfirmRequirements)
    assert summary_fragment in decision.payload.summary
    assumptions = "\n".join(decision.payload.assumptions)
    assert "Summary" in assumptions
    assert "Formal and concise" in assumptions
    assert layout_fragment in assumptions


def test_confirmation_fingerprint_covers_nonvisible_example_evidence() -> None:
    file_id = UUID("00000000-0000-0000-0000-000000000712")
    state = _state(primary_runtime_input="text", terminal_output="structured_text")
    state.architecture_commit = _finalized_commit_for_state(state)
    state.file_roles = [
        FileRoleEvidence(
            file_id=file_id,
            filename="expected.txt",
            file_type="text",
            mimetype="text/plain",
            has_readable_text=True,
            coverage="fully_seen",
            role="example_output",
            source="model",
            confidence="medium",
        )
    ]
    constraints = ExampleOutputConstraintEvidence(
        source_file_ids=[file_id],
        source_coverage=[
            ExampleOutputSourceCoverage(
                file_id=file_id,
                coverage="fully_seen",
            )
        ],
        headings=["Summary"],
        style_constraints=[
            ExampleOutputStyleConstraint(
                category="tone",
                description="Original hidden detail",
            )
        ],
        confidence="medium",
        citations=[
            ExampleOutputCitation(
                source_id=f"uploaded_file:{file_id}",
                file_id=file_id,
                quote="Summary",
            )
        ],
    )
    state = PlanningState.model_validate(
        {
            **dict(state),
            "example_output_constraints": constraints,
            "example_output_schema_inference": ExampleOutputSchemaInferenceOutcome(
                status="not_inferred",
                reason="no_json_object",
                source_file_ids=[file_id],
            ),
        }
    )
    first = resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_attachment_evidence_fingerprint=None,
        ui_language="en",
    ).decision
    assert isinstance(first, ConfirmRequirements)

    changed_constraints = constraints.model_copy(
        update={
            "style_constraints": [
                ExampleOutputStyleConstraint(
                    category="tone",
                    description="Changed hidden detail",
                )
            ]
        }
    )
    changed = PlanningState.model_validate(
        {
            **dict(state),
            "example_output_constraints": changed_constraints,
        }
    )
    second = resolve_turn_control(
        session_state=changed,
        selected_discovery_question_ids=(),
        confirmed_attachment_evidence_fingerprint=(
            first.attachment_evidence_fingerprint
        ),
        ui_language="en",
    ).decision

    assert isinstance(second, ConfirmRequirements)
    assert (
        second.attachment_evidence_fingerprint != first.attachment_evidence_fingerprint
    )


def test_server_confirmation_discloses_attachment_roles_and_honest_coverage() -> None:
    state = _state(primary_runtime_input="text", terminal_output="docx_document")
    state.file_roles = [
        FileRoleEvidence(
            file_id=UUID("00000000-0000-0000-0000-000000000701"),
            filename="complete.docx",
            file_type="document",
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            has_readable_text=True,
            coverage="fully_seen",
            role="template",
            source="heuristic",
            confidence="medium",
        ),
        FileRoleEvidence(
            file_id=UUID("00000000-0000-0000-0000-000000000702"),
            filename="not-excerpted.pdf",
            file_type="document",
            mimetype="application/pdf",
            has_readable_text=True,
            coverage="inventory_only",
            role="reference_material",
            source="model",
            confidence="medium",
        ),
        FileRoleEvidence(
            file_id=UUID("00000000-0000-0000-0000-000000000703"),
            filename="unreadable.bin",
            file_type="text",
            mimetype="application/octet-stream",
            has_readable_text=False,
            coverage="inventory_only",
            role="context_only",
            source="heuristic",
            confidence="low",
        ),
    ]
    state.architecture_commit = _finalized_commit_for_state(state)

    swedish = _decision(state=state, ui_language="sv")
    english = _decision(state=state, ui_language="en")

    assert isinstance(swedish, ConfirmRequirements)
    assert isinstance(english, ConfirmRequirements)
    assert any(
        'Bilageunderlag – Bilaga "complete.docx": vald roll Mall; '
        "läsbar text: ja; "
        "täckning: hela den läsbara texten ingår." == assumption
        for assumption in swedish.payload.assumptions
    )
    assert any(
        'Bilageunderlag – Bilaga "not-excerpted.pdf": vald roll Referensmaterial; '
        "läsbar text: ja; täckning: läsbar text finns men "
        "inget utdrag ingår." == assumption
        for assumption in swedish.payload.assumptions
    )
    assert any(
        'Attachment evidence — Attachment "unreadable.bin": '
        "selected role Context only; "
        "readable text: no; coverage: no readable text is available." == assumption
        for assumption in english.payload.assumptions
    )


def test_server_confirmation_bounds_attachment_detail_and_versions_coverage() -> None:
    state = _state(primary_runtime_input="text", terminal_output="docx_document")
    long_filename = f"attachment-0-{'x' * 120}.txt"
    state.file_roles = [
        FileRoleEvidence(
            file_id=UUID(int=index + 1),
            filename=long_filename if index == 0 else f"attachment-{index}.txt",
            file_type="text",
            mimetype="text/plain",
            has_readable_text=True,
            coverage="fully_seen",
            role="context_only",
            source="heuristic",
            confidence="low",
        )
        for index in range(12)
    ]
    state.architecture_commit = _finalized_commit_for_state(state)

    first = _decision(state=state, ui_language="en")
    assert isinstance(first, ConfirmRequirements)
    attachment_assumptions = [
        assumption
        for assumption in first.payload.assumptions
        if assumption.startswith('Attachment evidence — Attachment "')
    ]
    assert len(attachment_assumptions) == 10
    assert all(long_filename not in assumption for assumption in attachment_assumptions)
    assert "…" in attachment_assumptions[0]
    assert all("fully_seen" not in assumption for assumption in attachment_assumptions)
    assert (
        "Attachment evidence — 2 additional attachments are omitted from this "
        "summary (12 total)." in first.payload.assumptions
    )
    first_version = build_requirements_version(first.payload)

    state.file_roles[0] = state.file_roles[0].model_copy(
        update={"coverage": "excerpt_truncated"}
    )
    changed = _decision(state=state, ui_language="en")
    assert isinstance(changed, ConfirmRequirements)
    assert build_requirements_version(changed.payload) != first_version


def test_server_reconfirms_when_omitted_attachment_facts_change() -> None:
    state = _state(primary_runtime_input="text", terminal_output="docx_document")
    state.file_roles = [
        FileRoleEvidence(
            file_id=UUID(int=index + 1),
            filename=f"attachment-{index}.txt",
            file_type="text",
            mimetype="text/plain",
            has_readable_text=True,
            coverage="fully_seen",
            role="context_only",
            source="heuristic",
            confidence="low",
        )
        for index in range(12)
    ]
    state.architecture_commit = _finalized_commit_for_state(state)
    prior = resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_attachment_evidence_fingerprint=None,
        ui_language="en",
    ).decision
    assert isinstance(prior, ConfirmRequirements)

    state.file_roles[11] = state.file_roles[11].model_copy(
        update={
            "coverage": "excerpt_truncated",
            "role": "reference_material",
        }
    )
    current = resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_attachment_evidence_fingerprint=(
            prior.attachment_evidence_fingerprint
        ),
        ui_language="en",
    ).decision

    assert isinstance(current, ConfirmRequirements)


def test_server_reconfirms_for_clipped_filename_identity_collision() -> None:
    state = _state(primary_runtime_input="text", terminal_output="docx_document")
    shared_prefix = "x" * 100
    state.file_roles = [
        FileRoleEvidence(
            file_id=UUID(int=1),
            filename=f"{shared_prefix}-first.txt",
            file_type="text",
            mimetype="text/plain",
            has_readable_text=True,
            coverage="fully_seen",
            role="context_only",
            source="heuristic",
            confidence="low",
        )
    ]
    state.architecture_commit = _finalized_commit_for_state(state)
    prior = resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_attachment_evidence_fingerprint=None,
        ui_language="en",
    ).decision
    assert isinstance(prior, ConfirmRequirements)

    state.file_roles[0] = state.file_roles[0].model_copy(
        update={
            "file_id": UUID(int=2),
            "filename": f"{shared_prefix}-second.txt",
        }
    )
    current = resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_attachment_evidence_fingerprint=(
            prior.attachment_evidence_fingerprint
        ),
        ui_language="en",
    ).decision

    assert isinstance(current, ConfirmRequirements)


def test_server_confirmation_summarizes_processing_goal() -> None:
    state = _state(
        primary_runtime_input="audio",
        terminal_output="docx_document",
        docx_output_mode="generated_docx",
        post_processing_goal="action_followup",
        runtime_metadata_fields="no_extra_metadata",
    )
    state.architecture_commit = _finalized_commit_for_state(state)
    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ConfirmRequirements)
    payload = decision.payload
    assert "Resultatet ska hjälpa till med: Beslut, nästa steg" in payload.summary
    assert {decision.topic for decision in payload.key_decisions} >= {
        "Syfte med bearbetningen",
    }
    assert {decision.decision for decision in payload.key_decisions} >= {
        "Beslut, nästa steg och uppföljning",
    }


def test_server_confirmation_names_json_to_json_architecture() -> None:
    state = _state(
        primary_runtime_input="json",
        terminal_output="structured_json",
        post_processing_goal="extract_key_information",
        runtime_metadata_fields="no_extra_metadata",
    )
    state.architecture_commit = _finalized_commit_for_state(state)
    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ConfirmRequirements)
    decisions = {
        decision.topic: decision.decision for decision in decision.payload.key_decisions
    }
    assert decisions["Planerad bearbetning"] == "JSON till JSON"


def test_server_revises_architecture_for_commit_grade_terminal_output_change() -> None:
    state = _state(primary_runtime_input="text", terminal_output="pdf_document")
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            ),
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=[],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="f" * 64,
    )

    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ReviseArchitecture)
    assert decision.architecture_commit.tuples_chain[0].output_type == "pdf"
    assert decision.architecture_commit.chosen_patterns == ["text_to_artifact_report"]


def test_server_reasks_when_pinned_commit_conflicts_with_weak_output_slot() -> None:
    state = _state(primary_runtime_input="text")
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
        source="model",
        confidence="medium",
    )
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            ),
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=[],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )

    decision = _decision(
        state=state,
        ui_language="sv",
        requirements_confirmed=True,
    )

    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "terminal_output"


def test_server_confirmation_separates_decisions_from_assumptions() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "audio"),
        "terminal_output": _slot(
            "terminal_output",
            "structured_text",
            source="model",
            confidence="medium",
        ),
        "runtime_metadata_fields": _slot(
            "runtime_metadata_fields",
            "no_extra_metadata",
            source="policy_default",
            confidence="medium",
        ),
        "post_processing_goal": _slot(
            "post_processing_goal",
            "summarize_or_overview",
            source="heuristic",
        ),
        "docx_output_mode": _slot(
            "docx_output_mode",
            "generated_docx",
            source="flow_default",
        ),
    }
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ConfirmRequirements)
    decisions = {
        decision.topic: decision.decision for decision in decision.payload.key_decisions
    }
    assert "Indata vid körning" in decisions
    assert "DOCX-resultat" in decisions
    assert "Planerad bearbetning" in decisions
    assert "Slutresultat" not in decisions
    assert "Metadata vid körning" not in decisions
    assert "Syfte med bearbetningen" not in decisions
    assert "Slutresultat: Strukturerat textresultat" in decision.payload.assumptions
    assert "Metadata vid körning: Inga extra fält" in decision.payload.assumptions
    assert "Syfte med bearbetningen: Sammanfatta eller ge överblick" in (
        decision.payload.assumptions
    )


def test_server_confirmation_includes_discovery_assumptions() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "documents"),
        "terminal_output": _slot("terminal_output", "pdf_document"),
        "document_material_scope": _slot(
            "document_material_scope",
            "multiple_documents_case",
        ),
        "pdf_generation_mode": _slot("pdf_generation_mode", "generated_pdf"),
        "runtime_metadata_fields": _slot(
            "runtime_metadata_fields",
            "no_extra_metadata",
        ),
    }
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(
        state=state,
        ui_language="sv",
        discovery_assumptions=("Rapporten får ett avsnitt per källa.",),
    )

    assert isinstance(decision, ConfirmRequirements)
    assert "Rapporten får ett avsnitt per källa." in decision.payload.assumptions


def test_slot_sources_land_in_exactly_one_summary_bucket() -> None:
    source_to_slot = {
        "structured_answer": ("primary_runtime_input", "audio"),
        "requirements_summary": ("terminal_output", "structured_text"),
        "flow_default": ("docx_output_mode", "generated_docx"),
        "policy_default": ("runtime_metadata_fields", "no_extra_metadata"),
        "heuristic": ("post_processing_goal", "summarize_or_overview"),
        "model": ("document_material_scope", "single_uploaded_document"),
    }
    state = PlanningState.empty()
    state.resolved_slots = {
        slot_name: _slot(slot_name, value, source=source)
        for source, (slot_name, value) in source_to_slot.items()
    }
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ConfirmRequirements)
    assert set(source_to_slot) == set(get_args(SlotSource))
    decision_topics = {
        key_decision.topic for key_decision in decision.payload.key_decisions
    } - {"Planerad bearbetning"}
    assumption_topics = {
        assumption.split(":", 1)[0]
        for assumption in decision.payload.assumptions
        if ":" in assumption
    }
    assert decision_topics == {
        "Indata vid körning",
        "Slutresultat",
        "DOCX-resultat",
    }
    assert assumption_topics == {
        "Dokumentunderlag",
        "Metadata vid körning",
        "Syfte med bearbetningen",
    }
    assert decision_topics.isdisjoint(assumption_topics)
