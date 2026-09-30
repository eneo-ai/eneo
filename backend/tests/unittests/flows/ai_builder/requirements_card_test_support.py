"""The one recipe for a requirements card the real disclosure builder rendered."""

from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    requirements_summary_to_metadata,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_requirements_disclosure import (
    build_requirements_disclosure,
)
from eneo.flows.ai_builder.planning_state import PlanningState, ResolvedSlot


def pending_card_message(
    *,
    runtime_input: str,
    terminal_output: str,
    ui_language: str = "sv",
) -> ConversationMessage:
    """A card for a disclosure of these two slots that nobody has accepted."""

    disclosed = PlanningState.empty()
    disclosed.resolved_slots = {
        name: ResolvedSlot(
            name=name,
            value=value,
            source="structured_answer",
            confidence="high",
            evidence=[f"question_answer:{name}"],
        )
        for name, value in (
            ("primary_runtime_input", runtime_input),
            ("terminal_output", terminal_output),
        )
    }
    return ConversationMessage(
        role="assistant",
        content="Requirements presented to user.",
        metadata=requirements_summary_to_metadata(
            build_requirements_disclosure(disclosed, ui_language=ui_language)
        ),
    )
