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
from intric.flows.ai_builder.ai_builder_slot_classifier import (
    ClassifiedSlot,
    SlotClassificationConfidence,
    SlotClassificationResult,
)
from intric.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    ArchitectureCommit,
    EvidenceRef,
    PlanningState,
    ResolvedSlot,
    SlotConfidence,
    SlotSource,
    StepTriple,
)
from intric.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
    carry_forward_persisted_planner_state,
    merge_llm_resolved_slots,
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


def _slot(
    *,
    name: str,
    value: str,
    source: SlotSource,
) -> ResolvedSlot:
    confidence: SlotConfidence = "medium" if source == "policy_default" else "high"
    return ResolvedSlot(
        name=name,
        value=value,
        source=source,
        evidence=[f"{source}:{name}"],
        confidence=confidence,
    )


def _classified(
    slot_name: str,
    value: str,
    confidence: SlotClassificationConfidence,
) -> ClassifiedSlot:
    return ClassifiedSlot(
        slot_name=slot_name,
        value=value,
        confidence=confidence,
        reason=f"{slot_name} classified",
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
                        "Jag vill bygga ett flöde som tar emot en ljudfil, "
                        "transkriberar samtalet och skapar ett Word-dokument."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "policy_default"

    def test_text_input_defaults_to_no_extra_runtime_metadata(self) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Skapa ett flöde som tar emot text från användaren, "
                        "klassificerar ärendet och skriver ett svar."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "policy_default"

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

    def test_swedish_audio_prompt_with_terminal_word_file_resolves_core_slots(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill bygga ett flöde där jag ska skicka in en ljudfil "
                        "som ska transkriberas. Jag vill ha en Word-fil i slutet."
                    ),
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "audio"
        assert state.resolved_slots["terminal_output"].value == "docx_document"
        assert state.resolved_slots["docx_output_mode"].value == "generated_docx"
        assert state.resolved_slots["runtime_metadata_fields"].value == (
            "no_extra_metadata"
        )

    def test_swedish_audio_docx_prompt_with_no_input_fields_keeps_metadata_absent(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill bygga ett flöde där användaren skickar in "
                        "mötesljud, flödet transkriberar ljudet och skapar en "
                        "Word-rapport med rubriker. Inmatningsfält behövs inte."
                    ),
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "audio"
        assert state.resolved_slots["terminal_output"].value == "docx_document"
        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "heuristic"

    def test_swedish_audio_recording_prompt_with_terminal_word_file_resolves_core_slots(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Jag vill kunna skicka in en ljudinspelning och få ett "
                        "bra Word-dokument tillbaka."
                    ),
                )
            ]
        )

        assert state.resolved_slots["primary_runtime_input"].value == "audio"
        assert state.resolved_slots["terminal_output"].value == "docx_document"
        assert state.resolved_slots["docx_output_mode"].value == "generated_docx"
        assert state.resolved_slots["runtime_metadata_fields"].value == (
            "no_extra_metadata"
        )

    def test_explicit_audio_meeting_docx_prompt_resolves_audio_with_high_confidence(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett flöde där användaren laddar upp en ljudfil vid "
                        "körning. Ljudfilen är en inspelning från ett "
                        "kommunfullmäktigemöte. Flödet ska först transkribera "
                        "ljudfilen till svensk text. Rubrikerna ska inte vara "
                        "inmatningsfält för användaren, utan ska skapas och fyllas "
                        "i utifrån transkriptionen. Slutresultatet ska vara ett "
                        "Word-dokument. Användaren ska bara behöva lämna in "
                        "ljudfilen vid körning."
                    ),
                )
            ]
        )

        slot = state.resolved_slots["primary_runtime_input"]
        assert slot.value == "audio"
        assert slot.source == "heuristic"
        assert slot.confidence == "high"
        assert state.resolved_slots["terminal_output"].value == "docx_document"


class TestModelSlotMerge:
    def test_model_output_cannot_displace_explicit_summary_or_flow_defaults(
        self,
    ) -> None:
        state = _state()
        state.resolved_slots = {
            "primary_runtime_input": _slot(
                name="primary_runtime_input",
                value="documents",
                source="structured_answer",
            ),
            "terminal_output": _slot(
                name="terminal_output",
                value="structured_text",
                source="requirements_summary",
            ),
            "runtime_metadata_fields": _slot(
                name="runtime_metadata_fields",
                value="no_extra_metadata",
                source="flow_default",
            ),
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified("primary_runtime_input", "text", "high"),
                    _classified("terminal_output", "pdf_document", "high"),
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "high",
                    ),
                )
            ),
            prompt_hash="a" * 64,
        )

        assert state.resolved_slots["primary_runtime_input"].value == "documents"
        assert state.resolved_slots["terminal_output"].value == "structured_text"
        assert state.resolved_slots["runtime_metadata_fields"].value == (
            "no_extra_metadata"
        )

    def test_high_model_output_replaces_policy_default(self) -> None:
        state = _state()
        state.resolved_slots = {
            "runtime_metadata_fields": _slot(
                name="runtime_metadata_fields",
                value="no_extra_metadata",
                source="policy_default",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "high",
                    ),
                )
            ),
            prompt_hash="b" * 64,
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "detailed_case_metadata"
        assert slot.source == "model"
        assert slot.evidence == [
            "model:runtime_metadata_fields:" + "b" * 64,
        ]

    def test_medium_model_output_does_not_replace_policy_default(self) -> None:
        state = _state()
        state.resolved_slots = {
            "runtime_metadata_fields": _slot(
                name="runtime_metadata_fields",
                value="no_extra_metadata",
                source="policy_default",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "runtime_metadata_fields",
                        "detailed_case_metadata",
                        "medium",
                    ),
                )
            ),
            prompt_hash="c" * 64,
        )

        slot = state.resolved_slots["runtime_metadata_fields"]
        assert slot.value == "no_extra_metadata"
        assert slot.source == "policy_default"

    def test_medium_model_output_replaces_heuristic_and_fills_missing_slot(
        self,
    ) -> None:
        state = _state(phase="awaiting_input")
        state.resolved_slots = {
            "terminal_output": _slot(
                name="terminal_output",
                value="structured_text",
                source="heuristic",
            )
        }

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified("terminal_output", "pdf_document", "medium"),
                    _classified("primary_runtime_input", "text", "medium"),
                )
            ),
            prompt_hash="d" * 64,
        )

        assert state.resolved_slots["terminal_output"].value == "pdf_document"
        assert state.resolved_slots["primary_runtime_input"].value == "text"
        assert state.phase == "discovering"

    def test_model_output_cannot_displace_high_confidence_input_heuristic(
        self,
    ) -> None:
        state = build_planning_state_from_conversation(
            [
                ConversationMessage(
                    role="user",
                    content=(
                        "Bygg ett flöde där användaren laddar upp en ljudfil vid "
                        "körning. Slutresultatet ska vara ett Word-dokument. "
                        "Användaren ska bara behöva lämna in ljudfilen vid körning."
                    ),
                )
            ]
        )

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified(
                        "primary_runtime_input",
                        "text_and_documents",
                        "high",
                    ),
                )
            ),
            prompt_hash="d" * 64,
        )

        assert state.resolved_slots["primary_runtime_input"].value == "audio"
        assert state.resolved_slots["primary_runtime_input"].confidence == "high"

    def test_low_model_slot_is_not_persisted(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(_classified("terminal_output", "pdf_document", "low"),)
            ),
            prompt_hash="e" * 64,
        )

        assert state.resolved_slots == {}

    def test_unknown_model_slot_is_not_persisted(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(_classified("primary_runtime_input", "unknown", "high"),)
            ),
            prompt_hash="f" * 64,
        )

        assert state.resolved_slots == {}

    def test_non_llm_resolvable_slots_are_not_persisted(self) -> None:
        state = _state()

        merge_llm_resolved_slots(
            state,
            SlotClassificationResult(
                slots=(
                    _classified("docx_output_mode", "template_fill_docx", "high"),
                    _classified(
                        "pdf_generation_mode",
                        "pdf_template_requested",
                        "high",
                    ),
                )
            ),
            prompt_hash="g" * 64,
        )

        assert state.resolved_slots == {}

    def test_prompt_hash_is_required(self) -> None:
        state = _state()

        with pytest.raises(ValueError, match="prompt_hash"):
            merge_llm_resolved_slots(
                state,
                SlotClassificationResult(
                    slots=(_classified("primary_runtime_input", "text", "high"),)
                ),
                prompt_hash="",
            )
