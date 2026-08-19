from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_discovery import analyze_discovery
from eneo.flows.ai_builder.ai_builder_discovery_profile_builder import (
    build_discovery_profile,
)
from eneo.flows.ai_builder.ai_builder_discovery_signal_inference import (
    infer_answer_signals_from_text,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)


def test_generic_underlag_does_not_create_domain_or_runtime_metadata_evidence() -> None:
    conversation = [
        ConversationMessage(
            role="user",
            content=(
                "Jag vill skapa ett flöde där användaren laddar upp underlag "
                "och får en kort sammanfattning som text."
            ),
            metadata={"ui_language": "sv"},
        )
    ]

    signals = infer_answer_signals_from_text(conversation[0].content)
    profile = build_discovery_profile(conversation)
    analysis = analyze_discovery(conversation)
    question_ids = {
        issue.suggestion.question_id
        for issue in analysis.blocking_issues
        if issue.suggestion is not None
    }

    assert "runtime_metadata_fields" not in signals
    assert profile.resolved_slot("runtime_metadata_fields") is None
    assert "processing_scope" not in question_ids


def test_generic_source_material_does_not_establish_flow_purpose() -> None:
    for text in ("Underlag", "Source material"):
        analysis = analyze_discovery(
            [
                ConversationMessage(
                    role="user",
                    content=text,
                    metadata={"ui_language": "sv"},
                )
            ]
        )

        assert analysis.mvs_met is False


def test_structured_runtime_fields_persist_without_reasking() -> None:
    conversation = [
        ConversationMessage(
            role="user",
            content="Summarize an uploaded document as structured text.",
            metadata={"ui_language": "en"},
        ),
        ConversationMessage(
            role="user",
            content="Collect richer runtime metadata.",
            metadata={
                "question_answer": {
                    "question_id": "runtime_metadata_fields",
                    "selected_option_id": "detailed_runtime_metadata",
                    "selected_values": ["detailed_runtime_metadata"],
                    "answer": "detailed_runtime_metadata",
                },
                "ui_language": "en",
            },
        ),
    ]

    planning_state = build_planning_state_from_conversation(conversation)
    profile = build_discovery_profile(
        conversation,
        planning_state=planning_state,
    )
    analysis = analyze_discovery(
        conversation,
        planning_state=planning_state,
    )

    assert planning_state.resolved_slots["runtime_metadata_fields"].value == (
        "detailed_runtime_metadata"
    )
    runtime_metadata = profile.resolved_slot("runtime_metadata_fields")
    assert runtime_metadata is not None
    assert runtime_metadata.value == "detailed_runtime_metadata"
    assert all(
        issue.suggestion is None
        or issue.suggestion.question_id != "runtime_metadata_fields"
        for issue in analysis.blocking_issues
    )
