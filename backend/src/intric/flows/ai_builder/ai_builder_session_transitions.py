from __future__ import annotations

from intric.flows.ai_builder.ai_builder_domain_models import SessionStatus
from intric.main.exceptions import BadRequestException

_ALLOWED_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.CHATTING: {
        SessionStatus.CHATTING,
        SessionStatus.AWAITING_APPROVAL,
        SessionStatus.CANCELLED,
    },
    SessionStatus.AWAITING_APPROVAL: {
        SessionStatus.CHATTING,
        SessionStatus.APPLYING,
        SessionStatus.CANCELLED,
    },
    SessionStatus.APPLYING: {
        SessionStatus.AWAITING_APPROVAL,
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
    raise BadRequestException(
        f"Invalid AI Builder session transition: {current.value} -> {next_status.value}.",
        code="invalid_session_transition",
    )
