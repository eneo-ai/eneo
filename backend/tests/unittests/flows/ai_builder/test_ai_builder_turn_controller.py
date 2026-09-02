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
from eneo.flows.ai_builder.ai_builder_discovery import analyze_discovery
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_error_contract import AIBuilderErrorCode
from eneo.flows.ai_builder.ai_builder_requirements_disclosure import (
    _slot_is_key_decision,
    build_requirements_disclosure,
)
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
    BuilderTurnControl,
    CommitArchitecture,
    ConfirmRequirements,
    GenerateProposal,
    RefuseArchitectureCommit,
    ReviseArchitecture,
    resolve_turn_control,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    CheckpointIntent,
    ExampleOutputCitation,
    ExampleOutputConstraintEvidence,
    ExampleOutputSchemaInferenceOutcome,
    ExampleOutputSourceCoverage,
    ExampleOutputStyleConstraint,
    FileRoleEvidence,
    NamedResultEvidence,
    PlanningState,
    ResolvedSlot,
    RuntimeMetadataFieldPurpose,
    SchemaResolution,
    SlotConfidence,
    SlotEvidenceLevel,
    SlotSource,
    StepTriple,
)
from eneo.flows.ai_builder.question_catalog import (
    RUNTIME_METADATA_FIELD_PURPOSES,
    render_summary_label,
)


def _slot(
    name: str,
    value: str,
    *,
    source: SlotSource = "structured_answer",
    confidence: SlotConfidence = "high",
    evidence_level: SlotEvidenceLevel | None = None,
) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source=source,
        evidence=[
            f"quote:user_message:test:{name}"
            if source == "model"
            else f"{source}:{name}"
        ],
        confidence=confidence,
        evidence_level=(
            evidence_level
            if evidence_level is not None or source != "model"
            else "inferred"
        ),
    )


def _turn_control(
    *,
    session_state: PlanningState,
    selected_discovery_question_ids: tuple[str, ...] = (),
    confirmed_requirements_version: str | None = None,
    ui_language: str | None = None,
    discovery_assumptions: tuple[str, ...] = (),
    **kwargs: object,
) -> BuilderTurnControl:
    """Build the disclosure first, exactly as both production callers do."""

    return resolve_turn_control(
        session_state=session_state,
        selected_discovery_question_ids=selected_discovery_question_ids,
        requirements_disclosure=build_requirements_disclosure(
            session_state,
            ui_language=ui_language,
            discovery_assumptions=discovery_assumptions,
        ),
        confirmed_requirements_version=confirmed_requirements_version,
        ui_language=ui_language,
        **kwargs,  # type: ignore[arg-type]
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
    selected_discovery_question_ids: tuple[str, ...] = (),
) -> object:
    disclosure = build_requirements_disclosure(
        state,
        ui_language=ui_language,
        discovery_assumptions=discovery_assumptions,
    )
    return resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=selected_discovery_question_ids,
        requirements_disclosure=disclosure,
        confirmed_requirements_version=(
            disclosure.requirements_version if requirements_confirmed else None
        ),
        ui_language=ui_language,
    ).decision


def test_server_builds_ask_question_for_allowed_target() -> None:
    state = _state(primary_runtime_input="documents", terminal_output="text")
    decision = _decision(
        state=state,
        ui_language="en",
        selected_discovery_question_ids=("document_material_scope",),
    )

    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "document_material_scope"


def test_a_planned_remaining_of_zero_is_not_a_promise_the_interview_has_ended() -> None:
    # The snapshot is only ever this turn's plan. A JSON flow whose output is
    # still open has nothing queued behind the output question, and answering
    # it structured JSON is what makes the JSON-processing question exist at
    # all — so a question arrives after the plan said nothing was left. Both
    # counts are derived from real discovery over the state of their own turn,
    # because a snapshot asserted from an injected queue proves nothing about
    # the contract clients read.
    conversation = [
        ConversationMessage(
            role="user",
            content="Vi vill skicka in JSON från vårt ärendesystem till flödet.",
        )
    ]

    before = _state(primary_runtime_input="json")
    before_decision = _decision(
        state=before,
        ui_language="sv",
        selected_discovery_question_ids=analyze_discovery(
            conversation, planning_state=before
        ).selected_question_ids,
    )

    assert isinstance(before_decision, AskCanonicalQuestion)
    assert before_decision.slot_name == "terminal_output"
    assert before_decision.planned_remaining == 0

    after = _state(primary_runtime_input="json", terminal_output="structured_json")
    after_decision = _decision(
        state=after,
        ui_language="sv",
        selected_discovery_question_ids=analyze_discovery(
            conversation, planning_state=after
        ).selected_question_ids,
    )

    assert isinstance(after_decision, AskCanonicalQuestion)
    assert after_decision.slot_name == "structured_io_contract"


def test_ask_question_carries_the_rest_of_the_queue_it_was_taken_from() -> None:
    # The queue is asked head-first, so what stands behind the head is what the
    # interview currently intends to ask next. It is this turn's plan and
    # nothing more: the queue is re-derived next turn over whatever the session
    # knows by then, so it can shrink or grow.
    state = _state(primary_runtime_input="documents", terminal_output="text")

    decision = _decision(
        state=state,
        ui_language="en",
        selected_discovery_question_ids=(
            "document_material_scope",
            "report_disposition",
            "runtime_metadata_fields",
        ),
    )

    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "document_material_scope"
    assert decision.planned_remaining == 2


def test_unresolved_purpose_is_asked_before_primary_input() -> None:
    decision = _decision(
        state=PlanningState.empty(),
        ui_language="en",
        selected_discovery_question_ids=("post_processing_goal",),
    )

    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "post_processing_goal"
    assert decision.planned_remaining == 2


@pytest.mark.parametrize(
    "runtime_metadata_state",
    ["basic_runtime_metadata", "detailed_runtime_metadata"],
)
def test_server_collects_runtime_field_details_before_requirements_confirmation(
    runtime_metadata_state: str,
) -> None:
    state = _state(
        primary_runtime_input="text",
        terminal_output="structured_text",
        runtime_metadata_fields=runtime_metadata_state,
    )
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(state=state, ui_language="en")

    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "runtime_metadata_field_details"
    # Decided ahead of the ranked queue, so no plan stands behind it.
    assert decision.planned_remaining is None
    assert decision.question is not None
    assert decision.question.question_data.input_field_collection is True
    assert [option.value for option in decision.question.question_data.options] == [
        "interpret_input",
        "shape_result",
        "whole_flow",
    ]
    assert [option.label for option in decision.question.question_data.options] == [
        "Use it to understand the input",
        "Use it to shape the final result",
        "Use it throughout the flow",
    ]
    # The line beside the question says why the fields matter; a line that
    # repeats the question carries nothing, so it must never be the question.
    assert decision.question.assistant_text != decision.question.question_data.question
    assert "form" in decision.question.assistant_text


def test_every_purpose_a_field_can_be_stored_with_can_also_be_chosen() -> None:
    # The catalog owns the words for each purpose and the question catalog is
    # a leaf that cannot import the stored vocabulary. A purpose added to one
    # and not the other is either an option nobody can pick or a stored value
    # the confirmation card cannot name.
    assert set(RUNTIME_METADATA_FIELD_PURPOSES) == set(
        get_args(RuntimeMetadataFieldPurpose)
    )


def test_omitted_runtime_metadata_keeps_visible_no_extra_fields_assumption() -> None:
    state = _state(
        primary_runtime_input="text",
        terminal_output="structured_text",
    )
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(state=state, ui_language="en")

    assert isinstance(decision, ConfirmRequirements)


@pytest.mark.parametrize(
    ("ui_language", "expected_message"),
    [
        (
            "en",
            "This combination of input and final output is not supported. Start "
            "fresh and choose a different input or final output.",
        ),
        (
            "sv",
            "Den här kombinationen av indata och slutresultat stöds inte. Börja om "
            "och välj en annan indata eller ett annat slutresultat.",
        ),
    ],
)
def test_unsupported_architecture_returns_localized_refusal(
    ui_language: str,
    expected_message: str,
) -> None:
    state = _state(
        primary_runtime_input="json",
        terminal_output="structured_text",
    )

    decision = _decision(state=state, ui_language=ui_language)

    assert decision == RefuseArchitectureCommit(
        code=AIBuilderErrorCode.UNSUPPORTED_ARCHITECTURE,
        message=expected_message,
    )


@pytest.mark.parametrize(
    ("ui_language", "expected_message"),
    [
        (
            "en",
            "Filling a fixed PDF template is not supported. Choose a normal "
            "generated PDF. If a fixed template is mandatory, use a DOCX "
            "template-based Flow instead.",
        ),
        (
            "sv",
            "Det går inte att fylla i en fast PDF-mall. Välj en vanlig genererad "
            "PDF. Om en fast mall är ett krav behöver du i stället använda ett "
            "flöde som bygger på en DOCX-mall.",
        ),
    ],
)
def test_pdf_template_refusal_explains_supported_alternatives(
    ui_language: str,
    expected_message: str,
) -> None:
    state = _state(
        primary_runtime_input="audio",
        terminal_output="pdf_document",
    )
    state.resolved_slots["pdf_generation_mode"] = _slot(
        "pdf_generation_mode",
        "pdf_template_requested",
    )

    decision = _decision(state=state, ui_language=ui_language)

    assert decision == RefuseArchitectureCommit(
        code=AIBuilderErrorCode.PDF_TEMPLATE_UNSUPPORTED,
        message=expected_message,
    )


def test_transcript_checkpoint_refusal_has_actionable_localized_message() -> None:
    state = _state(
        primary_runtime_input="documents",
        terminal_output="structured_text",
    )
    state.architecture_commit = _finalized_commit_for_state(state)
    state.checkpoint_intents = [
        CheckpointIntent(
            evidence_level="explicit",
            producer_kind="transcript",
            operation="set",
            mode="edit",
            confidence="high",
            evidence=["quote:user_message:test:transcript-checkpoint"],
        )
    ]

    decision = _decision(state=state, ui_language="sv")

    assert decision == RefuseArchitectureCommit(
        code=AIBuilderErrorCode.TRANSCRIPT_CHECKPOINT_REQUIRES_AUDIO,
        message=(
            "En granskningspunkt för transkribering kräver ljud som indata vid "
            "körning. Välj ljud som indata eller ta bort granskningen av "
            "transkriberingen och försök igen."
        ),
    )


def test_vague_purpose_question_survives_to_the_emitted_turn_decision() -> None:
    # The dispatch seam: with the primary input resolved and terminal output
    # still open, a discovery-selected vague purpose question must be the
    # question the user actually receives.
    state = _state(primary_runtime_input="documents")

    decision = _decision(
        state=state,
        ui_language="sv",
        selected_discovery_question_ids=("post_processing_goal",),
    )

    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "post_processing_goal"


def test_server_routes_renderable_non_slot_discovery_question() -> None:
    state = _state(primary_runtime_input="documents", terminal_output="text")

    decision = _decision(
        state=state,
        ui_language="en",
        selected_discovery_question_ids=("flow_input_architecture",),
    )

    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "flow_input_architecture"


def test_server_revises_architecture_before_asking_schema_direction() -> None:
    state = _state(
        primary_runtime_input="documents",
        terminal_output="structured_text",
        document_material_scope="flexible_document_case",
    )
    state.architecture_commit = _finalized_commit_for_state(state)
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    state.resolved_slots["pdf_generation_mode"] = _slot(
        "pdf_generation_mode",
        "generated_pdf",
    )
    candidates = (
        build_declared_schema_candidate(
            {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
            },
            source_file_ids=(UUID(int=1),),
            provenance=(f"file:{UUID(int=1)}:json_schema_attachment",),
        ),
    )

    revision = _turn_control(
        session_state=state,
        schema_candidates=candidates,
        schema_direction_pending=True,
    ).decision

    assert isinstance(revision, ReviseArchitecture)
    state.architecture_commit = finalize_architecture_commit(
        revision.architecture_commit,
        now=lambda: datetime(2026, 4, 24, tzinfo=timezone.utc),
    )

    question = _turn_control(
        session_state=state,
        schema_candidates=candidates,
        schema_direction_pending=True,
    ).decision

    assert isinstance(question, AskCanonicalQuestion)
    assert question.slot_name == "schema_direction"


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

    decision = _turn_control(
        session_state=PlanningState.empty(),
        selected_discovery_question_ids=(),
        confirmed_requirements_version=None,
        ui_language=ui_language,
        attachment_context=attachment_context,
        schema_candidates=candidates,
        schema_direction_pending=True,
    ).decision

    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "schema_direction"
    assert decision.question is not None
    question = decision.question
    # Dispatch numbers the question before persisting it, so the persisted
    # record this fixture stands in for carries a number.
    question_data = question.question_data.model_copy(update={"question_index": 1})
    tool_call = make_persisted_assistant_tool_call(
        tool_call_id="schema_direction",
        tool_name=ASK_STRUCTURED_QUESTION_TOOL_NAME,
        arguments=question_data.model_dump(
            mode="json",
            exclude_none=False,
            exclude_unset=True,
        ),
    )
    assistant_message = ConversationMessage(
        role="assistant",
        content=question.assistant_text,
        metadata=metadata_for_assistant_question(question_data),
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


def test_confirmation_survives_reclassification_churn() -> None:
    """The version attests to what the user saw, not to derivation traces.

    Live loop (text_terminal_intranatsnyhet_namndbeslut, 3/3): every turn's
    re-classification appended a fresh `model:file_role:<hash>` plus a
    duplicate quote to the file role's evidence, so the retired raw-state
    fingerprint moved every turn while the requirements payload stayed
    byte-identical. No confirmation could ever match, and the builder
    re-summarized the same requirements forever.
    """

    file_id = UUID("00000000-0000-0000-0000-000000000712")

    def role(evidence: list[str], confidence: str) -> FileRoleEvidence:
        return FileRoleEvidence(
            file_id=file_id,
            filename="protokoll.pdf",
            file_type="text",
            mimetype="application/pdf",
            has_readable_text=True,
            coverage="fully_seen",
            role="runtime_input_sample",
            source="model",
            confidence=confidence,
            evidence=evidence,
            evidence_level="explicit",
        )

    state = _state(primary_runtime_input="document", terminal_output="structured_text")
    state.architecture_commit = _finalized_commit_for_state(state)
    state.file_roles = [role(["quote:user_message:1:exempel"], "high")]
    confirmed = _turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_requirements_version=None,
        ui_language="sv",
    ).decision
    assert isinstance(confirmed, ConfirmRequirements)

    churned = _state(
        primary_runtime_input="document", terminal_output="structured_text"
    )
    churned.architecture_commit = _finalized_commit_for_state(churned)
    churned.file_roles = [
        role(
            [
                "quote:user_message:1:exempel",
                "model:file_role:aaaa",
                "quote:user_message:1:exempel",
                "model:file_role:bbbb",
            ],
            "medium",
        )
    ]

    decision = _turn_control(
        session_state=churned,
        selected_discovery_question_ids=(),
        confirmed_requirements_version=(confirmed.payload.requirements_version),
        ui_language="sv",
    ).decision

    assert not isinstance(decision, ConfirmRequirements)


def test_role_change_invalidates_confirmation() -> None:
    # The user confirmed a runtime-input sample; the file becoming a
    # template is a different fact and needs a fresh confirmation.
    file_id = UUID("00000000-0000-0000-0000-000000000713")

    def role(kind: str) -> FileRoleEvidence:
        return FileRoleEvidence(
            file_id=file_id,
            filename="protokoll.pdf",
            file_type="text",
            mimetype="application/pdf",
            has_readable_text=True,
            coverage="fully_seen",
            role=kind,
            source="model",
            confidence="high",
            evidence=["quote:user_message:1:exempel"],
            evidence_level="explicit",
        )

    state = _state(primary_runtime_input="document", terminal_output="structured_text")
    state.architecture_commit = _finalized_commit_for_state(state)
    state.file_roles = [role("runtime_input_sample")]
    confirmed = _turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_requirements_version=None,
        ui_language="sv",
    ).decision
    assert isinstance(confirmed, ConfirmRequirements)

    changed = _state(
        primary_runtime_input="document", terminal_output="structured_text"
    )
    changed.architecture_commit = _finalized_commit_for_state(changed)
    changed.file_roles = [role("template")]

    decision = _turn_control(
        session_state=changed,
        selected_discovery_question_ids=(),
        confirmed_requirements_version=(confirmed.payload.requirements_version),
        ui_language="sv",
    ).decision

    assert isinstance(decision, ConfirmRequirements)


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
        report_disposition="both",
        runtime_metadata_fields="no_extra_metadata",
    )
    state.resolved_slots["runtime_metadata_fields"] = _slot(
        "runtime_metadata_fields",
        "no_extra_metadata",
        source="policy_default",
        confidence="medium",
    )
    state.resolved_slots["post_processing_goal"] = _slot(
        "post_processing_goal",
        "structure_key_information",
        source="heuristic",
        confidence="medium",
    )
    state.architecture_commit = _finalized_commit_for_state(state)
    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ConfirmRequirements)
    payload = decision.payload
    assert payload.summary == (
        "Flödet ska ta emot Dokument vid körning och leverera DOCX-dokument. "
        "Resultatet ska hjälpa till med: Strukturera materialet."
    )
    assert payload.input_description == "Primär indata vid körning: Dokument."
    assert payload.output_description == "Huvudsakligt slutresultat: DOCX-dokument."
    assert {decision.topic for decision in payload.key_decisions} >= {
        "Word-resultat",
        "Indata vid körning",
        "Planerad bearbetning",
        "Slutresultat",
    }
    assert {decision.decision for decision in payload.key_decisions} >= {
        "Genererat Word-dokument utan mall",
        "Ibland ett, ibland flera dokument",
        "Skapa DOCX (ett resultat per underlag)",
    }
    assert {
        (row.question_id, row.topic, row.label) for row in payload.assumption_rows
    } >= {("post_processing_goal", "Syfte med bearbetningen", "Strukturera materialet")}
    assert {
        (row.question_id, row.value, row.topic, row.label)
        for row in payload.assumption_rows
    } >= {
        (
            "runtime_metadata_fields",
            "no_extra_metadata",
            render_summary_label("runtime_metadata_fields", "sv"),
            "Inga extra fält",
        )
    }
    assert (
        "Planen ska följa kraven och underlaget i konversationen."
        not in payload.assumptions
    )
    assert (
        "Användaren ska kunna granska och ändra planen innan den tillämpas."
        not in payload.assumptions
    )
    assert "Docx Output Mode" not in {
        decision.topic for decision in payload.key_decisions
    }
    assert {
        item.requirement_id: item.selected_value
        for item in payload.resolved_requirements
    } == {
        "document_material_scope": "flexible_document_case",
        "docx_output_mode": "generated_docx",
        "primary_runtime_input": "documents",
        "post_processing_goal": "structure_key_information",
        "report_disposition": "both",
        "runtime_metadata_fields": "no_extra_metadata",
        "terminal_output": "docx_document",
    }


def test_server_does_not_project_attachment_structure_as_confirmed_requirement() -> (
    None
):
    state = _state(
        primary_runtime_input="documents",
        terminal_output="docx_document",
        document_material_scope="single_document_case",
        docx_output_mode="template_fill_docx",
        runtime_metadata_fields="no_extra_metadata",
    )
    state.resolved_slots["docx_output_mode"] = _slot(
        "docx_output_mode",
        "template_fill_docx",
        source="attachment_structure",
    )
    state.file_roles = [
        FileRoleEvidence(
            file_id="00000000-0000-0000-0000-000000000701",
            filename="mall.docx",
            file_type="document",
            mimetype=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            has_readable_text=True,
            coverage="fully_seen",
            role="template",
            source="heuristic",
            confidence="high",
            template_placeholders=[],
        )
    ]
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ConfirmRequirements)
    assert "docx_output_mode" not in {
        item.requirement_id for item in decision.payload.resolved_requirements
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


@pytest.mark.parametrize(
    ("ui_language", "placement_text", "contract_text"),
    [
        (
            "sv",
            "De namngivna delarna byggs på översta nivån",
            "Typer, struktur och obligatoriska fält är inte fastställda.",
        ),
        (
            "en",
            "The named content is built at the top level",
            "Types, structure, and required fields are not fixed.",
        ),
    ],
)
def test_server_confirmation_distinguishes_named_results_from_full_schema(
    ui_language: str,
    placement_text: str,
    contract_text: str,
) -> None:
    state = _state(primary_runtime_input="text", terminal_output="structured_json")
    state.named_result_evidence = [
        NamedResultEvidence(
            name=name,
            confidence="high",
            evidence=["quote:user_message:user-1:case_id and status"],
        )
        for name in ("case_id", "status")
    ]
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(state=state, ui_language=ui_language)

    assert isinstance(decision, ConfirmRequirements)
    assert placement_text in decision.payload.summary
    assert [field.label for field in decision.payload.named_content_fields] == [
        "case_id",
        "status",
    ]
    assert contract_text not in decision.payload.summary


@pytest.mark.parametrize("ui_language", ["sv", "en"])
def test_server_confirmation_discloses_every_named_result_with_its_shape(
    ui_language: str,
) -> None:
    state = _state(primary_runtime_input="text", terminal_output="structured_json")
    state.named_result_evidence = [
        NamedResultEvidence(
            name=f"field_{index}",
            confidence="high",
            evidence=["quote:user_message:user-1:named result"],
            declared_shape="array" if index == 8 else None,
        )
        for index in range(9)
    ]
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(state=state, ui_language=ui_language)

    assert isinstance(decision, ConfirmRequirements)
    fields = decision.payload.named_content_fields
    assert [field.label.split(" (", 1)[0] for field in fields] == [
        f"field_{index}" for index in range(9)
    ]
    shape_text = (
        "field_8 (användaren skrev en lista)"
        if ui_language == "sv"
        else "field_8 (the user wrote a list)"
    )
    assert fields[-1].label == shape_text


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


def test_the_requirements_version_covers_nonvisible_example_evidence() -> None:
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
    first = _turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_requirements_version=None,
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
    second = _turn_control(
        session_state=changed,
        selected_discovery_question_ids=(),
        confirmed_requirements_version=(first.payload.requirements_version),
        ui_language="en",
    ).decision

    assert isinstance(second, ConfirmRequirements)
    assert second.payload.requirements_version != first.payload.requirements_version


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
        'Bilageunderlag – Bilaga "complete.docx" '
        f"(#{UUID('00000000-0000-0000-0000-000000000701')}): vald roll Mall; "
        "läsbar text: ja; "
        "täckning: hela den läsbara texten ingår." in assumption
        for assumption in swedish.payload.assumptions
    )
    assert any(
        'Bilageunderlag – Bilaga "not-excerpted.pdf" '
        f"(#{UUID('00000000-0000-0000-0000-000000000702')}): vald roll Referensmaterial; "
        "läsbar text: ja; täckning: läsbar text finns men "
        "inget utdrag ingår." in assumption
        for assumption in swedish.payload.assumptions
    )
    assert any(
        'Attachment evidence — Attachment "unreadable.bin" '
        f"(#{UUID('00000000-0000-0000-0000-000000000703')}): selected role Context only; "
        "readable text: no; coverage: no readable text is available." in assumption
        for assumption in english.payload.assumptions
    )


def test_server_confirmation_discloses_every_attachment_and_versions_coverage() -> None:
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
    assert len(attachment_assumptions) == 12
    assert all(long_filename not in assumption for assumption in attachment_assumptions)
    assert "…" in attachment_assumptions[0]
    assert all("fully_seen" not in assumption for assumption in attachment_assumptions)
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
    prior = _turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_requirements_version=None,
        ui_language="en",
    ).decision
    assert isinstance(prior, ConfirmRequirements)

    state.file_roles[11] = state.file_roles[11].model_copy(
        update={
            "coverage": "excerpt_truncated",
            "role": "reference_material",
        }
    )
    current = _turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_requirements_version=(prior.payload.requirements_version),
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
    prior = _turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_requirements_version=None,
        ui_language="en",
    ).decision
    assert isinstance(prior, ConfirmRequirements)

    state.file_roles[0] = state.file_roles[0].model_copy(
        update={
            "file_id": UUID(int=2),
            "filename": f"{shared_prefix}-second.txt",
        }
    )
    current = _turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_requirements_version=(prior.payload.requirements_version),
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


@pytest.mark.parametrize(
    ("ui_language", "topic", "decision_text"),
    [
        (
            "en",
            "Transcript review",
            "The transcript can be edited before the flow continues.",
        ),
        (
            "sv",
            "Granskning av transkribering",
            "Transkriberingen kan redigeras innan flödet fortsätter.",
        ),
    ],
)
def test_confirmation_exposes_committed_checkpoint_intent(
    ui_language: str,
    topic: str,
    decision_text: str,
) -> None:
    state = _state(
        primary_runtime_input="audio",
        terminal_output="structured_text",
        post_processing_goal="stop_after_primary_operation",
    )
    state.checkpoint_intents = [
        CheckpointIntent(
            evidence_level="explicit",
            producer_kind="transcript",
            operation="set",
            mode="edit",
            confidence="high",
            evidence=["quote:user_message:user-1:edit the transcript"],
        )
    ]
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(state=state, ui_language=ui_language)

    assert isinstance(decision, ConfirmRequirements)
    decisions = {item.topic: item.decision for item in decision.payload.key_decisions}
    assert decisions[topic] == decision_text


@pytest.mark.parametrize(
    ("ui_language", "decision_text"),
    [
        ("en", "The transcript review is removed at your request."),
        ("sv", "Granskningen av transkriberingen är borttagen på din begäran."),
    ],
)
def test_confirmation_exposes_requested_checkpoint_clear(
    ui_language: str,
    decision_text: str,
) -> None:
    state = _state(
        primary_runtime_input="audio",
        terminal_output="structured_text",
        post_processing_goal="stop_after_primary_operation",
    )
    state.checkpoint_intents = [
        CheckpointIntent(
            evidence_level="explicit",
            producer_kind="transcript",
            operation="clear",
            mode=None,
            confidence="high",
            evidence=["quote:user_message:user-1:remove the transcript review"],
        )
    ]
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(state=state, ui_language=ui_language)

    assert isinstance(decision, ConfirmRequirements)
    decisions = {item.topic: item.decision for item in decision.payload.key_decisions}
    assert decision_text in decisions.values()


def test_checkpoint_intent_change_requires_fresh_confirmation() -> None:
    state = _state(
        primary_runtime_input="audio",
        terminal_output="structured_text",
        post_processing_goal="stop_after_primary_operation",
    )
    state.checkpoint_intents = [
        CheckpointIntent(
            evidence_level="explicit",
            producer_kind="transcript",
            operation="set",
            mode="view",
            confidence="high",
            evidence=["quote:user_message:user-1:approve the transcript"],
        )
    ]
    state.architecture_commit = _finalized_commit_for_state(state)
    prior = _turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_requirements_version=None,
        ui_language="en",
    ).decision
    assert isinstance(prior, ConfirmRequirements)

    state.checkpoint_intents = [
        CheckpointIntent(
            evidence_level="explicit",
            producer_kind="transcript",
            operation="set",
            mode="edit",
            confidence="high",
            evidence=["quote:user_message:user-1:edit the transcript"],
        )
    ]
    current = _turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_requirements_version=(prior.payload.requirements_version),
        ui_language="en",
    ).decision

    assert isinstance(current, ConfirmRequirements)
    assert current.payload.requirements_version != prior.payload.requirements_version


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
    assert (
        decisions["Planerad bearbetning"]
        == "JSON till JSON (ett resultat per underlag)"
    )


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


def test_server_keeps_pinned_commit_when_only_weak_output_slot_conflicts() -> None:
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

    assert isinstance(decision, GenerateProposal)


def test_step_scoped_edit_uses_plan_review_instead_of_duplicate_confirmation() -> None:
    state = _state(primary_runtime_input="text", terminal_output="structured_text")
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        confirmed_requirements_version=None,
        ui_language="sv",
        requirements_confirmation_required=False,
    ).decision

    assert isinstance(decision, GenerateProposal)


def test_server_confirmation_uses_model_evidence_level_for_summary_bucket() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "audio"),
        "terminal_output": _slot(
            "terminal_output",
            "structured_text",
            source="model",
            confidence="high",
            evidence_level="explicit",
        ),
        "runtime_metadata_fields": _slot(
            "runtime_metadata_fields",
            "no_extra_metadata",
            source="flow_default",
        ),
        "post_processing_goal": _slot(
            "post_processing_goal",
            "summarize_or_overview",
            source="model",
            confidence="high",
            evidence_level="inferred",
        ),
    }
    state.resolved_slots["terminal_output"].evidence = [
        "quote:user_message:structured_text"
    ]
    state.resolved_slots["post_processing_goal"].evidence = [
        "quote:user_message:summarize_or_overview"
    ]
    state.architecture_commit = _finalized_commit_for_state(state)

    decision = _decision(state=state, ui_language="sv")

    assert isinstance(decision, ConfirmRequirements)
    decisions = {
        decision.topic: decision.decision for decision in decision.payload.key_decisions
    }
    assert "Indata vid körning" in decisions
    assert "Extra uppgifter vid körning" in decisions
    assert "Planerad bearbetning" in decisions
    assert "Slutresultat" in decisions
    assert "Syfte med bearbetningen" not in decisions
    assert "Slutresultat: Strukturerat textresultat" not in (
        decision.payload.assumptions
    )
    assert ("post_processing_goal", "Sammanfatta eller ge överblick") in {
        (row.question_id, row.label) for row in decision.payload.assumption_rows
    }


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
        "report_disposition": _slot(
            "report_disposition",
            "per_source_sections",
        ),
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
    source_to_slot: dict[SlotSource, tuple[str, str]] = {
        "structured_answer": ("primary_runtime_input", "audio"),
        "requirements_summary": ("terminal_output", "structured_text"),
        "flow_default": ("docx_output_mode", "generated_docx"),
        "attachment_structure": ("docx_output_mode", "template_fill_docx"),
        "policy_default": ("runtime_metadata_fields", "no_extra_metadata"),
        "heuristic": ("post_processing_goal", "summarize_or_overview"),
        "model": ("document_material_scope", "single_uploaded_document"),
    }
    bucket_by_source = {
        source: (
            "decision"
            if _slot_is_key_decision(_slot(slot_name, value, source=source))
            else "assumption"
        )
        for source, (slot_name, value) in source_to_slot.items()
    }

    assert set(source_to_slot) == set(get_args(SlotSource))
    assert bucket_by_source == {
        "structured_answer": "decision",
        # Confirming a disclosure may not move a fact between buckets: that
        # provenance is created by the confirmation itself, so promoting it
        # would rewrite the very record the user attested to.
        "requirements_summary": "assumption",
        "flow_default": "decision",
        "attachment_structure": "assumption",
        "policy_default": "assumption",
        "heuristic": "assumption",
        "model": "assumption",
    }
    assert _slot_is_key_decision(
        ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="model",
            confidence="high",
            evidence=["quote:user_message:test:structured_text"],
            evidence_level="explicit",
        )
    )
