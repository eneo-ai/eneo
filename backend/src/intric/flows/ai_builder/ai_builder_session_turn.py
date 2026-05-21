"""Active send-turn write authority for AI Builder sessions."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


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
