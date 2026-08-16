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
from eneo.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
)
from eneo.flows.ai_builder.ai_builder_requirements_disclosure import (
    build_requirements_disclosure,
)
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    SlotClassificationResult,
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
)
from eneo.flows.ai_builder.planning_state_builder import merge_llm_resolved_slots

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
