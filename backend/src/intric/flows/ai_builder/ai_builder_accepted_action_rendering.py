from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    requirements_summary_to_metadata,
)
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_event_models import RequirementsSummaryPayload
from intric.flows.ai_builder.ai_builder_events import (
    build_requirements_summary_event,
    build_status_event,
    build_text_event,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    normalize_requirements_summary_for_flow,
)
from intric.flows.ai_builder.ai_builder_orchestrator import (
    AskQuestionAction,
    CommitArchitectureAction,
    ConfirmRequirementsAction,
    ConfirmRequirementsPayload,
    PlannerOutput,
)
from intric.flows.ai_builder.ai_builder_requirements_state import (
    build_requirements_version,
)
from intric.flows.ai_builder.ai_builder_telemetry import (
    build_assistant_message_metadata,
    build_planner_telemetry_from_turn,
)
from intric.flows.flow_authoring_spec import JsonObject

if TYPE_CHECKING:
    from intric.flows.ai_builder.ai_builder_planner_turn import TurnTelemetry
    from intric.flows.domain.flow import Flow


@dataclass(frozen=True, slots=True)
class RequirementsSummaryRenderContext:
    conversation: list[ConversationMessage]
    flow: "Flow | None"
    ui_language: str | None


def build_accepted_action_messages(
    accepted: PlannerOutput,
    telemetry: TurnTelemetry,
    *,
    context: RequirementsSummaryRenderContext,
    new_messages_start: int,
    used_auxiliary_llm: bool,
) -> list[ConversationMessage]:
    action = accepted.planner_action
    base_metadata: JsonObject | None = None

    match action:
        case AskQuestionAction():
            assistant_content = action.payload.prompt
            base_metadata = {"question_id": action.payload.question_id}
        case CommitArchitectureAction():
            return [*context.conversation[new_messages_start:]]
        case ConfirmRequirementsAction():
            assistant_content = action.payload.summary
            requirements_payload = build_requirements_summary_payload(
                action.payload,
                context=context,
            )
            base_metadata = requirements_summary_to_metadata(requirements_payload)
        case _ as unhandled:
            assert_never(unhandled)

    planner_telemetry = build_planner_telemetry_from_turn(
        telemetry,
        used_auxiliary_llm=used_auxiliary_llm,
    )
    return [
        *context.conversation[new_messages_start:],
        ConversationMessage(
            role="assistant",
            content=assistant_content,
            metadata=build_assistant_message_metadata(
                context.conversation,
                planner_telemetry=planner_telemetry,
                base_metadata=base_metadata,
            ),
        ),
    ]


def build_accepted_action_events(
    accepted: PlannerOutput,
    *,
    context: RequirementsSummaryRenderContext,
) -> list[dict[str, str]]:
    action = accepted.planner_action
    match action:
        case AskQuestionAction():
            return [build_text_event(action.payload.prompt)]
        case CommitArchitectureAction():
            return [build_status_event("architecture_committed")]
        case ConfirmRequirementsAction():
            return [
                build_requirements_summary_event(
                    build_requirements_summary_payload(action.payload, context=context)
                )
            ]
        case _ as unhandled:
            assert_never(unhandled)


def build_requirements_summary_payload(
    payload: ConfirmRequirementsPayload,
    *,
    context: RequirementsSummaryRenderContext,
) -> RequirementsSummaryPayload:
    normalized = normalize_requirements_summary_for_flow(
        payload.model_dump(),
        conversation=context.conversation,
        flow=context.flow,
        language=context.ui_language,
    )
    requirements_payload = RequirementsSummaryPayload.model_validate(normalized)
    return requirements_payload.model_copy(
        update={
            "requirements_version": build_requirements_version(requirements_payload)
        },
        deep=True,
    )


__all__ = [
    "RequirementsSummaryRenderContext",
    "build_accepted_action_events",
    "build_accepted_action_messages",
    "build_requirements_summary_payload",
]
