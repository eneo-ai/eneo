from __future__ import annotations

import asyncio
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from intric.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_send_lease import (
    claim_ai_builder_send_turn,
)
from intric.flows.ai_builder.ai_builder_session_turn import SessionSendLease


class _FakeSendLeaseRepo:
    def __init__(self, *, claim_result: bool = True) -> None:
        self.claim_result = claim_result
        self.events: list[str] = []
        self.refresh_started = asyncio.Event()
        self.finish_refresh = asyncio.Event()
        self.claimed_lease: SessionSendLease | None = None
        self.released_lease: SessionSendLease | None = None
        self.refresh_result = False

    async def claim_session_send(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        lease: SessionSendLease,
        lock_expires_at: datetime,
    ) -> bool:
        self.events.append("claim")
        self.claimed_lease = lease
        assert session_id
        assert tenant_id
        assert lock_expires_at
        return self.claim_result

    async def refresh_session_send_lease(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        lease: SessionSendLease,
        lock_expires_at: datetime,
    ) -> bool:
        self.events.append("refresh-start")
        self.refresh_started.set()
        await self.finish_refresh.wait()
        self.events.append("refresh-end")
        assert session_id
        assert tenant_id
        assert lease == self.claimed_lease
        assert lock_expires_at
        return self.refresh_result

    async def release_session_send(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        lease: SessionSendLease,
    ) -> None:
        self.events.append("release")
        self.released_lease = lease
        assert session_id
        assert tenant_id


def _force_fast_send_lock_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "intric.flows.ai_builder.ai_builder_send_lease."
        "_send_lock_refresh_interval_seconds",
        lambda: 0,
    )


@pytest.mark.asyncio
async def test_claim_ai_builder_send_turn_raises_without_release_when_claim_fails() -> (
    None
):
    fake_repo = _FakeSendLeaseRepo(claim_result=False)

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        async with claim_ai_builder_send_turn(
            repo=cast(AIBuilderRepository, fake_repo),
            session_id=uuid4(),
            tenant_id=uuid4(),
            base_planning_state_version=7,
        ):
            pass

    assert exc_info.value.code is AIBuilderErrorCode.SESSION_MESSAGE_IN_PROGRESS
    assert fake_repo.events == ["claim"]
    assert fake_repo.released_lease is None


@pytest.mark.asyncio
async def test_claim_ai_builder_send_turn_waits_for_refresh_before_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _FakeSendLeaseRepo()
    _force_fast_send_lock_refresh(monkeypatch)

    async with claim_ai_builder_send_turn(
        repo=cast(AIBuilderRepository, fake_repo),
        session_id=uuid4(),
        tenant_id=uuid4(),
        base_planning_state_version=11,
    ) as claimed:
        assert claimed.turn.base_planning_state_version == 11
        assert claimed.lease_lost_event.is_set() is False
        await asyncio.wait_for(fake_repo.refresh_started.wait(), timeout=1)
        fake_repo.finish_refresh.set()

    assert fake_repo.events == ["claim", "refresh-start", "refresh-end", "release"]
    assert fake_repo.released_lease == fake_repo.claimed_lease
