from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from intric.flows.ai_builder.ai_builder_domain_models import PlannerPlanEnvelope
from intric.flows.ai_builder.ai_builder_edit_models import BuilderPlanEditResult
from intric.flows.ai_builder.ai_builder_event_models import (
    AIBuilderPlanEventData,
    AIBuilderStatusEventData,
    AIBuilderTextEventData,
    RequirementsSummaryPayload,
    StructuredQuestionPayload,
)

SSE_EVENT_TEXT = "text"
SSE_EVENT_PLAN = "plan"
SSE_EVENT_QUESTION = "question"
SSE_EVENT_REQUIREMENTS_SUMMARY = "requirements_summary"
SSE_EVENT_ERROR = "error"
SSE_EVENT_STATUS = "status"
SSE_EVENT_USAGE = "usage"
SSE_EVENT_DONE = "done"


def build_text_event(text: str) -> dict[str, str]:
    return {
        "event": SSE_EVENT_TEXT,
        "data": AIBuilderTextEventData(text=text).model_dump_json(),
    }


def build_status_event(status: str) -> dict[str, str]:
    return {
        "event": SSE_EVENT_STATUS,
        "data": AIBuilderStatusEventData(status=status).model_dump_json(),
    }


def build_usage_event(telemetry: Mapping[str, Any]) -> dict[str, str]:
    return {
        "event": SSE_EVENT_USAGE,
        "data": json.dumps(dict(telemetry), ensure_ascii=False),
    }


def build_question_event(question_data: dict[str, Any]) -> dict[str, str]:
    payload = StructuredQuestionPayload.model_validate(question_data)
    return {
        "event": SSE_EVENT_QUESTION,
        "data": payload.model_dump_json(exclude_none=True),
    }


def build_requirements_summary_event(data: dict[str, Any]) -> dict[str, str]:
    payload = RequirementsSummaryPayload.model_validate(data)
    return {
        "event": SSE_EVENT_REQUIREMENTS_SUMMARY,
        "data": payload.model_dump_json(),
    }


def build_plan_event(
    *,
    plan_id: UUID,
    envelope: PlannerPlanEnvelope,
    edit_result: BuilderPlanEditResult | None = None,
) -> dict[str, str]:
    return {
        "event": SSE_EVENT_PLAN,
        "data": AIBuilderPlanEventData(
            plan_id=plan_id,
            envelope=envelope.model_copy(update={"reasoning": None}, deep=True),
            edit_result_json=edit_result,
        ).model_dump_json(exclude_none=True),
    }
