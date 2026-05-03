"""Reconstruction contract for requirements-state from conversation metadata.

The planner's structured-JSON transport emits a `confirm_requirements`
action whose payload carries the full `RequirementsSummaryPayload`
shape. The builder persists that shape as `metadata.requirements_summary`
on the assistant message it writes inside the commit_turn savepoint.
`resolve_requirements_state` must recognize that shape so subsequent
turns can re-render the confirmed requirements into the system prompt
and gate later flows on user confirmation.
"""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_models import (
    ConversationMessage,
    RequirementsSummaryPayload,
)
from intric.flows.ai_builder.ai_builder_requirements_state import (
    build_requirements_version,
    resolve_requirements_state,
)


def _summary_payload() -> RequirementsSummaryPayload:
    return RequirementsSummaryPayload.model_validate(
        {
            "summary": "A flow that extracts data from PDFs into structured JSON.",
            "key_decisions": [
                {"topic": "Input", "decision": "Single PDF per run"},
                {"topic": "Output", "decision": "JSON with extracted fields"},
            ],
            "input_description": "A PDF document uploaded by the user.",
            "output_description": "JSON object with extracted key fields.",
            "assumptions": ["User provides legible PDFs"],
            "manual_setup_notes": ["Connect knowledge base with field glossary"],
        }
    )


class TestResolveRequirementsStateFromAssistantMetadata:
    def test_assistant_metadata_shape_populates_latest_summary(self) -> None:
        payload = _summary_payload()
        version = build_requirements_version(payload)
        conversation = [
            ConversationMessage(role="user", content="Build a PDF extractor"),
            ConversationMessage(
                role="assistant",
                content="Here is the summary I have so far.",
                metadata={
                    "requirements_summary": payload.model_dump(mode="json"),
                    "requirements_version": version,
                },
            ),
        ]

        state = resolve_requirements_state(conversation)

        assert state.latest_summary is not None
        assert state.latest_summary.summary == payload.summary
        assert state.latest_version == version
        assert state.confirmed is False  # no user confirmation yet

    def test_user_confirmation_completes_the_confirmed_contract(self) -> None:
        payload = _summary_payload()
        version = build_requirements_version(payload)
        conversation = [
            ConversationMessage(role="user", content="Build a PDF extractor"),
            ConversationMessage(
                role="assistant",
                content="Here is the summary I have so far.",
                metadata={
                    "requirements_summary": payload.model_dump(mode="json"),
                    "requirements_version": version,
                },
            ),
            ConversationMessage(
                role="user",
                content="Yes, proceed with the plan",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": version,
                },
            ),
        ]

        state = resolve_requirements_state(conversation)

        assert state.latest_summary is not None
        assert state.latest_version == version
        assert state.confirmed_version == version
        assert state.confirmed is True

    def test_legacy_user_confirmation_without_version_confirms_latest_summary(
        self,
    ) -> None:
        payload = _summary_payload()
        version = build_requirements_version(payload)
        conversation = [
            ConversationMessage(role="user", content="Build a PDF extractor"),
            ConversationMessage(
                role="assistant",
                content="Here is the summary I have so far.",
                metadata={
                    "requirements_summary": payload.model_dump(mode="json"),
                    "requirements_version": version,
                },
            ),
            ConversationMessage(
                role="user",
                content="Yes, proceed with the plan",
                metadata={"requirements_confirmed": True},
            ),
        ]

        state = resolve_requirements_state(conversation)

        assert state.latest_version == version
        assert state.confirmed_version == version
        assert state.confirmed is True

    def test_version_drift_on_user_confirmation_blocks_confirmed_flag(self) -> None:
        payload = _summary_payload()
        version = build_requirements_version(payload)
        conversation = [
            ConversationMessage(
                role="assistant",
                content="Summary",
                metadata={
                    "requirements_summary": payload.model_dump(mode="json"),
                    "requirements_version": version,
                },
            ),
            ConversationMessage(
                role="user",
                content="Confirmed",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": "stale-hash",
                },
            ),
        ]

        state = resolve_requirements_state(conversation)

        assert state.latest_summary is not None
        assert state.confirmed is False
