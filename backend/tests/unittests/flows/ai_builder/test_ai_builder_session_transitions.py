from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderTurnState,
    SessionStatus,
)
from eneo.flows.ai_builder.ai_builder_session_transitions import (
    AI_BUILDER_SESSION_TRANSITIONS,
    AI_BUILDER_TURN_TRANSITIONS,
    effective_builder_turn_state,
    ensure_valid_session_status_transition,
)
from eneo.main.exceptions import BadRequestException


def test_builder_transition_owners_are_exhaustive() -> None:
    assert set(AI_BUILDER_SESSION_TRANSITIONS) == set(SessionStatus)
    assert set(AI_BUILDER_TURN_TRANSITIONS) == set(BuilderTurnState)


def test_local_no_call_completion_can_commit_an_open_turn() -> None:
    assert (
        BuilderTurnState.COMMITTED
        in AI_BUILDER_TURN_TRANSITIONS[BuilderTurnState.OPEN].legal_next_states
    )


@pytest.mark.parametrize(
    ("stored_state", "expired_state"),
    [
        (BuilderTurnState.OPEN, BuilderTurnState.FAILED_BEFORE_PROVIDER),
        (
            BuilderTurnState.PROCESSING,
            BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN,
        ),
        (BuilderTurnState.COMMITTED, BuilderTurnState.COMMITTED),
        (
            BuilderTurnState.FAILED_BEFORE_PROVIDER,
            BuilderTurnState.FAILED_BEFORE_PROVIDER,
        ),
        (
            BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN,
            BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN,
        ),
    ],
)
def test_effective_builder_turn_state_projects_only_expired_active_turns(
    stored_state: BuilderTurnState,
    expired_state: BuilderTurnState,
) -> None:
    assert (
        effective_builder_turn_state(
            stored_state,
            has_active_request=False,
            lock_is_active=False,
        )
        is stored_state
    )
    assert (
        effective_builder_turn_state(
            stored_state,
            has_active_request=True,
            lock_is_active=True,
        )
        is stored_state
    )
    assert (
        effective_builder_turn_state(
            stored_state,
            has_active_request=True,
            lock_is_active=False,
        )
        is expired_state
    )


@pytest.mark.parametrize(
    ("current", "next_status"),
    [
        (SessionStatus.CHATTING, SessionStatus.AWAITING_APPROVAL),
        (SessionStatus.CHATTING, SessionStatus.CANCELLED),
        (SessionStatus.AWAITING_APPROVAL, SessionStatus.CHATTING),
        (SessionStatus.AWAITING_APPROVAL, SessionStatus.APPLIED),
        (SessionStatus.AWAITING_APPROVAL, SessionStatus.CANCELLED),
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


def test_applied_session_cannot_be_cancelled() -> None:
    with pytest.raises(
        BadRequestException, match="Invalid AI Builder session transition"
    ):
        ensure_valid_session_status_transition(
            current=SessionStatus.APPLIED,
            next_status=SessionStatus.CANCELLED,
        )
