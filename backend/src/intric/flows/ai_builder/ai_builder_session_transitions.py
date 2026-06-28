from __future__ import annotations

from intric.flows.ai_builder.ai_builder_domain_models import SessionStatus
from intric.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)

_ALLOWED_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CHATTING: {
        SessionStatus.CHATTING,
        SessionStatus.AWAITING_APPROVAL,
        SessionStatus.CANCELLED,
    },
    SessionStatus.AWAITING_APPROVAL: {
        SessionStatus.CHATTING,
        SessionStatus.APPLIED,
        SessionStatus.CANCELLED,
    },
    SessionStatus.APPLIED: {SessionStatus.APPLIED},
    SessionStatus.CANCELLED: {SessionStatus.CANCELLED},
}


def ensure_valid_session_status_transition(
    *,
    current: SessionStatus,
    next_status: SessionStatus,
) -> None:
    if next_status in _ALLOWED_TRANSITIONS[current]:
        return
    raise AIBuilderBadRequestException(
        f"Invalid AI Builder session transition: {current.value} -> {next_status.value}.",
        code=AIBuilderErrorCode.INVALID_SESSION_TRANSITION,
    )
