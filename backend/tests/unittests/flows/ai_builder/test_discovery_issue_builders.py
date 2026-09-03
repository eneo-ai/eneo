from __future__ import annotations

import pytest

import eneo.flows.ai_builder.ai_builder_discovery as discovery
from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    ultra_vague_terminal_output_choice_is_vague,
)
from eneo.flows.ai_builder.ai_builder_discovery_profile_builder import (
    build_discovery_profile,
)
from eneo.flows.ai_builder.ai_builder_discovery_questions import (
    comparison_scope_conflict_question,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.planning_state import (
    MappedFileLimit,
    PlanningState,
    ResolvedSlot,
)


def test_final_output_mode_builder_prefers_output_vague_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery, "_terminal_output_is_vague", lambda profile: True)
    monkeypatch.setattr(
        discovery, "_ultra_vague_terminal_output_choice_is_vague", lambda profile: True
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="Summarize uploaded documents.",
            metadata={"ui_language": "en"},
        )
    ]
    profile = build_discovery_profile(conversation)

    issue = discovery._build_terminal_output_issue(conversation, profile)

    assert issue is not None
    assert issue.issue_id == "terminal_output"
    assert issue.message == (
        "The final output format is still too vague to design the flow confidently."
    )


def test_swedish_inflected_summary_request_reaches_terminal_output_clarification() -> (
    None
):
    profile = build_discovery_profile(
        [
            ConversationMessage(
                role="user",
                content="Sammanfatta uppladdade dokument.",
                metadata={"ui_language": "sv"},
            )
        ]
    )

    assert ultra_vague_terminal_output_choice_is_vague(profile) is True


def test_json_comparison_request_does_not_ask_document_comparison_scope() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="json",
            source="structured_answer",
            evidence=["question_answer:primary_runtime_input"],
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_json",
            source="structured_answer",
            evidence=["question_answer:terminal_output"],
            confidence="high",
        ),
    }
    conversation = [
        ConversationMessage(
            role="user",
            content="Compare fields in the input JSON and return JSON.",
            metadata={"ui_language": "en"},
        )
    ]
    profile = build_discovery_profile(conversation, planning_state=state)

    assert profile.comparison_requested is True
    assert discovery._build_comparison_scope_issue(conversation, profile) is None


def test_fixed_discovery_questions_do_not_advertise_custom_answers() -> None:
    assert comparison_scope_conflict_question("en").allow_custom is False


def _committed_state(*, primary_input: str) -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value=primary_input,
            source="structured_answer",
            confidence="high",
            evidence=["question_answer:primary_runtime_input"],
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="structured_answer",
            confidence="high",
            evidence=["question_answer:terminal_output"],
        ),
    }
    if primary_input == "audio":
        # An audio flow with a text terminal cannot commit an architecture
        # until the purpose settles whether the transcript is the result.
        state.resolved_slots["post_processing_goal"] = ResolvedSlot(
            name="post_processing_goal",
            value="stop_after_primary_operation",
            source="structured_answer",
            confidence="high",
            evidence=["question_answer:post_processing_goal"],
        )
    if primary_input == "documents":
        state.resolved_slots["document_material_scope"] = ResolvedSlot(
            name="document_material_scope",
            value="multiple_documents_case",
            source="structured_answer",
            confidence="high",
            evidence=["question_answer:document_material_scope"],
        )
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    state.architecture_commit = finalize_architecture_commit(draft)
    return state


def test_mapped_file_limit_is_not_asked_for_audio_architecture() -> None:
    state = _committed_state(primary_input="audio")
    state.mapped_file_limit = MappedFileLimit(
        proposed_value=8,
        diagnostic="confirmation_required",
    )

    analysis = discovery.analyze_discovery(
        [ConversationMessage(role="user", content="Transcribe meeting audio")],
        planning_state=state,
    )

    assert "mapped_file_limit" not in analysis.selected_question_ids


def test_mapped_file_limit_waits_for_architecture_revision() -> None:
    state = _committed_state(primary_input="documents")
    state.resolved_slots["primary_runtime_input"] = ResolvedSlot(
        name="primary_runtime_input",
        value="audio",
        source="structured_answer",
        confidence="high",
        evidence=["question_answer:primary_runtime_input"],
    )
    state.mapped_file_limit = MappedFileLimit(
        proposed_value=8,
        diagnostic="confirmation_required",
    )

    analysis = discovery.analyze_discovery(
        [ConversationMessage(role="user", content="Use audio instead")],
        planning_state=state,
    )

    assert "mapped_file_limit" not in analysis.selected_question_ids


def test_mapped_file_limit_reask_explains_policy_ceiling() -> None:
    state = _committed_state(primary_input="documents")
    state.mapped_file_limit = MappedFileLimit(
        proposed_value=8,
        diagnostic="exceeds_policy",
    )

    followup = discovery.build_registry_question_followup(
        "mapped_file_limit",
        [ConversationMessage(role="user", content="Process uploaded documents")],
        planning_state=state,
    )

    assert followup is not None
    assert followup.assistant_text == (
        "Enter a positive whole number no higher than the organization limit (8)."
    )
