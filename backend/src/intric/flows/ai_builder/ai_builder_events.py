from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from intric.flows.ai_builder.ai_builder_edit_models import CompiledEditResult

from intric.flows.ai_builder.ai_builder_event_models import (
    AIBuilderErrorEventData,
    AIBuilderPlanEventData,
    AIBuilderStatusEventData,
    AIBuilderTextEventData,
    RequirementsSummaryPayload,
    StructuredQuestionPayload,
)
from intric.flows.ai_builder.ai_builder_models import PlannerPlanEnvelope
from intric.main.exceptions import ErrorCodes

SSE_EVENT_TEXT = "text"
SSE_EVENT_PLAN = "plan"
SSE_EVENT_QUESTION = "question"
SSE_EVENT_REQUIREMENTS_SUMMARY = "requirements_summary"
SSE_EVENT_ERROR = "error"
SSE_EVENT_STATUS = "status"
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


def build_question_event(question_data: dict[str, Any]) -> dict[str, str]:
    payload = StructuredQuestionPayload.model_validate(question_data)
    return {
        "event": SSE_EVENT_QUESTION,
        "data": payload.model_dump_json(exclude_none=True),
    }


def error_payload(
    *,
    message: str,
    code: str,
    phase: str,
    intric_error_code: ErrorCodes | int | None = None,
    request_id: str | None = None,
) -> str:
    resolved_error_code = _resolve_intric_error_code(code=code, phase=phase)
    if intric_error_code is not None:
        resolved_error_code = int(intric_error_code)
    return AIBuilderErrorEventData(
        error=message,
        message=message,
        code=code,
        phase=phase,
        intric_error_code=resolved_error_code,
        request_id=request_id or str(uuid4()),
    ).model_dump_json(exclude_none=True)


def build_error_event(
    *,
    message: str,
    code: str,
    phase: str,
    intric_error_code: ErrorCodes | int | None = None,
    request_id: str | None = None,
) -> dict[str, str]:
    return {
        "event": SSE_EVENT_ERROR,
        "data": error_payload(
            message=message,
            code=code,
            phase=phase,
            intric_error_code=intric_error_code,
            request_id=request_id,
        ),
    }


def _resolve_intric_error_code(*, code: str, phase: str) -> int | None:
    bad_request_codes = {
        "planner_output_too_long",
        "self_correction_invalid_payload",
        "self_correction_quality_failure",
        "self_correction_invalid_plan",
        "question_recovery_unavailable",
        "question_recovery_exhausted",
        "question_parse_error",
        "unsupported_structured_question",
        "confirm_requirements_parse_error",
        "confirm_requirements_invalid",
        "edit_parse_error",
        "edit_validation_error",
        "edit_compile_error",
        "edit_spec_validation_error",
        "session_message_in_progress",
    }
    internal_error_codes = {
        "planner_upstream_error",
        "planner_stream_failed",
    }
    if code in bad_request_codes:
        return int(ErrorCodes.BAD_REQUEST)
    if code in internal_error_codes:
        return int(ErrorCodes.INTERNAL_SERVER_ERROR)
    if phase in {"planner", "router"}:
        return int(ErrorCodes.INTERNAL_SERVER_ERROR)
    return None


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
    edit_result: "CompiledEditResult | None" = None,
) -> dict[str, str]:
    edit_kwargs: dict[str, Any] = {}
    if edit_result is not None:
        edit_kwargs["edit_diff"] = edit_result.diff.model_dump(mode="json")
        edit_kwargs["edit_confidence"] = edit_result.confidence
        edit_kwargs["edit_warnings"] = edit_result.warnings
        if edit_result.advisories:
            edit_kwargs["edit_advisories"] = [
                a.model_dump(mode="json") for a in edit_result.advisories
            ]
        edit_kwargs["edit_risk_flags"] = edit_result.risk_flags

    return {
        "event": SSE_EVENT_PLAN,
        "data": AIBuilderPlanEventData(
            plan_id=plan_id,
            envelope=envelope.model_copy(update={"reasoning": None}, deep=True),
            **edit_kwargs,
        ).model_dump_json(exclude_none=True),
    }
