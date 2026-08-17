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
from uuid import UUID

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
    RequirementsSummaryPayload,
)
from eneo.flows.ai_builder.ai_builder_requirements_disclosure import (
    build_requirements_disclosure,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    resolve_requirements_state,
)
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    ClassifiedEvidence,
    ClassifiedSlot,
    SlotClassificationAttempt,
    SlotClassificationConfidence,
    SlotClassificationInput,
    SlotClassificationResult,
    SlotClassificationSource,
)
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    ConfirmRequirements,
    GenerateProposal,
    resolve_turn_control,
)
from eneo.flows.ai_builder.planning_state import (
    ExampleOutputCitation,
    ExampleOutputConstraintEvidence,
    ExampleOutputSourceCoverage,
    ExampleOutputStyleConstraint,
    FileRoleEvidence,
    NamedResultEvidence,
    PlanningState,
    ResolvedSlot,
    SlotConfidence,
    SlotEvidenceLevel,
    SlotSource,
)
from eneo.flows.ai_builder.planning_state_builder import (
    apply_attested_requirements,
    build_planning_state_from_conversation,
    merge_llm_resolved_slots,
)
from eneo.flows.ai_builder.question_catalog import render_summary_label

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
        SlotClassificationResult(
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
        SlotClassificationResult(
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
        SlotClassificationResult(example_output_constraints=revised),
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
            result=SlotClassificationResult(slots=slots),
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
