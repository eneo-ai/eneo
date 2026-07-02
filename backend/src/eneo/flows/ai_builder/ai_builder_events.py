from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from eneo.flows.ai_builder.ai_builder_domain_models import FlowBuilderProposalContent
from eneo.flows.ai_builder.ai_builder_event_models import (
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
    AIBuilderStreamEvent,
    AIBuilderTextEvent,
    AIBuilderTextEventData,
    AIBuilderUsageEvent,
    RequirementsSummaryPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_telemetry_models import (
    SessionTelemetrySummary,
)


def encode_ai_builder_stream_event(event: AIBuilderStreamEvent) -> dict[str, str]:
    payload = event.data
    if isinstance(payload, BaseModel):
        data = payload.model_dump_json(exclude_none=True)
    else:
        data = payload
    return {"event": event.event, "data": data}


def build_text_event(text: str) -> AIBuilderTextEvent:
    return AIBuilderTextEvent(data=AIBuilderTextEventData(text=text))


def build_status_event(status: str) -> AIBuilderStatusEvent:
    return AIBuilderStatusEvent(data=AIBuilderStatusEventData(status=status))


def build_usage_event(telemetry: SessionTelemetrySummary) -> AIBuilderUsageEvent:
    return AIBuilderUsageEvent(data=telemetry)


def build_done_event() -> AIBuilderDoneEvent:
    return AIBuilderDoneEvent()


def build_question_event(
    question_data: StructuredQuestionPayload,
) -> AIBuilderQuestionEvent:
    return AIBuilderQuestionEvent(data=question_data)


def build_requirements_summary_event(
    data: RequirementsSummaryPayload,
) -> AIBuilderRequirementsSummaryEvent:
    return AIBuilderRequirementsSummaryEvent(data=data)


def build_plan_event(
    *,
    plan_id: UUID,
    proposal: FlowBuilderProposalContent,
) -> AIBuilderPlanEvent:
    return AIBuilderPlanEvent(
        data=AIBuilderPlanEventData(
            plan_id=plan_id,
            proposal=proposal,
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
    "encode_ai_builder_stream_event",
]
