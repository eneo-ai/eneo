"""Unit tests for `planning_state_builder.carry_forward_persisted_planner_state`.

The helper is the single place the save path merges planner-owned
fields (architecture_commit, draft_plan_id, monotonic phase) from the
previously persisted state onto a freshly rebuilt one. Integration
tests pin the savepoint wiring; these unit tests pin the merge
semantics in isolation so regressions show up at the merge layer, not
two containers deep.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    ArchitectureCommit,
    EvidenceRef,
    PlanningState,
    StepTriple,
)
from intric.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
    carry_forward_persisted_planner_state,
)


def _state(
    *,
    phase: str = "discovering",
    architecture_commit: ArchitectureCommit | None = None,
    draft_plan_id=None,
) -> PlanningState:
    return PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        phase=phase,  # type: ignore[arg-type]
        evidence=EvidenceRef(),
        architecture_commit=architecture_commit,
        draft_plan_id=draft_plan_id,
    )


def _commit(hash_char: str = "a") -> ArchitectureCommit:
    return ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        committed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
        architecture_hash=hash_char * 64,
    )


class TestPersistedNone:
    def test_is_noop_when_persisted_is_none(self) -> None:
        rebuilt = _state(phase="awaiting_input")

        carry_forward_persisted_planner_state(rebuilt, None)

        assert rebuilt.architecture_commit is None
        assert rebuilt.draft_plan_id is None
        assert rebuilt.phase == "awaiting_input"


class TestArchitectureCommitPreservation:
    def test_carries_forward_when_rebuilt_has_none(self) -> None:
        persisted_commit = _commit()
        rebuilt = _state()
        persisted = _state(architecture_commit=persisted_commit)

        carry_forward_persisted_planner_state(rebuilt, persisted)

        assert rebuilt.architecture_commit is persisted_commit

    def test_does_not_overwrite_explicit_set_on_rebuilt(self) -> None:
        explicit = _commit(hash_char="b")
        persisted_commit = _commit(hash_char="a")
        rebuilt = _state(architecture_commit=explicit)
        persisted = _state(architecture_commit=persisted_commit)

        carry_forward_persisted_planner_state(rebuilt, persisted)

        assert rebuilt.architecture_commit is explicit

    def test_leaves_none_when_neither_side_has_commit(self) -> None:
        rebuilt = _state()
        persisted = _state()

        carry_forward_persisted_planner_state(rebuilt, persisted)

        assert rebuilt.architecture_commit is None


class TestDraftPlanIdPreservation:
    def test_carries_forward_when_rebuilt_has_none(self) -> None:
        plan_id = uuid4()
        rebuilt = _state()
        persisted = _state(draft_plan_id=plan_id)

        carry_forward_persisted_planner_state(rebuilt, persisted)

        assert rebuilt.draft_plan_id == plan_id

    def test_does_not_overwrite_explicit_set_on_rebuilt(self) -> None:
        explicit = uuid4()
        old = uuid4()
        rebuilt = _state(draft_plan_id=explicit)
        persisted = _state(draft_plan_id=old)

        carry_forward_persisted_planner_state(rebuilt, persisted)

        assert rebuilt.draft_plan_id == explicit


class TestPhaseMonotonicity:
    def test_preserves_advanced_phase_when_rebuild_regressed(self) -> None:
        rebuilt = _state(phase="discovering")
        persisted = _state(phase="plan_proposed")

        carry_forward_persisted_planner_state(rebuilt, persisted)

        assert rebuilt.phase == "plan_proposed"

    def test_keeps_rebuilt_phase_when_already_equal_or_ahead(self) -> None:
        rebuilt = _state(phase="plan_proposed")
        persisted = _state(phase="discovering")

        carry_forward_persisted_planner_state(rebuilt, persisted)

        assert rebuilt.phase == "plan_proposed"

    def test_preserves_ready_to_commit_over_discovering(self) -> None:
        rebuilt = _state(phase="discovering")
        persisted = _state(phase="ready_to_commit")

        carry_forward_persisted_planner_state(rebuilt, persisted)

        assert rebuilt.phase == "ready_to_commit"

    def test_raises_on_unknown_phase(self) -> None:
        # The tuple-based PHASE_ORDER lookup fails loud on unknown
        # phases. If a new PlanningPhase Literal is added without
        # updating the order, .index() raises — preservation never
        # silently degrades.
        rebuilt = _state()
        rebuilt.phase = "discovering"  # valid
        persisted = _state(phase="plan_proposed")
        # Bypass Literal enforcement on persisted to simulate a phase
        # that exists at runtime but was forgotten in _PHASE_ORDER.
        object.__setattr__(persisted, "phase", "brand_new_phase")

        with pytest.raises(ValueError):
            carry_forward_persisted_planner_state(rebuilt, persisted)


class TestReturnValue:
    def test_returns_none_and_mutates_in_place(self) -> None:
        rebuilt = _state()
        persisted = _state(architecture_commit=_commit())

        result = carry_forward_persisted_planner_state(rebuilt, persisted)

        assert result is None
        assert rebuilt.architecture_commit is not None


class TestPolicyDefaults:
    def test_text_runtime_input_is_inferred_from_generic_receive_text_phrase(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Skapa ett enkelt flöde som tar emot en kort text från "
                        "användaren och sammanfattar den i tre tydliga punkter."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["primary_runtime_input"]
        assert slot.value == "text"
        output_slot = state.resolved_slots["terminal_output"]
        assert output_slot.value == "structured_text"

    def test_document_input_defaults_to_flexible_document_scope(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Build a document analysis flow that accepts uploaded "
                        "documents and produces a written report."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["document_material_scope"]
        assert slot.value == "flexible_document_case"
        assert slot.source == "policy_default"

    def test_audio_answer_to_document_scope_question_sets_audio_without_document_scope(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content="ljudfil som transkribering",
                    metadata={
                        "question_answer": {
                            "question_id": "document_material_scope",
                            "answer": "ljudfil som transkribering",
                        }
                    },
                )
            ]
        )

        slot = state.resolved_slots["primary_runtime_input"]
        assert slot.value == "audio"
        assert "document_material_scope" not in state.resolved_slots

    def test_audio_upload_prompt_does_not_create_document_scope_slot(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett flöde där användaren laddar upp en ljudfil "
                        "vid körning. Flödet ska transkribera ljudfilen till "
                        "svensk text och skapa ett Word-dokument som slutresultat."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["primary_runtime_input"]
        assert slot.value == "audio"
        assert "document_material_scope" not in state.resolved_slots

    def test_document_input_defaults_to_no_extra_runtime_metadata(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Build a document analysis flow that accepts uploaded "
                        "documents and produces a written report."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "policy_default"

    def test_audio_input_defaults_to_no_extra_runtime_metadata(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett ljudflöde för mötesprotokoll i DOCX. "
                        "Användaren ska bara lämna ljudfilen."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "heuristic"

    def test_runtime_input_fields_are_not_overwritten_by_no_metadata_default(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Create a document review flow that accepts PDFs, uses "
                        "input fields for audience and detail level at runtime, "
                        "and produces a DOCX report."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_case_metadata"
        assert slot.source == "heuristic"
