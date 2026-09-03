"""Confirmation has one truth, and unchanged evidence keeps it.

A confirmed Builder session used to re-emit its requirements summary until the
interaction limit: the classifier re-read the same attachment every turn, its
wording moved, and both the hidden evidence fingerprint and the visible summary
moved with it, so the confirmation the user had just given could never match.

These tests pin the contract that replaced it — one versioned disclosure,
stable under re-derivation, complete enough that nothing plan-driving can
change behind it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    metadata_with_slot_classification,
    slot_classification_metadata_from_attempt,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_event_models import (
    RequirementsDisclosureContent,
    RequirementsSummaryPayload,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import FlowInputFieldIntent
from eneo.flows.ai_builder.ai_builder_requirements_disclosure import (
    build_requirements_disclosure,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    resolve_requirements_state,
)
from eneo.flows.ai_builder.ai_builder_result_contract import (
    RESULT_OBLIGATION_SIGNAL_ID,
)
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    ClassifiedEvidence,
    ClassifiedSlot,
    SlotClassificationAttempt,
    SlotClassificationConfidence,
    SlotClassificationInput,
    SlotClassificationSource,
)
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    ConfirmRequirements,
    GenerateProposal,
    resolve_turn_control,
)
from eneo.flows.ai_builder.planning_state import (
    ConfirmedRuntimeMetadataField,
    ExampleOutputCitation,
    ExampleOutputConstraintEvidence,
    ExampleOutputSourceCoverage,
    ExampleOutputStyleConstraint,
    FileRoleEvidence,
    MappedFileLimit,
    NamedResultEvidence,
    PlanningSignal,
    PlanningState,
    ResolvedSlot,
    SlotConfidence,
    SlotEvidenceLevel,
    SlotSource,
)
from eneo.flows.ai_builder.planning_state_builder import (
    apply_attested_requirements,
    apply_policy_defaults_from_resolved_slots,
    build_planning_state_from_conversation,
    merge_llm_resolved_slots,
)
from eneo.flows.ai_builder.question_catalog import render_question, render_summary_label
from eneo.flows.domain.flow import Flow, FlowStep
from tests.unittests.flows.ai_builder.slot_classification_test_support import (
    slot_classification_result,
)

_EXAMPLE_FILE = UUID("00000000-0000-0000-0000-0000000000e1")


def _slot(name: str, value: str) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source="structured_answer",
        confidence="high",
        evidence=[f"question_answer:{name}"],
    )


def _committed_state(**slots: str) -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots = {name: _slot(name, value) for name, value in slots.items()}
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    state.architecture_commit = finalize_architecture_commit(
        draft,
        now=lambda: datetime(2026, 8, 15, tzinfo=timezone.utc),
    )
    return state


def _document_state() -> PlanningState:
    return _committed_state(
        primary_runtime_input="documents",
        terminal_output="docx_document",
        docx_output_mode="generated_docx",
        document_material_scope="multiple_documents_case",
        post_processing_goal="structure_key_information",
        runtime_metadata_fields="no_extra_metadata",
    )


def _example_output_role(file_id: UUID = _EXAMPLE_FILE) -> FileRoleEvidence:
    return FileRoleEvidence(
        file_id=file_id,
        filename="example_report.docx",
        file_type="document",
        mimetype=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        has_readable_text=True,
        coverage="fully_seen",
        role="example_output",
        source="model",
        confidence="high",
        evidence=["quote:user_message:user-1:den bifogade exempelrapporten"],
        evidence_level="explicit",
    )


def _constraints(
    *,
    headings: list[str],
    style_description: str,
    file_id: UUID = _EXAMPLE_FILE,
) -> ExampleOutputConstraintEvidence:
    return ExampleOutputConstraintEvidence(
        source_file_ids=[file_id],
        source_coverage=[
            ExampleOutputSourceCoverage(file_id=file_id, coverage="fully_seen")
        ],
        headings=headings,
        style_constraints=[
            ExampleOutputStyleConstraint(
                category="organization",
                description=style_description,
            )
        ],
        confidence="medium",
        citations=[
            ExampleOutputCitation(
                source_id=f"uploaded_file:{file_id}",
                file_id=file_id,
                quote="Samlad bedömning",
            )
        ],
    )


def _decide(
    state: PlanningState,
    *,
    confirmed_version: str | None = None,
) -> object:
    disclosure = build_requirements_disclosure(state, ui_language="sv")
    return resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        requirements_disclosure=disclosure,
        confirmed_requirements_version=confirmed_version,
        ui_language="sv",
    ).decision


def _flow_observed_document_state() -> PlanningState:
    """A DOCX Flow being edited, before the user has said anything about it."""

    state = PlanningState.empty()
    state.resolved_slots = {
        name: ResolvedSlot(
            name=name,
            value=value,
            source="flow_default",
            confidence="high",
            evidence=[f"flow_default:{name}"],
        )
        for name, value in (
            ("primary_runtime_input", "documents"),
            ("terminal_output", "docx_document"),
            ("docx_output_mode", "generated_docx"),
            ("runtime_metadata_fields", "no_extra_metadata"),
        )
    }
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    state.architecture_commit = finalize_architecture_commit(
        draft,
        now=lambda: datetime(2026, 8, 17, tzinfo=timezone.utc),
    )
    return state


def test_settled_but_unanswered_slots_are_reopenable_rows_and_non_slot_facts_stay_prose() -> (
    None
):
    state = _document_state()
    state.resolved_slots["document_material_scope"] = ResolvedSlot(
        name="document_material_scope",
        value="flexible_document_case",
        source="policy_default",
        confidence="medium",
        evidence=["policy_default:document_material_scope=flexible_document_case"],
    )
    state.resolved_slots["docx_output_mode"] = ResolvedSlot(
        name="docx_output_mode",
        value="generated_docx",
        source="policy_default",
        confidence="medium",
        evidence=["policy_default:docx_output_mode=generated_docx"],
    )
    state.resolved_slots["report_disposition"] = ResolvedSlot(
        name="report_disposition",
        value="both",
        source="heuristic",
        confidence="medium",
        evidence=["heuristic:report_disposition=both"],
    )
    state.mapped_file_limit = MappedFileLimit(
        accepted_value=7,
        provenance="policy_default",
    )

    disclosed = build_requirements_disclosure(state, ui_language="en")

    def option_label(slot_name: str) -> str:
        return next(
            option.label
            for option in render_question(slot_name, "en").options
            if option.value == state.resolved_slots[slot_name].value
        )

    # Every settled-but-unanswered catalog slot is a row: a policy default, a
    # heuristic reading; the row carries no provenance.
    rows = {row.question_id: row for row in disclosed.assumption_rows}
    assert set(rows) >= {
        "document_material_scope",
        "docx_output_mode",
        "report_disposition",
    }
    for slot_name in (
        "document_material_scope",
        "docx_output_mode",
        "report_disposition",
    ):
        assert rows[slot_name].model_dump() == {
            "question_id": slot_name,
            "slot_name": slot_name,
            "value": state.resolved_slots[slot_name].value,
            "topic": render_summary_label(slot_name, "en"),
            "label": option_label(slot_name),
        }
    # Non-slot facts stay prose, and no slot is told twice.
    assert any("At most 7 files" in assumption for assumption in disclosed.assumptions)
    assert not any(
        rows[slot_name].label in assumption
        for slot_name in rows
        for assumption in disclosed.assumptions
    )

    changed_non_slot_fact = state.model_copy(deep=True)
    changed_non_slot_fact.mapped_file_limit = MappedFileLimit(
        accepted_value=8,
        provenance="policy_default",
    )
    assert (
        build_requirements_disclosure(
            changed_non_slot_fact,
            ui_language="en",
        ).requirements_version
        != disclosed.requirements_version
    )


def test_answering_a_reopened_question_replaces_the_assumption_and_moves_version() -> (
    None
):
    assumed = PlanningState.empty()
    assumed.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input", "documents"
    )
    apply_policy_defaults_from_resolved_slots(assumed, freeform_text="")
    before = build_requirements_disclosure(assumed, ui_language="en")
    assert [row.question_id for row in before.assumption_rows] == [
        "comparison_scope",
        "document_material_scope",
        "runtime_metadata_fields",
    ]

    conversation = [
        ConversationMessage(
            role="user",
            content="",
            metadata={
                "question_answer": {
                    "question_id": "primary_runtime_input",
                    "selected_value": "documents",
                }
            },
        ),
        ConversationMessage(
            role="user",
            content="",
            metadata={
                "reopen_question": {
                    "question_id": "document_material_scope",
                    "requirements_version": before.requirements_version,
                }
            },
        ),
        ConversationMessage(
            role="assistant",
            content="How many documents can each run receive?",
            metadata={"question_id": "document_material_scope"},
        ),
        ConversationMessage(
            role="user",
            content="",
            metadata={
                "question_answer": {
                    "question_id": "document_material_scope",
                    "selected_value": "single_document_case",
                }
            },
        ),
    ]

    rebuilt = build_planning_state_from_conversation(conversation)
    after = build_requirements_disclosure(rebuilt, ui_language="en")

    assert rebuilt.resolved_slots["document_material_scope"].source == (
        "structured_answer"
    )
    assert after.assumption_rows == []
    assert after.requirements_version != before.requirements_version


def test_confirming_the_card_accepts_its_assumptions_as_the_users_answer() -> None:
    """An assumption is reopenable until the card is confirmed, not after.

    Accepting the card accepts the row with everything else: the value becomes
    the user's own answer, and the record the user accepted re-renders
    unchanged, rows included, so the version does not move on acceptance.
    """

    assumed = PlanningState.empty()
    assumed.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input", "documents"
    )
    apply_policy_defaults_from_resolved_slots(assumed, freeform_text="")
    disclosed = build_requirements_disclosure(assumed, ui_language="en")
    assert [row.question_id for row in disclosed.assumption_rows] == [
        "comparison_scope",
        "document_material_scope",
        "runtime_metadata_fields",
    ]

    confirmed = assumed.model_copy(deep=True)
    apply_attested_requirements(confirmed, disclosed)

    assert confirmed.resolved_slots["document_material_scope"].source == (
        "requirements_summary"
    )
    assert build_requirements_disclosure(confirmed, ui_language="en") == disclosed


def test_replacing_the_flow_output_withdraws_the_confirmation_it_contradicts() -> None:
    """The reported defect: the summary quoted the request and kept DOCX.

    Editing a DOCX Flow, the user wrote that they want a PDF instead. The
    disclosure repeated the sentence back while every decision under it still
    said DOCX, and the turn proposed a plan against the confirmed DOCX
    requirements. A requirement the user replaces is a different disclosure,
    and a different disclosure is not the one they confirmed.
    """

    state = _flow_observed_document_state()
    disclosed = build_requirements_disclosure(
        state, ui_language="sv", is_edit_mode=True
    )
    assert isinstance(
        _decide(state, confirmed_version=disclosed.requirements_version),
        GenerateProposal,
    )

    merge_llm_resolved_slots(
        state,
        slot_classification_result(
            slots=(
                ClassifiedSlot(
                    slot_name="terminal_output",
                    value="pdf_document",
                    confidence="high",
                    reason="The user asked for a PDF instead of the DOCX.",
                    evidence=(
                        ClassifiedEvidence(
                            source_id="user_message:user-1",
                            quote="PDF fil istället som utdata än en docx fil",
                        ),
                    ),
                    evidence_level="explicit",
                ),
            )
        ),
        prompt_hash="d" * 64,
        freeform_text="Jag vill ha en PDF fil istället som utdata än en docx fil.",
    )

    revised = build_requirements_disclosure(state, ui_language="sv", is_edit_mode=True)
    assert revised.requirements_version != disclosed.requirements_version
    assert {
        requirement.selected_value
        for requirement in revised.resolved_requirements
        if requirement.requirement_id == "terminal_output"
    } == {"pdf_document"}
    assert not isinstance(
        _decide(state, confirmed_version=disclosed.requirements_version),
        GenerateProposal,
    )


def _docx_flow() -> Flow:
    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Strukturerad samtalsrapport",
        description="Befintligt dokumentflöde",
        steps=[
            FlowStep(
                assistant_id=uuid4(),
                step_order=1,
                user_description="Läs underlaget",
                input_source="flow_input",
                input_type="document",
                output_mode="pass_through",
                output_type="text",
            ),
            FlowStep(
                assistant_id=uuid4(),
                step_order=2,
                user_description="Skapa DOCX",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="docx",
            ),
        ],
    )


def _post_plan_conversation(
    disclosed: RequirementsSummaryPayload,
    *,
    last_user_message: str,
    last_user_metadata: dict[str, object] | None = None,
) -> list[ConversationMessage]:
    return [
        ConversationMessage(role="user", content="Behåll flödet som det är."),
        ConversationMessage(
            role="assistant",
            content=disclosed.summary,
            metadata={
                "requirements_summary": disclosed.model_dump(mode="json"),
                "requirements_version": disclosed.requirements_version,
            },
        ),
        ConversationMessage(
            role="user",
            content="",
            metadata={
                "requirements_confirmed": True,
                "requirements_version": disclosed.requirements_version,
            },
        ),
        ConversationMessage(
            role="assistant",
            content="Här är planen.",
            tool_calls=[
                {
                    "id": "call_plan",
                    "name": PROPOSE_FLOW_TOOL_NAME,
                    "arguments": {"flow_name": "Strukturerad samtalsrapport"},
                }
            ],
        ),
        ConversationMessage(
            role="tool",
            content="Draft saved.",
            tool_call_id="call_plan",
        ),
        ConversationMessage(
            role="user",
            content=last_user_message,
            metadata=last_user_metadata,
        ),
    ]


def _edit_disclosure(
    conversation: list[ConversationMessage],
) -> RequirementsSummaryPayload:
    return build_requirements_disclosure(
        build_planning_state_from_conversation(conversation, flow=_docx_flow()),
        ui_language="sv",
        is_edit_mode=True,
    )


def _disclosed_terminal_output(disclosure: RequirementsSummaryPayload) -> set[str]:
    return {
        requirement.selected_value
        for requirement in disclosure.resolved_requirements
        if requirement.requirement_id == "terminal_output"
    }


def test_a_post_plan_replacement_reaches_the_disclosure_the_user_must_reconfirm() -> (
    None
):
    """The confirmation is withdrawn by a changed requirement, not by wording.

    Nine hard-coded phrases used to decide this, and the accepted DOCX also
    outranked the reading of the very message that replaced it, so the plan was
    revised for the old artifact. The comparison that replaced the phrases is
    typed: the disclosure is derived from the conversation each turn, and a
    confirmation names exactly one version of it.
    """

    disclosed = _edit_disclosure([])
    assert _disclosed_terminal_output(disclosed) == {"docx_document"}

    conversation = _post_plan_conversation(
        disclosed,
        last_user_message="Jag vill ha en PDF fil istället som utdata än en docx fil.",
    )
    # The citation names the message the user just sent, which is what makes it
    # newer than the acceptance rather than a re-reading of it.
    conversation[-1] = conversation[-1].model_copy(
        update={
            "metadata": _classifier_metadata(
                _classified(
                    "terminal_output",
                    "pdf_document",
                    "high",
                    "PDF fil istället som utdata än en docx fil",
                    cited_message_id=conversation[-1].message_id,
                )
            )
        }
    )

    revised = _edit_disclosure(conversation)
    assert _disclosed_terminal_output(revised) == {"pdf_document"}
    assert revised.requirements_version != disclosed.requirements_version
    assert (
        resolve_requirements_state(conversation).confirmed_requirements_version
        == disclosed.requirements_version
    )


def test_a_post_plan_revision_keeps_the_confirmation_it_did_not_touch() -> None:
    """The confirm-stability contract: a revision request is not a new demand.

    Asking for the same requirements to be confirmed again for every revision
    is what ran a confirmed session into the interaction limit.
    """

    disclosed = _edit_disclosure([])
    conversation = _post_plan_conversation(
        disclosed,
        last_user_message="Gör steg 2 kortare.",
    )

    revised = _edit_disclosure(conversation)
    assert revised.requirements_version == disclosed.requirements_version
    assert (
        resolve_requirements_state(conversation).confirmed_requirements_version
        == disclosed.requirements_version
    )


def test_reclassifying_unchanged_example_evidence_keeps_the_confirmation() -> None:
    """The measured defect: same file, same coverage, reworded interpretation.

    In the sealed 158x3 run the model returned "Behåll den synliga
    källhänvisningen" on one turn and "Behåll synliga källhänvisningar" on the
    next, then dropped two of three headings, then returned them in English.
    Every wording change produced a new requirements version.
    """

    state = _document_state()
    state.file_roles = [_example_output_role()]
    state.example_output_constraints = _constraints(
        headings=["Källa 1", "Källa 2", "Samlad bedömning"],
        style_description="Ett avsnitt per källa följt av en samlad bedömning.",
    )
    confirmed = _decide(state)
    assert isinstance(confirmed, ConfirmRequirements)
    confirmed_version = confirmed.payload.requirements_version
    assert confirmed_version is not None

    merge_llm_resolved_slots(
        state,
        slot_classification_result(
            example_output_constraints=_constraints(
                headings=["Samlad bedömning"],
                style_description="Use one section per source.",
            )
        ),
        prompt_hash="a" * 64,
        freeform_text="",
    )

    assert isinstance(
        _decide(state, confirmed_version=confirmed_version), GenerateProposal
    )


def test_new_example_evidence_replaces_the_interpretation_and_invalidates() -> None:
    """Preservation is scoped to unchanged evidence, never to changed evidence."""

    other_file = UUID("00000000-0000-0000-0000-0000000000e2")
    state = _document_state()
    state.file_roles = [_example_output_role(), _example_output_role(other_file)]
    state.example_output_constraints = _constraints(
        headings=["Samlad bedömning"],
        style_description="Ett avsnitt per källa.",
    )
    confirmed = _decide(state)
    assert isinstance(confirmed, ConfirmRequirements)

    merge_llm_resolved_slots(
        state,
        slot_classification_result(
            example_output_constraints=_constraints(
                headings=["Ny rubrik"],
                style_description="En annan struktur.",
                file_id=other_file,
            )
        ),
        prompt_hash="b" * 64,
        freeform_text="",
    )

    reconfirmed = _decide(
        state,
        confirmed_version=confirmed.payload.requirements_version,
    )
    assert isinstance(reconfirmed, ConfirmRequirements)
    assert (
        reconfirmed.payload.requirements_version
        != confirmed.payload.requirements_version
    )


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda state: state.example_output_constraints.headings.append("Rubrik 9"),
            id="ninth example heading",
        ),
        pytest.param(
            lambda state: state.example_output_constraints.style_constraints.append(
                ExampleOutputStyleConstraint(category="tone", description="Saklig.")
            ),
            id="seventh style constraint",
        ),
        pytest.param(
            lambda state: state.file_roles.__setitem__(
                10,
                state.file_roles[10].model_copy(update={"role": "template"}),
            ),
            id="eleventh attachment role",
        ),
        pytest.param(
            lambda state: state.named_result_evidence.__setitem__(
                0,
                state.named_result_evidence[0].model_copy(
                    update={"declared_shape": "array"}
                ),
            ),
            id="named result declared shape",
        ),
    ],
)
def test_a_hidden_plan_driving_change_invalidates_the_confirmation(mutate) -> None:
    """Nothing that can change the plan may hide behind a stale confirmation.

    Each of these once sat outside the visible summary — beyond the tenth
    attachment, the eighth heading, the sixth style constraint, or inside a
    named result whose shape the summary never showed.
    """

    state = _document_state()
    state.file_roles = [
        FileRoleEvidence(
            file_id=UUID(int=index + 1),
            filename=f"bilaga-{index}.txt",
            file_type="text",
            mimetype="text/plain",
            has_readable_text=True,
            coverage="fully_seen",
            role="reference_material",
            source="model",
            confidence="high",
            evidence=["quote:user_message:user-1:bilagan"],
            evidence_level="explicit",
        )
        for index in range(12)
    ]
    state.file_roles.append(_example_output_role())
    state.example_output_constraints = _constraints(
        headings=[f"Rubrik {index}" for index in range(8)],
        style_description="Ett avsnitt per källa.",
    )
    state.example_output_constraints.style_constraints.extend(
        ExampleOutputStyleConstraint(
            category="detail_level",
            description=f"Detaljnivå {index}.",
        )
        for index in range(5)
    )
    state.named_result_evidence = [
        NamedResultEvidence(
            name="sokta_insatser",
            confidence="high",
            evidence=["quote:user_message:user-1:sökta insatser"],
        )
    ]

    confirmed = _decide(state)
    assert isinstance(confirmed, ConfirmRequirements)
    mutate(state)

    reconfirmed = _decide(
        state,
        confirmed_version=confirmed.payload.requirements_version,
    )
    assert isinstance(reconfirmed, ConfirmRequirements)
    assert (
        reconfirmed.payload.requirements_version
        != confirmed.payload.requirements_version
    )


def test_attachment_provenance_alone_does_not_invalidate() -> None:
    """A different citation for the same role is not a different plan."""

    state = _document_state()
    state.file_roles = [_example_output_role()]
    state.example_output_constraints = _constraints(
        headings=["Samlad bedömning"],
        style_description="Ett avsnitt per källa.",
    )
    confirmed = _decide(state)
    assert isinstance(confirmed, ConfirmRequirements)

    state.file_roles[0] = state.file_roles[0].model_copy(
        update={
            "evidence": ["quote:user_message:user-2:en annan formulering"],
            "confidence": "medium",
            "candidate_roles": ["reference_material"],
        }
    )

    assert isinstance(
        _decide(state, confirmed_version=confirmed.payload.requirements_version),
        GenerateProposal,
    )


def test_the_disclosure_is_a_pure_function_of_planning_state() -> None:
    """Rendering twice from one state yields one payload and one version."""

    state = _document_state()
    state.file_roles = [_example_output_role()]
    state.example_output_constraints = _constraints(
        headings=["Samlad bedömning"],
        style_description="Ett avsnitt per källa.",
    )

    first = build_requirements_disclosure(state, ui_language="sv")
    second = build_requirements_disclosure(state, ui_language="sv")

    assert first == second
    assert first.requirements_version is not None


def _report_disposition_slot(
    *,
    source: SlotSource,
    confidence: SlotConfidence,
    evidence_level: SlotEvidenceLevel | None,
) -> ResolvedSlot:
    evidence = (
        ["quote:user_message:user-1:en samlad rapport"]
        if source == "model"
        else [f"{source}:report_disposition"]
    )
    return ResolvedSlot(
        name="report_disposition",
        value="synthesized_overview",
        source=source,
        confidence=confidence,
        evidence=evidence,
        evidence_level=evidence_level,
    )


@pytest.mark.parametrize(
    ("source", "confidence", "evidence_level"),
    [
        ("model", "high", "explicit"),
        ("model", "high", "inferred"),
        ("model", "medium", "explicit"),
        ("model", "medium", "inferred"),
        ("heuristic", "high", None),
        ("heuristic", "medium", None),
        ("heuristic", "low", None),
        ("policy_default", "medium", None),
        ("requirements_summary", "high", None),
        ("structured_answer", "high", None),
        ("flow_default", "high", None),
        ("attachment_structure", "high", None),
    ],
)
def test_accepting_a_disclosure_does_not_change_that_disclosure(
    source: SlotSource,
    confidence: SlotConfidence,
    evidence_level: SlotEvidenceLevel | None,
) -> None:
    """Confirmation is a fixed point, for every grade a slot can carry.

    Accepting a disclosure makes its inferred values the user's own answer,
    which is what lets them drive the architecture. It is also the only thing
    that changed, so re-rendering has to yield the same record. When acceptance
    instead moved a fact from an assumption to a key decision, the server
    disclosed a new version of what the user had just accepted and asked again,
    every turn, until the interaction limit — so the bucket boundary and the
    attestation precedence boundary have to agree on every combination, not
    just the one that was measured.
    """

    state = _document_state()
    state.resolved_slots["report_disposition"] = _report_disposition_slot(
        source=source,
        confidence=confidence,
        evidence_level=evidence_level,
    )
    disclosed = build_requirements_disclosure(state, ui_language="sv")

    accepted = state.model_copy(deep=True)
    apply_attested_requirements(accepted, disclosed)

    assert build_requirements_disclosure(accepted, ui_language="sv") == disclosed


def test_accepting_an_inferred_requirement_admits_it_to_the_architecture() -> None:
    """Acceptance is not cosmetic: it is what makes the value commit-grade.

    Only commit-grade facts reach the architecture commit, and the compiler
    reads the report disposition from there and nowhere else.
    """

    state = _document_state()
    state.resolved_slots["report_disposition"] = _report_disposition_slot(
        source="model",
        confidence="medium",
        evidence_level="inferred",
    )
    assert state.commit_grade_slot_value("report_disposition") is None

    apply_attested_requirements(
        state,
        build_requirements_disclosure(state, ui_language="sv"),
    )

    assert state.commit_grade_slot_value("report_disposition") == "synthesized_overview"
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    assert draft.report_disposition == "synthesized_overview"


def test_a_later_disclosure_does_not_withdraw_what_was_already_accepted() -> None:
    """A pending disclosure supersedes the pending one, not the accepted one.

    A changed policy or attachment earns a new disclosure mid-session. While it
    waits for an answer, the facts the user accepted earlier still hold: the
    architecture was pinned from them, so dropping them makes the next commit
    look like the model re-authored the architecture.
    """

    disclosed = build_requirements_disclosure(_document_state(), ui_language="sv")
    conversation = [
        ConversationMessage(role="user", content="Bygg ett dokumentflöde."),
        ConversationMessage(
            role="assistant",
            content=disclosed.summary,
            metadata={
                "requirements_summary": disclosed.model_dump(mode="json"),
                "requirements_version": disclosed.requirements_version,
            },
        ),
        ConversationMessage(
            role="user",
            content="",
            metadata={
                "requirements_confirmed": True,
                "requirements_version": disclosed.requirements_version,
            },
        ),
    ]
    assert resolve_requirements_state(conversation).attested_summary == disclosed

    superseded = [
        *conversation,
        ConversationMessage(
            role="assistant",
            content="Ny sammanfattning",
            metadata={
                "requirements_summary": disclosed.model_copy(
                    update={"requirements_version": "b" * 64}
                ).model_dump(mode="json"),
                "requirements_version": "b" * 64,
            },
        ),
    ]
    state = resolve_requirements_state(superseded)

    assert not state.confirmed
    assert state.attested_summary == disclosed


def test_a_user_revision_over_the_same_attachment_replaces_the_interpretation() -> None:
    """Preservation recognises new user evidence, not only new files.

    The user can say "drop the summary section" about the same attachment. That
    is a new citation, so the interpretation must move even though the files
    and their coverage did not.
    """

    state = _document_state()
    state.file_roles = [_example_output_role()]
    state.example_output_constraints = _constraints(
        headings=["Källa 1", "Samlad bedömning"],
        style_description="Ett avsnitt per källa.",
    )
    confirmed = _decide(state)
    assert isinstance(confirmed, ConfirmRequirements)

    revised = _constraints(
        headings=["Källa 1"],
        style_description="Ingen samlad bedömning.",
    )
    revised.citations.append(
        ExampleOutputCitation(
            source_id="user_message:user-2",
            quote="ta bort den samlade bedömningen",
        )
    )
    merge_llm_resolved_slots(
        state,
        slot_classification_result(example_output_constraints=revised),
        prompt_hash="c" * 64,
        freeform_text="",
    )

    assert state.example_output_constraints == revised
    reconfirmed = _decide(
        state,
        confirmed_version=confirmed.payload.requirements_version,
    )
    assert isinstance(reconfirmed, ConfirmRequirements)


def test_values_that_clip_alike_are_still_different_disclosures() -> None:
    """Display may clip evidence; identity may not.

    The summary clips long evidence values so it stays readable. Two template
    placeholders that share their first 79 characters therefore render
    identically, while the compiled runtime fields they produce differ.
    """

    shared_prefix = "beslut_om_insats_enligt_socialtjanstlagen_kapitel_fyra_paragraf_ett_for_persona"
    assert len(shared_prefix) == 79

    def _disclosure_for(placeholder_tail: str) -> RequirementsSummaryPayload:
        state = _document_state()
        state.file_roles = [
            FileRoleEvidence(
                file_id=_EXAMPLE_FILE,
                filename="mall.docx",
                file_type="document",
                mimetype=(
                    "application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"
                ),
                has_readable_text=True,
                coverage="fully_seen",
                role="template",
                source="model",
                confidence="high",
                evidence=["quote:user_message:user-1:mallen"],
                evidence_level="explicit",
                template_placeholders=[f"{shared_prefix}{placeholder_tail}"],
            )
        ]
        return build_requirements_disclosure(state, ui_language="sv")

    first = _disclosure_for("n_som_ansoker")
    second = _disclosure_for("n_som_overklagar")

    assert first.assumptions == second.assumptions
    assert first.requirements_version != second.requirements_version


def test_values_that_join_alike_are_still_different_disclosures() -> None:
    """A list is composed into one line, so its members keep their boundaries.

    Every heading reaches proposal section preparation, so ["A, B", "C"] and
    ["A", "B, C"] are two different plans behind one sentence.
    """

    def _disclosure_for(headings: list[str]) -> RequirementsSummaryPayload:
        state = _document_state()
        state.file_roles = [_example_output_role()]
        state.example_output_constraints = _constraints(
            headings=headings,
            style_description="Ett avsnitt per källa.",
        )
        return build_requirements_disclosure(state, ui_language="sv")

    first = _disclosure_for(["Källa 1, Källa 2", "Samlad bedömning"])
    second = _disclosure_for(["Källa 1", "Källa 2, Samlad bedömning"])

    assert first.assumptions == second.assumptions
    assert first.requirements_version != second.requirements_version


def _classifier_metadata(*slots: ClassifiedSlot) -> dict[str, object]:
    quotes_by_source: dict[str, list[str]] = {}
    for slot in slots:
        for item in slot.evidence:
            quotes_by_source.setdefault(item.source_id, []).append(item.quote)
    metadata = slot_classification_metadata_from_attempt(
        SlotClassificationAttempt(
            outcome="resolved",
            result=slot_classification_result(slots=slots),
        ),
        prompt_hash="c" * 64,
        classification_input=SlotClassificationInput(
            sources=tuple(
                SlotClassificationSource(
                    source_id=source_id,
                    kind="user_message",
                    text="\n".join(quotes),
                    message_id=source_id.removeprefix("user_message:"),
                )
                for source_id, quotes in quotes_by_source.items()
            )
        ),
        model="openai/gpt-test",
        provider="openai",
    )
    assert metadata is not None
    conversation_metadata = metadata_with_slot_classification(None, metadata)
    assert conversation_metadata is not None
    return conversation_metadata


def _classified(
    slot_name: str,
    value: str,
    confidence: SlotClassificationConfidence,
    quote: str,
    *,
    cited_message_id: str = "user-1",
) -> ClassifiedSlot:
    return ClassifiedSlot(
        slot_name=slot_name,
        value=value,
        confidence=confidence,
        reason="Classifier evidence.",
        evidence=(
            ClassifiedEvidence(
                source_id=f"user_message:{cited_message_id}",
                quote=quote,
            ),
        ),
    )


def _interview_conversation_before_disclosure() -> list[ConversationMessage]:
    """A multi-question interview whose scope facts live only in the classifier.

    The deterministic pass cannot see how many documents arrive at runtime:
    only the persisted classifier metadata says so. That is what makes the
    report disposition unresolvable until after the replay, which is the shape
    every measured failure had.
    """

    return [
        ConversationMessage(
            message_id="user-1",
            role="user",
            content=(
                "Vi sitter ofta med många anbud och mycket underlag och vill ha "
                "en samlad överblick i en PDF."
            ),
            metadata=_classifier_metadata(
                _classified(
                    "document_material_scope",
                    "multiple_documents_case",
                    "high",
                    "många anbud och mycket underlag",
                ),
                _classified(
                    "report_disposition",
                    "synthesized_overview",
                    "medium",
                    "en samlad överblick",
                ),
            ),
        ),
        ConversationMessage(
            message_id="answer-input",
            role="user",
            content="Dokument",
            metadata={
                "question_answer": {
                    "question_id": "primary_runtime_input",
                    "selected_option_id": "documents",
                }
            },
        ),
        ConversationMessage(
            message_id="answer-goal",
            role="user",
            content="Sammanfatta eller ge överblick",
            metadata={
                "question_answer": {
                    "question_id": "post_processing_goal",
                    "selected_option_id": "summarize_or_overview",
                }
            },
        ),
        ConversationMessage(
            message_id="answer-output",
            role="user",
            content="PDF-dokument",
            metadata={
                "question_answer": {
                    "question_id": "terminal_output",
                    "selected_option_id": "pdf_document",
                }
            },
        ),
    ]


def test_the_rebuild_pins_the_same_architecture_the_acknowledgment_committed() -> None:
    """The commit the fast path pins must survive its own conversation rebuild.

    The acknowledgment resolves from persisted state and regrades what the user
    accepted; `commit_turn` then rebuilds the same session from its persisted
    conversation and refuses to store an architecture that drifted. When only
    the fast path applied the acceptance, the two disagreed about the report
    disposition and every confirmation turn on a multi-question session failed
    with an internal error instead of a plan.
    """

    conversation = _interview_conversation_before_disclosure()
    disclosed = build_requirements_disclosure(
        build_planning_state_from_conversation(conversation),
        ui_language="sv",
    )
    conversation.append(
        ConversationMessage(
            message_id="disclosure",
            role="assistant",
            content=disclosed.summary,
            metadata={
                "requirements_summary": disclosed.model_dump(mode="json"),
                "requirements_version": disclosed.requirements_version,
            },
        )
    )
    persisted = build_planning_state_from_conversation(conversation)
    conversation.append(
        ConversationMessage(
            message_id="confirmation",
            role="user",
            content="",
            metadata={
                "requirements_confirmed": True,
                "requirements_version": disclosed.requirements_version,
            },
        )
    )

    acknowledged = persisted.model_copy(deep=True)
    apply_attested_requirements(acknowledged, disclosed)
    pinned = derive_architecture_commit_draft(acknowledged)
    assert pinned is not None
    assert pinned.report_disposition == "synthesized_overview"

    rebuilt = build_planning_state_from_conversation(conversation)

    assert derive_architecture_commit_draft(rebuilt) == pinned


def _accepted_audio_conversation(
    *,
    confirmation_metadata: dict[str, object] | None = None,
) -> tuple[
    list[ConversationMessage],
    RequirementsSummaryPayload,
]:
    """One open prompt, its disclosure accepted, and the plan it produced.

    The prompt names both a structured payload and a Word document, so the
    terminal output is inferred rather than answered — which is the only kind
    of value acceptance has to protect, and the kind an open prompt produces.
    """

    conversation = [
        ConversationMessage(
            message_id="user-1",
            role="user",
            content=(
                "Ladda upp mötesljud, ta fram beslut och åtgärder, och ge "
                "resultatet både som strukturerad JSON och som ett "
                "protokollsutkast i Word-format."
            ),
            metadata=_classifier_metadata(
                _classified("primary_runtime_input", "audio", "high", "mötesljud"),
                _classified(
                    "terminal_output",
                    "docx_document",
                    "high",
                    "protokollsutkast i Word-format",
                ),
                _classified(
                    "post_processing_goal",
                    "action_followup",
                    "high",
                    "beslut och åtgärder",
                ),
            ),
        ),
    ]
    disclosed = build_requirements_disclosure(
        build_planning_state_from_conversation(conversation),
        ui_language="sv",
    )
    conversation.extend(
        [
            ConversationMessage(
                message_id="disclosure",
                role="assistant",
                content=disclosed.summary,
                metadata={
                    "requirements_summary": disclosed.model_dump(mode="json"),
                    "requirements_version": disclosed.requirements_version,
                },
            ),
            ConversationMessage(
                message_id="confirmation",
                role="user",
                content="",
                metadata={
                    **(confirmation_metadata or {}),
                    "requirements_confirmed": True,
                    "requirements_version": disclosed.requirements_version,
                },
            ),
            ConversationMessage(
                message_id="plan",
                role="assistant",
                content="",
                tool_calls=[{"id": "call-1", "name": "propose_flow", "arguments": {}}],
            ),
        ]
    )
    return conversation, disclosed


def test_rereading_the_accepted_prompt_does_not_move_the_accepted_output() -> None:
    """Acceptance is a fact about the user, not a grade a later reading beats.

    The prompt asks for both a JSON payload and a Word document, so a fresh
    reading of that same sentence can land on either. Once the user has
    accepted the disclosure that named the document, re-reading the sentence
    they already answered is not them changing their mind: it silently rebuilt
    the flow around the other reading and then asked them to attest to a
    substitution they never requested.
    """

    conversation, disclosed = _accepted_audio_conversation()
    conversation.append(
        ConversationMessage(
            message_id="user-2",
            role="user",
            content="Lägg till mötesdatum i rubriken.",
            metadata=_classifier_metadata(
                _classified(
                    "terminal_output",
                    "structured_json",
                    "high",
                    "strukturerad JSON",
                ),
            ),
        )
    )

    rebuilt = build_planning_state_from_conversation(conversation)

    assert rebuilt.resolved_slots["terminal_output"].value == "docx_document"
    draft = derive_architecture_commit_draft(rebuilt)
    assert draft is not None
    assert draft.tuples_chain[-1].output_type.value == "docx"
    assert (
        build_requirements_disclosure(rebuilt, ui_language="sv").requirements_version
        == disclosed.requirements_version
    )


def test_what_the_user_says_after_accepting_still_changes_the_output() -> None:
    """Protection is scoped to the evidence the user already answered.

    A user who accepted a Word document and then asks for a JSON payload has
    changed their mind, and the flow has to follow — with a new disclosure to
    attest to, because the plan is no longer the one they accepted.
    """

    conversation, disclosed = _accepted_audio_conversation()
    conversation.append(
        ConversationMessage(
            message_id="user-2",
            role="user",
            content="Vi vill ha strukturerad JSON som slutresultat i stället.",
            metadata=_classifier_metadata(
                _classified(
                    "terminal_output",
                    "structured_json",
                    "high",
                    "strukturerad JSON som slutresultat",
                    cited_message_id="user-2",
                ),
            ),
        )
    )

    rebuilt = build_planning_state_from_conversation(conversation)

    assert rebuilt.resolved_slots["terminal_output"].value == "structured_json"
    draft = derive_architecture_commit_draft(rebuilt)
    assert draft is not None
    assert draft.tuples_chain[-1].output_type.value == "json"
    assert (
        build_requirements_disclosure(rebuilt, ui_language="sv").requirements_version
        != disclosed.requirements_version
    )


def test_the_confirmation_turns_own_reading_does_not_replace_what_it_confirms() -> None:
    """The classification a confirmation turn makes is not what it confirmed.

    A confirmation whose attachments or deployment policy moved since the
    disclosure falls through to an ordinary classified turn, and that turn's
    reading is persisted on the confirmation message itself. The disclosure the
    user answered was built before it, so it is a re-reading like any other —
    but it shares the confirmation's own position in the conversation, which is
    the one place chronology can be read as "already accepted".
    """

    conversation, disclosed = _accepted_audio_conversation(
        confirmation_metadata=_classifier_metadata(
            _classified(
                "terminal_output",
                "structured_json",
                "high",
                "strukturerad JSON",
            ),
        ),
    )

    rebuilt = build_planning_state_from_conversation(conversation)

    assert rebuilt.resolved_slots["terminal_output"].value == "docx_document"
    draft = derive_architecture_commit_draft(rebuilt)
    assert draft is not None
    assert draft.tuples_chain[-1].output_type.value == "docx"
    assert (
        build_requirements_disclosure(rebuilt, ui_language="sv").requirements_version
        == disclosed.requirements_version
    )


def test_an_answered_decision_names_the_question_that_settled_it() -> None:
    # The summary rendered every decision the same way, so a reader could not
    # tell an answer from a reading, and had nothing to change a wrong one
    # against. Provenance is on the slot; the disclosure stops discarding it.
    state = _document_state()

    disclosure = build_requirements_disclosure(state, ui_language="sv")

    answered = {
        decision.question_id
        for decision in disclosure.key_decisions
        if not decision.is_derived
    }
    assert "terminal_output" in answered
    assert "primary_runtime_input" in answered
    assert all(
        decision.question_id is not None
        for decision in disclosure.key_decisions
        if not decision.is_derived
    )


def test_a_decision_the_builder_read_is_derived_and_names_no_question() -> None:
    # A high-confidence explicit classification is presented as a key decision,
    # but the user never answered it. Offering a question to change would point
    # at a question they were never asked.
    state = _document_state()
    state.resolved_slots["report_disposition"] = _report_disposition_slot(
        source="model",
        confidence="high",
        evidence_level="explicit",
    )

    disclosure = build_requirements_disclosure(state, ui_language="sv")

    read = [
        decision
        for decision in disclosure.key_decisions
        if decision.topic == render_summary_label("report_disposition", "sv")
    ]
    assert len(read) == 1
    assert read[0].is_derived is True
    assert read[0].question_id is None


def _runtime_field_state() -> PlanningState:
    """A committed state whose operator fills in two fields before every run."""

    state = _committed_state(
        primary_runtime_input="documents",
        terminal_output="docx_document",
        docx_output_mode="generated_docx",
        document_material_scope="multiple_documents_case",
        post_processing_goal="structure_key_information",
        runtime_metadata_fields="basic_runtime_metadata",
    )
    state.input_fields = [
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                variable_name="arendetyp",
                label="Ärendetyp",
                field_type="select",
                required=True,
                # A value that contains the separator the summary sentence
                # joins fields with: the list must keep it one option.
                options=["Bygglov, rivning", "Serveringstillstånd"],
                provenance="user_confirmed",
            ),
            purpose="interpret_input",
            structured_answer_message_id="message-1",
        ),
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                variable_name="mottagare",
                label="Mottagare",
                field_type="text",
                required=False,
                provenance="user_confirmed",
            ),
            purpose="shape_result",
            structured_answer_message_id="message-1",
        ),
    ]
    return state


def test_the_runtime_form_the_summary_states_is_also_readable_as_fields() -> None:
    # The confirmation card had to parse the fields back out of the interview
    # transcript to list them. They are the same fields the summary sentence
    # already states, projected from the same state, so list and sentence
    # cannot name different fields.
    state = _runtime_field_state()

    swedish = build_requirements_disclosure(state, ui_language="sv")
    english = build_requirements_disclosure(state, ui_language="en")

    assert [field.key for field in swedish.runtime_input_fields] == [
        "arendetyp",
        "mottagare",
    ]
    case_type, recipient = swedish.runtime_input_fields
    assert case_type.label == "Ärendetyp"
    assert case_type.type == "select"
    assert case_type.required is True
    assert case_type.options == ["Bygglov, rivning", "Serveringstillstånd"]
    assert recipient.type == "text"
    assert recipient.required is False
    assert recipient.options == []
    assert [field.purpose for field in swedish.runtime_input_fields] == [
        "Använd för att förstå indata",
        "Använd för att forma slutresultatet",
    ]
    assert [field.purpose for field in english.runtime_input_fields] == [
        "Use it to understand the input",
        "Use it to shape the final result",
    ]
    for field in swedish.runtime_input_fields:
        assert any(field.label in note for note in swedish.assumptions)
    # The same facts reach the confirmation identity through that sentence, so
    # the list beside it needs no place of its own in the hash.
    assert "runtime_input_fields" not in RequirementsDisclosureContent.model_fields


def test_two_choices_and_three_choices_do_not_read_alike() -> None:
    # An option may contain the separator the sentence joins options with.
    # Two choices, one of them "Bygglov, rivning", must not read as the three
    # choices a comma-separated list would suggest — the user is confirming
    # what the operator will be able to pick.
    two_choices = _runtime_field_state()
    three_choices = _runtime_field_state()
    three_choices.input_fields[0].value = three_choices.input_fields[
        0
    ].value.model_copy(
        update={"options": ["Bygglov", "rivning", "Serveringstillstånd"]}
    )

    stated = build_requirements_disclosure(two_choices, ui_language="sv")
    split = build_requirements_disclosure(three_choices, ui_language="sv")

    assert stated.assumptions != split.assumptions
    assert stated.requirements_version != split.requirements_version


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda field: field.model_copy(
                update={
                    "value": field.value.model_copy(update={"label": "Typ av ärende"})
                }
            ),
            id="renamed field",
        ),
        pytest.param(
            lambda field: field.model_copy(
                update={
                    "value": field.value.model_copy(
                        update={"options": ["Bygglov", "rivning"]}
                    )
                }
            ),
            id="different options",
        ),
        pytest.param(
            lambda field: field.model_copy(update={"purpose": "whole_flow"}),
            id="different purpose",
        ),
    ],
)
def test_changing_a_shown_runtime_field_invalidates_the_confirmation(mutate) -> None:
    """Everything the card says about a field is part of what was confirmed.

    The label is the control the operator reads, the options are what they may
    pick, and the purpose decides which step the value is placed on. Purpose
    and options once reached the compiled flow without reaching the summary,
    so a confirmation could survive a change the user never saw.
    """

    state = _runtime_field_state()
    confirmed = _decide(state)
    assert isinstance(confirmed, ConfirmRequirements)

    state.input_fields = [mutate(state.input_fields[0]), *state.input_fields[1:]]

    reconfirmed = _decide(
        state,
        confirmed_version=confirmed.payload.requirements_version,
    )
    assert isinstance(reconfirmed, ConfirmRequirements)
    assert (
        reconfirmed.payload.requirements_version
        != confirmed.payload.requirements_version
    )


def test_the_committed_architecture_is_a_derived_decision() -> None:
    # The chain follows from the answers; nobody was asked to approve it as a
    # question, and there is no question to send a reader back to.
    state = _document_state()

    disclosure = build_requirements_disclosure(state, ui_language="sv")

    architecture = [
        decision
        for decision in disclosure.key_decisions
        if decision.topic == "Planerad bearbetning"
    ]
    assert len(architecture) == 1
    assert architecture[0].is_derived is True
    assert architecture[0].question_id is None


def test_result_obligations_are_disclosed_in_the_readers_language() -> None:
    # The classifier names obligations by identifier; the card must not echo
    # those to a municipal reader, and the order follows the vocabulary, not
    # the alphabet.
    state = _document_state()
    state.signals = [
        PlanningSignal(
            question_id=RESULT_OBLIGATION_SIGNAL_ID,
            value=value,
            confidence="high",
            source="model",
            provenance=[f"model:{value}"],
        )
        for value in ("recommendations", "summary", "open_questions")
    ]

    swedish = build_requirements_disclosure(state, ui_language="sv")
    english = build_requirements_disclosure(state, ui_language="en")

    assert (
        "Resultatet ska också innehålla: sammanfattning, öppna frågor, rekommendationer."
        in swedish.assumptions
    )
    assert (
        "The result must also include: summary, open questions, recommendations."
        in english.assumptions
    )
    assert not any("recommendations" in line for line in swedish.assumptions)


def test_every_result_obligation_has_a_label_in_both_languages() -> None:
    from eneo.flows.ai_builder.ai_builder_requirements_disclosure import (
        _RESULT_OBLIGATION_LABELS,
    )
    from eneo.flows.ai_builder.ai_builder_result_contract import (
        RESULT_OBLIGATION_VALUES,
    )

    assert set(_RESULT_OBLIGATION_LABELS) == set(RESULT_OBLIGATION_VALUES)
    assert all(sv and en for sv, en in _RESULT_OBLIGATION_LABELS.values())
