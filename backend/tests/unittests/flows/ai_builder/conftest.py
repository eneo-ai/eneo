from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.flows.ai_builder import ai_builder_send_lease
from eneo.flows.ai_builder.ai_builder_domain_models import BuilderTurnState
from eneo.flows.ai_builder.ai_builder_session_turn import SessionSendLease


@dataclass
class SendLockReleaseSpy:
    """Records the releases the send lease performs on its own session.

    The lease heartbeats and releases through a session of its own so a
    cancelled response scope cannot take the release down with it, which means
    the request repository double never sees them.
    """

    released_leases: list[SessionSendLease] = field(default_factory=list)
    released_state: BuilderTurnState | None = None

    async def refresh_session_send_lease(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        lease: SessionSendLease,
        lock_lease_seconds: int,
    ) -> bool:
        return True

    async def release_session_send(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        lease: SessionSendLease,
    ) -> BuilderTurnState | None:
        # A real release suspends on its round trip, which is where a
        # cancelled response scope would re-raise.
        await asyncio.sleep(0)
        self.released_leases.append(lease)
        return self.released_state

    def assert_released_once(self) -> None:
        assert len(self.released_leases) == 1, self.released_leases

    def assert_not_released(self) -> None:
        assert self.released_leases == []


@pytest.fixture(autouse=True)
def send_lock_release(monkeypatch: pytest.MonkeyPatch) -> SendLockReleaseSpy:
    spy = SendLockReleaseSpy()
    spy_session = cast(AsyncSession, object())

    @contextlib.asynccontextmanager
    async def session_scope() -> AsyncGenerator[AsyncSession, None]:
        yield spy_session

    monkeypatch.setattr(
        ai_builder_send_lease.sessionmanager,
        "session",
        session_scope,
    )
    monkeypatch.setattr(
        ai_builder_send_lease,
        "AIBuilderRepository",
        lambda session: spy if session is spy_session else None,
    )
    return spy
