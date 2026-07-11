"""Active send-turn write authority for AI Builder sessions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderSession,
    BuilderTurnState,
    ConversationMessage,
    SessionStatus,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject


@dataclass(frozen=True, slots=True)
class SessionSendLease:
    request_id: UUID
    lock_token: UUID


@dataclass(frozen=True, slots=True)
class SessionSendTurn:
    session_id: UUID
    tenant_id: UUID
    lease: SessionSendLease
    base_planning_state_version: int


@dataclass(frozen=True, slots=True)
class SessionTurnAcceptance:
    client_turn_id: UUID
    request_fingerprint: str
    request: FlowPersistedJsonObject
    user_message: ConversationMessage
    file_ids: tuple[UUID, ...]
    acknowledge_duplicate_provider_spend: bool = False


@dataclass(frozen=True, slots=True)
class SessionTurnPreparationBaseline:
    session_status: SessionStatus
    latest_plan_id: UUID | None
    planning_state_version: int
    latest_turn_id: UUID | None
    latest_turn_state: BuilderTurnState | None
    attachment_file_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class SessionTurnPreflight:
    session: BuilderSession
    baseline: SessionTurnPreparationBaseline
    replayed: bool = False


class SessionTurnClaimDisposition(StrEnum):
    EXECUTE = "execute"
    REPLAY_COMMITTED = "replay_committed"
    PROVIDER_OUTCOME_UNKNOWN = "provider_outcome_unknown"


@dataclass(frozen=True, slots=True)
class SessionTurnClaim:
    disposition: SessionTurnClaimDisposition
    user_message: ConversationMessage
    base_planning_state_version: int
