from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorCode,
    AIBuilderErrorEvent,
    AIBuilderErrorPhase,
    build_ai_builder_error_event,
)


def build_session_send_lease_lost_event(*, request_id: str) -> AIBuilderErrorEvent:
    return build_ai_builder_error_event(
        message=(
            "The AI Builder session lock was lost while the planner was running. "
            "Please try again."
        ),
        code=AIBuilderErrorCode.SESSION_SEND_LEASE_LOST,
        phase=AIBuilderErrorPhase.PLANNER,
        request_id=request_id,
    )


def build_planner_upstream_error_event(*, request_id: str) -> AIBuilderErrorEvent:
    return build_ai_builder_error_event(
        message="The AI planner failed. Please try again.",
        code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
        phase=AIBuilderErrorPhase.PLANNER,
        request_id=request_id,
    )


__all__ = [
    "build_planner_upstream_error_event",
    "build_session_send_lease_lost_event",
]
