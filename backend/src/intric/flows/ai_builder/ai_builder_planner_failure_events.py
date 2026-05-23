from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from intric.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
    build_ai_builder_error_event,
)
from intric.flows.ai_builder.ai_builder_orchestrator import PlannerOutput
from intric.flows.ai_builder.ai_builder_planner_turn import PlannerTurnResult
from intric.flows.ai_builder.ai_builder_response_format import (
    PlannerResponseFormatSelection,
)
from intric.flows.ai_builder.pattern_registry import (
    PATTERN_REGISTRY_VERSION,
)
from intric.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
)
from intric.main.logging import get_logger
from intric.observability.failure_events import (
    log_failure_event,
    make_failure_fingerprint,
    schema_fingerprint,
)

logger = get_logger(__name__)

_PLANNER_OUTPUT_SCHEMA_HASH: str = schema_fingerprint(PlannerOutput.model_json_schema())


@dataclass(frozen=True, slots=True)
class PlannerTurnResultEventRequest:
    turn_result: PlannerTurnResult
    request_id: str
    session_id: UUID
    tenant_id: UUID
    planning_state_version: int
    planner_prompt_hash: str | None
    response_format_selection: PlannerResponseFormatSelection
    max_output_tokens: int


def build_session_send_lease_lost_event(*, request_id: str) -> dict[str, str]:
    return build_ai_builder_error_event(
        message=(
            "The AI Builder session lock was lost while the planner was running. "
            "Please try again."
        ),
        code=AIBuilderErrorCode.SESSION_SEND_LEASE_LOST,
        phase=AIBuilderErrorPhase.PLANNER,
        request_id=request_id,
    )


def build_planner_upstream_error_event(*, request_id: str) -> dict[str, str]:
    return build_ai_builder_error_event(
        message="The AI planner failed. Please try again.",
        code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
        phase=AIBuilderErrorPhase.PLANNER,
        request_id=request_id,
    )


def record_planner_turn_result(request: PlannerTurnResultEventRequest) -> None:
    parse_failure_diagnostics = _parse_failure_diagnostics(request.turn_result)
    logger.info(
        "AI Builder planner turn metrics",
        extra={
            "outcome_kind": request.turn_result.kind,
            "llm_calls_made": request.turn_result.llm_calls_made,
            "repair_attempts": request.turn_result.repair_attempts,
            "parse_repair_attempts": request.turn_result.parse_repair_attempts,
            "architecture_commit_populated": (
                request.turn_result.turn_telemetry.architecture_commit_populated
            ),
            "wall_clock_ms": request.turn_result.turn_telemetry.wall_clock_ms,
            "prompt_tokens": request.turn_result.turn_telemetry.prompt_tokens,
            "completion_tokens": request.turn_result.turn_telemetry.completion_tokens,
            "total_tokens": request.turn_result.turn_telemetry.total_tokens,
            "finish_reason": request.turn_result.turn_telemetry.finish_reason,
            "request_id": request.request_id,
            "planner_prompt_hash": request.planner_prompt_hash,
            "planner_output_schema_hash": _PLANNER_OUTPUT_SCHEMA_HASH,
            "pattern_registry_version": PATTERN_REGISTRY_VERSION,
            "fcm_version": FCM_VERSION,
            "planner_contract_version": PLANNER_CONTRACT_VERSION,
            "builder_schema_version": BUILDER_SCHEMA_VERSION,
            "planning_state_version": request.planning_state_version,
            **_structured_output_log_fields(request.response_format_selection),
            **parse_failure_diagnostics,
        },
    )

    if request.turn_result.kind in ("parse_failed", "rejected"):
        _emit_planner_failure_event(
            turn_result=request.turn_result,
            request_id=request.request_id,
            session_id=request.session_id,
            tenant_id=request.tenant_id,
            planning_state_version=request.planning_state_version,
            planner_prompt_hash=request.planner_prompt_hash,
            parse_failure_diagnostics=parse_failure_diagnostics,
        )


def build_planner_turn_error_event(
    request: PlannerTurnResultEventRequest,
) -> dict[str, str] | None:
    turn_result = request.turn_result
    if turn_result.kind == "parse_failed":
        completion = turn_result.final_completion
        if completion is not None and completion.finish_reason == "length":
            logger.warning(
                "LLM response truncated (finish_reason=length) - "
                f"max_tokens={request.max_output_tokens} may be too low for this model"
            )
            return build_ai_builder_error_event(
                message=(
                    "The flow was too complex for the current model's output limit. "
                    "Try simplifying the flow or using a more capable model."
                ),
                code=AIBuilderErrorCode.PLANNER_OUTPUT_TOO_LONG,
                phase=AIBuilderErrorPhase.PLANNER,
                request_id=request.request_id,
            )
        return build_ai_builder_error_event(
            message="The AI planner response could not be parsed. Please try again.",
            code=AIBuilderErrorCode.PLANNER_PARSE_ERROR,
            phase=AIBuilderErrorPhase.PLANNER,
            request_id=request.request_id,
        )
    if turn_result.kind == "rejected":
        return build_ai_builder_error_event(
            message=(
                "The assistant couldn't complete that step. Please rephrase your "
                "request or try again."
            ),
            code=AIBuilderErrorCode.PLANNER_REJECTED,
            phase=AIBuilderErrorPhase.PLANNER,
            request_id=request.request_id,
        )
    return None


def _parse_failure_diagnostics(turn_result: PlannerTurnResult) -> dict[str, Any]:
    if (
        turn_result.kind == "parse_failed"
        and turn_result.parse_failure_diagnostics is not None
    ):
        return turn_result.parse_failure_diagnostics
    return {}


def _structured_output_log_fields(
    response_format_selection: PlannerResponseFormatSelection,
) -> dict[str, Any]:
    capability = response_format_selection.capability_decision
    return {
        "structured_output_capability_path": capability.mode.value,
        "structured_output_request_mode": response_format_selection.request_mode.value,
        "structured_output_decision_source": capability.source.value,
        "structured_output_response_schema_supported": (
            capability.supports_response_schema
        ),
        "structured_output_response_format_supported": (
            capability.supports_response_format
        ),
        "planner_output_strict_blocked": (
            response_format_selection.planner_output_strict_blocked
        ),
        "planner_output_strict_blocker_count": len(
            response_format_selection.planner_output_strict_blockers
        ),
    }


def _extract_first_validation_loc(locs: Any) -> str | None:
    if not isinstance(locs, list) or not locs:
        return None
    first = cast(Any, locs[0])
    if not isinstance(first, dict):
        return None
    loc_value = cast(Any, first).get("loc")
    return None if loc_value is None else str(loc_value)


def _emit_planner_failure_event(
    *,
    turn_result: PlannerTurnResult,
    request_id: str,
    session_id: UUID,
    tenant_id: UUID,
    planning_state_version: int,
    planner_prompt_hash: str | None,
    parse_failure_diagnostics: dict[str, Any],
) -> None:
    failure_kind = turn_result.kind
    failure_code: str | None = None
    fingerprint_locus: str | None = None
    safe_detail: dict[str, Any] = {}

    if failure_kind == "parse_failed":
        parse_error_kind = parse_failure_diagnostics.get("parse_error_kind")
        failure_code = str(parse_error_kind) if parse_error_kind is not None else None
        fingerprint_locus = _extract_first_validation_loc(
            parse_failure_diagnostics.get("validation_locs")
        )
        safe_detail = dict(parse_failure_diagnostics)
    elif failure_kind == "rejected" and turn_result.rejection is not None:
        rejection = turn_result.rejection
        failure_code = rejection.code
        fingerprint_locus = rejection.code
        safe_detail = {
            "rejection_code": rejection.code,
            "rejection_detail": rejection.detail,
            "current_version": rejection.current_version,
        }

    log_failure_event(
        logger,
        event="ai_builder.failure",
        component="ai_builder",
        operation="planner_turn",
        failure_kind=failure_kind,
        failure_code=failure_code,
        failure_fingerprint=make_failure_fingerprint(
            failure_kind, failure_code, fingerprint_locus
        ),
        request_id=request_id,
        session_id=str(session_id),
        tenant_id=str(tenant_id),
        replay_handle={
            "session_id": str(session_id),
            "request_id": request_id,
            "planning_state_version": planning_state_version,
            "planner_prompt_hash": planner_prompt_hash,
            "planner_output_schema_hash": _PLANNER_OUTPUT_SCHEMA_HASH,
            "pattern_registry_version": PATTERN_REGISTRY_VERSION,
            "fcm_version": FCM_VERSION,
            "planner_contract_version": PLANNER_CONTRACT_VERSION,
            "builder_schema_version": BUILDER_SCHEMA_VERSION,
        },
        safe_detail=safe_detail,
    )
