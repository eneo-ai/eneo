"""Tests for the server-owned AI Builder planner action policy."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from eneo.flows.ai_builder.ai_builder_action_policy import (
    build_planner_action_policy,
)
from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_error_contract import AIBuilderErrorCode
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    ClassifiedEvidence,
    ExplicitlyUncertainSlotClassificationOutcome,
    SlotClassificationEvidenceLevel,
    SlotClassificationResult,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommitDraft,
    CheckpointIntent,
    FileRoleEvidence,
    PlanningState,
    ResolvedSlot,
    SlotConfidence,
    SlotSource,
    StepTriple,
)
from eneo.flows.ai_builder.planning_state_builder import (
    apply_policy_defaults_from_resolved_slots,
    merge_llm_resolved_slots,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode


def _slot_value(slot_name: str) -> str:
    return {
        "primary_runtime_input": "documents",
        "terminal_output": "text",
        "document_material_scope": "flexible_document_case",
    }.get(slot_name, f"{slot_name}_value")


def _slot(
    slot_name: str,
    value: str | None = None,
    *,
    source: SlotSource = "structured_answer",
    confidence: SlotConfidence = "high",
    evidence: list[str] | None = None,
    evidence_level: SlotClassificationEvidenceLevel | None = None,
) -> ResolvedSlot:
    return ResolvedSlot(
        name=slot_name,
        value=value or _slot_value(slot_name),
        source=source,
        evidence=(
            [
                (
                    f"quote:user_message:test:{slot_name}"
                    if source == "model"
                    else f"{source}:{slot_name}"
                )
            ]
            if evidence is None
            else evidence
        ),
        confidence=confidence,
        evidence_level=(
            evidence_level
            if evidence_level is not None or source != "model"
            else "inferred"
        ),
    )


def _state_with_resolved_slots(*slot_names: str) -> PlanningState:
    state = PlanningState.empty()
    for slot_name in slot_names:
        state.resolved_slots[slot_name] = _slot(slot_name)
    return state


def _state_with_architecture_commit() -> PlanningState:
    state = _state_with_resolved_slots(
        "primary_runtime_input",
        "terminal_output",
        "document_material_scope",
    )
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    state.architecture_commit = finalize_architecture_commit(
        draft,
        now=lambda: datetime(2026, 4, 24, tzinfo=timezone.utc),
    )
    return state


def _template_file_role(
    *,
    placeholders: list[str] | None,
) -> FileRoleEvidence:
    return FileRoleEvidence(
        file_id="00000000-0000-0000-0000-000000000701",
        filename="mall.docx",
        file_type="document",
        mimetype=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        has_readable_text=True,
        coverage="fully_seen",
        role="template",
        source="structured_answer",
        confidence="high",
        template_placeholders=placeholders,
    )


def test_policy_blocks_commit_and_plan_until_core_architecture_is_resolved() -> None:
    policy = build_planner_action_policy(
        session_state=PlanningState.empty(),
        selected_discovery_question_ids=("document_material_scope",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == (
        "primary_runtime_input",
        "terminal_output",
        "document_material_scope",
    )


def test_policy_asks_for_model_medium_core_slot_before_commit() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "audio",
        source="heuristic",
        confidence="high",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
        source="model",
        confidence="medium",
    )
    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == (
        "primary_runtime_input",
        "terminal_output",
    )


def test_policy_asks_weak_pattern_slot_only_when_discovery_selects_it() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "documents",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "flexible_document_case",
        source="model",
        confidence="medium",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=("document_material_scope",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("document_material_scope",)


@pytest.mark.parametrize(
    ("slot", "expected"),
    [
        (_slot("terminal_output", "structured_text", source="model"), True),
        (
            _slot(
                "terminal_output",
                "structured_text",
                source="model",
                confidence="medium",
                evidence_level="inferred",
            ),
            False,
        ),
        (
            _slot(
                "terminal_output",
                "structured_text",
                source="model",
                confidence="medium",
                evidence_level="explicit",
            ),
            True,
        ),
        (
            _slot(
                "terminal_output",
                "structured_text",
                source="heuristic",
                confidence="medium",
            ),
            False,
        ),
        (
            _slot(
                "terminal_output",
                "structured_text",
                source="heuristic",
                confidence="low",
            ),
            False,
        ),
        (
            _slot(
                "terminal_output",
                "structured_text",
                source="requirements_summary",
                confidence="medium",
            ),
            True,
        ),
        (
            _slot(
                "primary_runtime_input",
                "audio",
                source="heuristic",
                confidence="high",
            ),
            False,
        ),
        (
            _slot(
                "runtime_metadata_fields",
                "no_extra_metadata",
                source="policy_default",
                confidence="medium",
            ),
            False,
        ),
        (_slot("terminal_output", "docx_document", source="flow_default"), True),
    ],
)
def test_commit_grade_truth_table(slot: ResolvedSlot, expected: bool) -> None:
    assert slot.is_commit_grade is expected


def test_vague_purpose_question_precedes_primary_input_and_terminal_output() -> None:
    policy = build_planner_action_policy(
        session_state=PlanningState.empty(),
        selected_discovery_question_ids=("post_processing_goal",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == (
        "post_processing_goal",
        "primary_runtime_input",
        "terminal_output",
    )


def test_vague_purpose_question_precedes_selected_terminal_output() -> None:
    state = _state_with_resolved_slots(
        "primary_runtime_input",
        "document_material_scope",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(
            "terminal_output",
            "post_processing_goal",
        ),
    )

    assert policy.allowed_ask_question_targets == (
        "post_processing_goal",
        "terminal_output",
    )


def test_vague_purpose_question_precedes_structured_io_contract() -> None:
    state = _state_with_resolved_slots(
        "primary_runtime_input",
        "terminal_output",
        "document_material_scope",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(
            "structured_io_contract",
            "post_processing_goal",
        ),
    )

    assert policy.allowed_ask_question_targets == (
        "post_processing_goal",
        "structured_io_contract",
    )


def test_commit_grade_purpose_keeps_existing_core_question_order() -> None:
    state = _state_with_resolved_slots("post_processing_goal")

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=("post_processing_goal",),
    )

    assert policy.allowed_ask_question_targets == (
        "primary_runtime_input",
        "terminal_output",
    )


def test_confidently_inferred_purpose_skipped_by_discovery_keeps_core_order() -> None:
    state = PlanningState.empty()
    state.resolved_slots["post_processing_goal"] = _slot(
        "post_processing_goal",
        source="heuristic",
        confidence="high",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_ask_question_targets == (
        "primary_runtime_input",
        "terminal_output",
    )


def test_blocking_discovery_question_still_precedes_vague_purpose() -> None:
    policy = build_planner_action_policy(
        session_state=PlanningState.empty(),
        selected_discovery_question_ids=(
            "flow_input_architecture",
            "post_processing_goal",
        ),
    )

    assert policy.allowed_ask_question_targets == (
        "flow_input_architecture",
        "post_processing_goal",
        "primary_runtime_input",
        "terminal_output",
    )


def test_policy_does_not_force_inferred_metadata_default_into_questions() -> None:
    state = _state_with_resolved_slots(
        "primary_runtime_input",
        "terminal_output",
        "document_material_scope",
    )
    state.resolved_slots["runtime_metadata_fields"] = _slot(
        "runtime_metadata_fields",
        "no_extra_metadata",
        source="model",
        confidence="medium",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_asks_a_heuristic_comparison_scope_before_committing() -> None:
    # The aggregation reader commits nothing below commit grade, so a confident
    # text reading of the comparison must be asked before the architecture is
    # committed; otherwise the card and the build disagree.
    state = _state_with_resolved_slots(
        "primary_runtime_input",
        "terminal_output",
        "document_material_scope",
    )
    state.resolved_slots["comparison_scope"] = _slot(
        "comparison_scope",
        "same_run_compare",
        source="heuristic",
        confidence="high",
    )
    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=("comparison_scope",),
    )
    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("comparison_scope",)


def test_policy_keeps_selected_comparison_question_askable() -> None:
    state = _state_with_resolved_slots(
        "primary_runtime_input",
        "terminal_output",
        "document_material_scope",
    )
    state.resolved_slots["comparison_scope"] = _slot(
        "comparison_scope",
        "same_run_compare",
        source="heuristic",
        confidence="high",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=("comparison_scope",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("comparison_scope",)


def test_policy_orders_every_ask_by_the_interaction_table() -> None:
    # Discovery's questions and the core gaps share one order: the purpose
    # before the input and output that depend on it, quality slots last.
    policy = build_planner_action_policy(
        session_state=PlanningState.empty(),
        selected_discovery_question_ids=(
            "runtime_metadata_fields",
            "post_processing_goal",
        ),
    )

    assert policy.allowed_ask_question_targets == (
        "post_processing_goal",
        "primary_runtime_input",
        "terminal_output",
        "runtime_metadata_fields",
    )


@pytest.mark.parametrize("primary_runtime_input", ["audio", "text"])
def test_policy_ignores_weak_comparison_for_non_document_input(
    primary_runtime_input: str,
) -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        primary_runtime_input,
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
    )
    state.resolved_slots["post_processing_goal"] = _slot(
        "post_processing_goal",
        "summarize_or_overview",
    )
    state.resolved_slots["comparison_scope"] = _slot(
        "comparison_scope",
        "same_run_compare",
        source="heuristic",
        confidence="high",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


@pytest.mark.parametrize("primary_runtime_input", ["audio", "text"])
def test_policy_ignores_weak_report_disposition_for_non_document_input(
    primary_runtime_input: str,
) -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        primary_runtime_input,
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
    )
    state.resolved_slots["post_processing_goal"] = _slot(
        "post_processing_goal",
        "summarize_or_overview",
    )
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "both",
        source="model",
        confidence="medium",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_asks_the_purpose_before_committing_an_audio_text_architecture() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "audio",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
    )

    unsettled = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    # Delivering the transcript and writing a result from it are different
    # topologies, so the purpose is asked rather than assumed or refused.
    assert unsettled.allowed_action_kinds == ("ask_question",)
    assert unsettled.allowed_ask_question_targets == ("post_processing_goal",)
    assert unsettled.architecture_refusal_code is None

    state.resolved_slots["post_processing_goal"] = _slot(
        "post_processing_goal",
        "action_followup",
    )
    settled = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert settled.allowed_action_kinds == ("commit_architecture",)
    assert settled.allowed_ask_question_targets == ()


def test_policy_does_not_ask_the_purpose_when_editing_an_existing_flow() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "audio",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
        is_edit_mode=True,
    )

    # An edit keeps the existing flow's topology, so the purpose is not the
    # question that unblocks it.
    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_does_not_introduce_report_layout_discovery_in_edit_mode() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "documents",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "multiple_documents_case",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
        is_edit_mode=True,
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_refuses_removed_json_to_text_architecture() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "json",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("refuse_architecture_commit",)
    assert policy.allowed_ask_question_targets == ()
    assert (
        policy.architecture_refusal_code is AIBuilderErrorCode.UNSUPPORTED_ARCHITECTURE
    )


def test_policy_refuses_unsupported_revision_of_committed_architecture() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "json",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_json",
    )
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    state.architecture_commit = finalize_architecture_commit(draft)
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
        requirements_confirmed=True,
    )

    assert policy.allowed_action_kinds == ("refuse_architecture_commit",)
    assert (
        policy.architecture_refusal_code is AIBuilderErrorCode.UNSUPPORTED_ARCHITECTURE
    )


def test_policy_refuses_unsupported_committed_pattern_envelope() -> None:
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="docx",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=[
                "audio_to_artifact_report",
                "text_to_artifact_report",
            ],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("refuse_architecture_commit",)
    assert (
        policy.architecture_refusal_code is AIBuilderErrorCode.UNSUPPORTED_ARCHITECTURE
    )


def test_policy_requires_audio_for_a_transcript_checkpoint() -> None:
    state = _state_with_architecture_commit()
    state.checkpoint_intents = [
        CheckpointIntent(
            evidence_level="explicit",
            producer_kind="transcript",
            operation="set",
            mode=FlowStepReviewMode.EDIT,
            confidence="high",
            evidence=["quote:user_message:test:transcript-checkpoint"],
        )
    ]

    refused = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert refused.allowed_action_kinds == ("refuse_architecture_commit",)
    assert (
        refused.architecture_refusal_code
        is AIBuilderErrorCode.TRANSCRIPT_CHECKPOINT_REQUIRES_AUDIO
    )

    state.checkpoint_intents = [
        CheckpointIntent(
            evidence_level="explicit",
            producer_kind="transcript",
            operation="clear",
            mode=None,
            confidence="high",
            evidence=["quote:user_message:test:clear-transcript-checkpoint"],
        )
    ]
    allowed_clear = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )
    assert allowed_clear.allowed_action_kinds == ("confirm_requirements",)
    assert allowed_clear.architecture_refusal_code is None

    audio_state = _state_with_resolved_slots(
        "primary_runtime_input",
        "terminal_output",
    )
    audio_state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "audio",
    )
    audio_state.resolved_slots["post_processing_goal"] = _slot(
        "post_processing_goal",
        "action_followup",
    )
    audio_draft = derive_architecture_commit_draft(audio_state)
    assert audio_draft is not None
    audio_state.architecture_commit = finalize_architecture_commit(audio_draft)
    audio_state.checkpoint_intents = [
        CheckpointIntent(
            evidence_level="explicit",
            producer_kind="transcript",
            operation="set",
            mode=FlowStepReviewMode.EDIT,
            confidence="high",
            evidence=["quote:user_message:test:audio-transcript-checkpoint"],
        )
    ]
    allowed_audio = build_planner_action_policy(
        session_state=audio_state,
        selected_discovery_question_ids=(),
    )
    assert allowed_audio.allowed_action_kinds == ("confirm_requirements",)
    assert allowed_audio.architecture_refusal_code is None


def test_policy_requires_one_readable_template_for_template_fill() -> None:
    state = _state_with_resolved_slots(
        "primary_runtime_input",
        "terminal_output",
        "document_material_scope",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "docx_document",
    )
    state.resolved_slots["docx_output_mode"] = _slot(
        "docx_output_mode",
        "template_fill_docx",
    )
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    state.architecture_commit = finalize_architecture_commit(draft)

    missing = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )
    assert missing.allowed_action_kinds == ("refuse_architecture_commit",)
    assert (
        missing.architecture_refusal_code
        is AIBuilderErrorCode.TEMPLATE_ATTACHMENT_SELECTION_INVALID
    )

    state.file_roles = [_template_file_role(placeholders=None)]
    unreadable = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )
    assert unreadable.allowed_action_kinds == ("refuse_architecture_commit",)
    assert (
        unreadable.architecture_refusal_code
        is AIBuilderErrorCode.TEMPLATE_ATTACHMENT_UNREADABLE
    )

    state.file_roles[0] = state.file_roles[0].model_copy(
        update={"template_placeholders": []}
    )
    readable = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )
    assert readable.allowed_action_kinds == ("confirm_requirements",)
    assert readable.architecture_refusal_code is None


def test_policy_does_not_force_policy_default_docx_mode_into_questions() -> None:
    state = _state_with_resolved_slots(
        "primary_runtime_input",
        "document_material_scope",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "docx_document",
    )
    state.resolved_slots["docx_output_mode"] = _slot(
        "docx_output_mode",
        "generated_docx",
        source="policy_default",
        confidence="medium",
    )
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "synthesized_overview",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_allows_commit_after_core_slots_and_selected_questions_resolve() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_resolved_slots(
            "primary_runtime_input",
            "terminal_output",
            "document_material_scope",
        ),
        selected_discovery_question_ids=("document_material_scope",),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_does_not_use_pattern_metadata_as_question_selection() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_resolved_slots(
            "primary_runtime_input",
            "terminal_output",
        ),
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_asks_selected_report_disposition_for_multi_source_pdf_report() -> None:
    state = _state_with_resolved_slots("primary_runtime_input")
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    state.resolved_slots["pdf_generation_mode"] = _slot(
        "pdf_generation_mode",
        "generated_pdf",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "multiple_documents_case",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=("report_disposition",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("report_disposition",)


def test_policy_asks_unresolved_report_disposition_before_architecture_commit() -> None:
    state = _state_with_resolved_slots("primary_runtime_input")
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "multiple_documents_case",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("report_disposition",)


def test_policy_default_multi_source_scope_carries_an_assumed_report_layout() -> None:
    # A scope the policy assumed is not the user's decision, so the layout
    # that depends on it is assumed with it and shown as a row, not asked.
    state = _state_with_resolved_slots("primary_runtime_input")
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    apply_policy_defaults_from_resolved_slots(state, freeform_text="")

    assert state.resolved_slots["document_material_scope"].source == "policy_default"
    layout = state.resolved_slots["report_disposition"]
    assert (layout.source, layout.value) == ("policy_default", "synthesized_overview")
    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )
    draft = derive_architecture_commit_draft(state)

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert draft is not None
    assert draft.report_disposition == "synthesized_overview"


def test_resolved_disposition_commits_with_policy_default_multi_source_scope() -> None:
    state = _state_with_resolved_slots("primary_runtime_input")
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    apply_policy_defaults_from_resolved_slots(state, freeform_text="")
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "synthesized_overview",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )
    draft = derive_architecture_commit_draft(state)

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert draft is not None
    assert draft.report_disposition == "synthesized_overview"


def test_policy_refuses_a_required_pdf_template() -> None:
    state = _state_with_resolved_slots("primary_runtime_input")
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    state.resolved_slots["pdf_generation_mode"] = _slot(
        "pdf_generation_mode",
        "pdf_template_requested",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("refuse_architecture_commit",)
    assert policy.architecture_refusal_code is not None
    assert policy.architecture_refusal_code.value == "pdf_template_unsupported"


def test_policy_accepts_classifier_inferred_report_disposition() -> None:
    state = _state_with_resolved_slots("primary_runtime_input")
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    state.resolved_slots["pdf_generation_mode"] = _slot(
        "pdf_generation_mode",
        "generated_pdf",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "multiple_documents_case",
    )
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "per_source_sections",
        source="model",
        confidence="high",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_does_not_ask_report_disposition_for_docx_template_fill() -> None:
    state = _state_with_resolved_slots("primary_runtime_input")
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "docx_document",
    )
    state.resolved_slots["docx_output_mode"] = _slot(
        "docx_output_mode",
        "template_fill_docx",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "multiple_documents_case",
    )
    state.file_roles = [_template_file_role(placeholders=[])]

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("commit_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_never_exposes_resolved_slots_as_question_targets() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_resolved_slots("primary_runtime_input"),
        selected_discovery_question_ids=("primary_runtime_input",),
    )

    assert policy.allowed_ask_question_targets == ("terminal_output",)
    assert policy.allowed_action_kinds == ("ask_question",)


def test_policy_filters_commit_grade_terminal_output_discovery_target() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_resolved_slots(
            "primary_runtime_input",
            "terminal_output",
        ),
        selected_discovery_question_ids=("final_output_mode",),
    )

    assert "terminal_output" not in policy.allowed_ask_question_targets


def test_policy_can_ask_output_after_classifier_uncertainty_clears_guess() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = ResolvedSlot(
        name="primary_runtime_input",
        value="audio",
        source="heuristic",
        evidence=["heuristic:role-aware freeform analysis"],
        confidence="high",
    )
    state.resolved_slots["terminal_output"] = ResolvedSlot(
        name="terminal_output",
        value="structured_text",
        source="model",
        evidence=[
            "model:terminal_output:" + "a" * 64,
            "quote:user_message:test:structured_text",
        ],
        confidence="medium",
        evidence_level="inferred",
    )

    merge_llm_resolved_slots(
        state,
        SlotClassificationResult(
            slot_outcomes={
                "terminal_output": ExplicitlyUncertainSlotClassificationOutcome(
                    quote=ClassifiedEvidence(
                        source_id="user_message:test",
                        quote="not sure what the final output should be",
                    )
                )
            }
        ),
        prompt_hash="b" * 64,
        freeform_text="",
    )
    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert "terminal_output" not in state.resolved_slots
    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == (
        "primary_runtime_input",
        "terminal_output",
    )


@pytest.mark.parametrize("source", ["structured_answer", "flow_default"])
def test_classifier_uncertainty_keeps_protected_output_sources_resolved(
    source: str,
) -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = ResolvedSlot(
        name="primary_runtime_input",
        value="audio",
        source="heuristic",
        evidence=["heuristic:role-aware freeform analysis"],
        confidence="high",
    )
    state.resolved_slots["terminal_output"] = ResolvedSlot(
        name="terminal_output",
        value="docx_document",
        source=source,
        evidence=[f"{source}:final_output_mode"],
        confidence="high",
    )

    merge_llm_resolved_slots(
        state,
        SlotClassificationResult(
            slot_outcomes={
                "terminal_output": ExplicitlyUncertainSlotClassificationOutcome(
                    quote=ClassifiedEvidence(
                        source_id="user_message:test",
                        quote="not sure what the final output should be",
                    )
                )
            }
        ),
        prompt_hash="c" * 64,
        freeform_text="",
    )
    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert state.resolved_slots["terminal_output"].value == "docx_document"
    assert state.resolved_slots["terminal_output"].source == source
    assert "terminal_output" not in policy.allowed_ask_question_targets


def test_policy_asks_missing_core_slots_even_without_discovery_selection() -> None:
    policy = build_planner_action_policy(
        session_state=PlanningState.empty(),
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == (
        "primary_runtime_input",
        "terminal_output",
    )


def test_policy_normalizes_legacy_discovery_question_ids_to_slot_targets() -> None:
    policy = build_planner_action_policy(
        session_state=PlanningState.empty(),
        selected_discovery_question_ids=("final_output_mode",),
    )

    assert policy.allowed_ask_question_targets == (
        "primary_runtime_input",
        "terminal_output",
    )


def test_policy_allows_requirements_confirmation_after_architecture_commit() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_architecture_commit(),
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("confirm_requirements",)


def test_policy_keeps_discovery_selected_question_after_architecture_commit() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_architecture_commit(),
        selected_discovery_question_ids=("runtime_metadata_fields",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("runtime_metadata_fields",)


def test_policy_keeps_renderable_non_slot_discovery_question() -> None:
    state = _state_with_resolved_slots(
        "primary_runtime_input",
        "terminal_output",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=("flow_input_architecture",),
    )

    assert policy.allowed_action_kinds == ("ask_question",)
    assert policy.allowed_ask_question_targets == ("flow_input_architecture",)


def test_policy_revises_committed_architecture_when_commit_grade_slots_drift() -> None:
    state = _state_with_architecture_commit()
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    state.resolved_slots["pdf_generation_mode"] = _slot(
        "pdf_generation_mode",
        "generated_pdf",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "flexible_document_case",
    )
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "both",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("revise_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_revises_commit_when_report_disposition_changes() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "documents",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    state.resolved_slots["pdf_generation_mode"] = _slot(
        "pdf_generation_mode",
        "generated_pdf",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "multiple_documents_case",
    )
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "per_source_sections",
    )
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    state.architecture_commit = finalize_architecture_commit(draft)
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "both",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("revise_architecture",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_keeps_pinned_commit_when_only_weak_slot_conflicts() -> None:
    state = _state_with_architecture_commit()
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
        source="model",
        confidence="medium",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
        requirements_confirmed=True,
    )

    assert policy.allowed_action_kinds == ("propose_plan",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_ignores_stale_weak_report_disposition_after_commit() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "text",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
    )
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    state.architecture_commit = finalize_architecture_commit(draft)
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "both",
        source="heuristic",
        confidence="high",
    )

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=(),
    )

    assert policy.allowed_action_kinds == ("confirm_requirements",)
    assert policy.allowed_ask_question_targets == ()


def test_policy_allows_plan_after_architecture_and_requirements_confirmation() -> None:
    policy = build_planner_action_policy(
        session_state=_state_with_architecture_commit(),
        selected_discovery_question_ids=(),
        requirements_confirmed=True,
    )

    assert policy.allowed_action_kinds == ("propose_plan",)
