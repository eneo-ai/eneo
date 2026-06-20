from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_domain_models import SessionStatus
from intric.flows.ai_builder.ai_builder_session_transitions import (
    ensure_valid_session_status_transition,
)
from intric.main.exceptions import BadRequestException


@pytest.mark.parametrize(
    ("current", "next_status"),
    [
        (SessionStatus.CHATTING, SessionStatus.AWAITING_APPROVAL),
        (SessionStatus.AWAITING_APPROVAL, SessionStatus.CHATTING),
        (SessionStatus.AWAITING_APPROVAL, SessionStatus.APPLYING),
        (SessionStatus.APPLYING, SessionStatus.APPLIED),
        (SessionStatus.CANCELLED, SessionStatus.CANCELLED),
    ],
)
def test_valid_transitions_are_allowed(
    current: SessionStatus, next_status: SessionStatus
) -> None:
    ensure_valid_session_status_transition(
        current=current,
        next_status=next_status,
    )


def test_invalid_transition_is_rejected() -> None:
    with pytest.raises(
        BadRequestException, match="Invalid AI Builder session transition"
    ):
        ensure_valid_session_status_transition(
            current=SessionStatus.APPLIED,
            next_status=SessionStatus.CHATTING,
        )
