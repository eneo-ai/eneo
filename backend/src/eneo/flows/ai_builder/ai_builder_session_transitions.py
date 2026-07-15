from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderTurnState,
    SessionStatus,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)

AI_BUILDER_SESSION_TRANSITIONS: Mapping[SessionStatus, frozenset[SessionStatus]] = (
    MappingProxyType(
        {
            SessionStatus.CHATTING: frozenset(
                {
                    SessionStatus.CHATTING,
                    SessionStatus.AWAITING_APPROVAL,
                    SessionStatus.CANCELLED,
                }
            ),
            SessionStatus.AWAITING_APPROVAL: frozenset(
                {
                    SessionStatus.CHATTING,
                    SessionStatus.APPLIED,
                    SessionStatus.CANCELLED,
                }
            ),
            SessionStatus.APPLIED: frozenset({SessionStatus.APPLIED}),
            SessionStatus.CANCELLED: frozenset({SessionStatus.CANCELLED}),
        }
    )
)


@dataclass(frozen=True, slots=True)
class BuilderTurnTransitionRule:
    legal_next_states: frozenset[BuilderTurnState]
    terminal_state_after_lock_clear: BuilderTurnState


AI_BUILDER_TURN_TRANSITIONS: Mapping[BuilderTurnState, BuilderTurnTransitionRule] = (
    MappingProxyType(
        {
            BuilderTurnState.OPEN: BuilderTurnTransitionRule(
                legal_next_states=frozenset(
                    {
                        BuilderTurnState.PROCESSING,
                        BuilderTurnState.COMMITTED,
                        BuilderTurnState.FAILED_BEFORE_PROVIDER,
                    }
                ),
                terminal_state_after_lock_clear=BuilderTurnState.FAILED_BEFORE_PROVIDER,
            ),
            BuilderTurnState.PROCESSING: BuilderTurnTransitionRule(
                legal_next_states=frozenset(
                    {
                        BuilderTurnState.PROCESSING,
                        BuilderTurnState.COMMITTED,
                        BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN,
                    }
                ),
                terminal_state_after_lock_clear=BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN,
            ),
            BuilderTurnState.COMMITTED: BuilderTurnTransitionRule(
                legal_next_states=frozenset(),
                terminal_state_after_lock_clear=BuilderTurnState.COMMITTED,
            ),
            BuilderTurnState.FAILED_BEFORE_PROVIDER: BuilderTurnTransitionRule(
                legal_next_states=frozenset({BuilderTurnState.OPEN}),
                terminal_state_after_lock_clear=BuilderTurnState.FAILED_BEFORE_PROVIDER,
            ),
            BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN: BuilderTurnTransitionRule(
                legal_next_states=frozenset({BuilderTurnState.OPEN}),
                terminal_state_after_lock_clear=BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN,
            ),
        }
    )
)


def terminal_builder_turn_state(
    stored_state: BuilderTurnState | None,
) -> BuilderTurnState | None:
    if stored_state is None:
        return None
    return AI_BUILDER_TURN_TRANSITIONS[stored_state].terminal_state_after_lock_clear


def effective_builder_turn_state(
    stored_state: BuilderTurnState | None,
    *,
    has_active_request: bool,
    lock_is_active: bool,
) -> BuilderTurnState | None:
    if not has_active_request or lock_is_active:
        return stored_state
    return terminal_builder_turn_state(stored_state)


def builder_turn_transition_predecessors(
    next_state: BuilderTurnState,
) -> tuple[BuilderTurnState, ...]:
    return tuple(
        state
        for state, rule in AI_BUILDER_TURN_TRANSITIONS.items()
        if next_state in rule.legal_next_states
    )


def builder_turn_terminal_state_pairs() -> tuple[
    tuple[BuilderTurnState, BuilderTurnState], ...
]:
    return tuple(
        (state, rule.terminal_state_after_lock_clear)
        for state, rule in AI_BUILDER_TURN_TRANSITIONS.items()
    )


def ensure_valid_session_status_transition(
    *,
    current: SessionStatus,
    next_status: SessionStatus,
) -> None:
    if next_status in AI_BUILDER_SESSION_TRANSITIONS[current]:
        return
    raise AIBuilderBadRequestException(
        f"Invalid AI Builder session transition: {current.value} -> {next_status.value}.",
        code=AIBuilderErrorCode.INVALID_SESSION_TRANSITION,
    )
