from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from intric.flows.ai_builder.ai_builder_domain_models import FlowBuilderProposalContent
from intric.flows.ai_builder.ai_builder_event_models import (
    SSE_EVENT_DONE,
    SSE_EVENT_ERROR,
    SSE_EVENT_PLAN,
    SSE_EVENT_QUESTION,
    SSE_EVENT_REQUIREMENTS_SUMMARY,
    SSE_EVENT_STATUS,
    SSE_EVENT_TEXT,
    SSE_EVENT_USAGE,
    AIBuilderDoneEvent,
    AIBuilderPlanEvent,
    AIBuilderPlanEventData,
    AIBuilderQuestionEvent,
    AIBuilderRequirementsSummaryEvent,
    AIBuilderStatusEvent,
    AIBuilderStatusEventData,
    AIBuilderTextEvent,
    AIBuilderTextEventData,
    AIBuilderUsageEvent,
    RequirementsSummaryPayload,
    StructuredQuestionPayload,
)
from intric.flows.ai_builder.ai_builder_telemetry_models import (
    SessionTelemetrySummary,
)


def _to_wire_event(event: BaseModel) -> dict[str, str]:
    event_name = getattr(event, "event")
    payload = getattr(event, "data")
    if not isinstance(event_name, str):
        raise TypeError(f"{event.__class__.__name__}.event must be a string")
    if isinstance(payload, BaseModel):
        data = payload.model_dump_json(exclude_none=True)
    elif isinstance(payload, str):
        data = payload
    else:
        raise TypeError(f"{event.__class__.__name__}.data must be a model or string")
    return {"event": event_name, "data": data}


def build_text_event(text: str) -> dict[str, str]:
    return _to_wire_event(AIBuilderTextEvent(data=AIBuilderTextEventData(text=text)))


def build_status_event(status: str) -> dict[str, str]:
    return _to_wire_event(
        AIBuilderStatusEvent(data=AIBuilderStatusEventData(status=status))
    )


def build_usage_event(telemetry: SessionTelemetrySummary) -> dict[str, str]:
    return _to_wire_event(AIBuilderUsageEvent(data=telemetry))


def build_done_event() -> dict[str, str]:
    return _to_wire_event(AIBuilderDoneEvent())


def build_question_event(question_data: StructuredQuestionPayload) -> dict[str, str]:
    return _to_wire_event(AIBuilderQuestionEvent(data=question_data))


def build_requirements_summary_event(
    data: RequirementsSummaryPayload,
) -> dict[str, str]:
    return _to_wire_event(AIBuilderRequirementsSummaryEvent(data=data))


def build_plan_event(
    *,
    plan_id: UUID,
    proposal: FlowBuilderProposalContent,
) -> dict[str, str]:
    return _to_wire_event(
        AIBuilderPlanEvent(
            data=AIBuilderPlanEventData(
                plan_id=plan_id,
                proposal=proposal,
            )
        )
    )


__all__ = [
    "SSE_EVENT_DONE",
    "SSE_EVENT_ERROR",
    "SSE_EVENT_PLAN",
    "SSE_EVENT_QUESTION",
    "SSE_EVENT_REQUIREMENTS_SUMMARY",
    "SSE_EVENT_STATUS",
    "SSE_EVENT_TEXT",
    "SSE_EVENT_USAGE",
    "build_done_event",
    "build_plan_event",
    "build_question_event",
    "build_requirements_summary_event",
    "build_status_event",
    "build_text_event",
    "build_usage_event",
]
