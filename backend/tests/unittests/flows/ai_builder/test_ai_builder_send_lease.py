from __future__ import annotations

import asyncio
from typing import cast
from uuid import UUID, uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    SessionStatus,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_send_lease import (
    claim_ai_builder_send_turn,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionTurnAcceptance,
    SessionTurnClaim,
    SessionTurnClaimDisposition,
    SessionTurnPreparationBaseline,
)


class _FakeSendLeaseRepo:
    def __init__(
        self, *, claim_error: AIBuilderBadRequestException | None = None
    ) -> None:
        self.claim_error = claim_error
        self.events: list[str] = []
        self.refresh_started = asyncio.Event()
        self.finish_refresh = asyncio.Event()
        self.claimed_lease: SessionSendLease | None = None
        self.released_lease: SessionSendLease | None = None
        self.refresh_result = False

    async def accept_session_turn(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        lease: SessionSendLease,
        lock_lease_seconds: int,
        acceptance: SessionTurnAcceptance,
        preparation_baseline: SessionTurnPreparationBaseline,
    ) -> SessionTurnClaim:
        self.events.append("claim")
        self.claimed_lease = lease
        assert session_id
        assert tenant_id
        assert lock_lease_seconds >= 30
        assert preparation_baseline.session_status is SessionStatus.CHATTING
        if self.claim_error is not None:
            raise self.claim_error
        return SessionTurnClaim(
            disposition=SessionTurnClaimDisposition.EXECUTE,
            user_message=acceptance.user_message,
            base_planning_state_version=11,
        )

    async def refresh_session_send_lease(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        lease: SessionSendLease,
        lock_lease_seconds: int,
    ) -> bool:
        self.events.append("refresh-start")
        self.refresh_started.set()
        await self.finish_refresh.wait()
        self.events.append("refresh-end")
        assert session_id
        assert tenant_id
        assert lease == self.claimed_lease
        assert lock_lease_seconds >= 30
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
        "eneo.flows.ai_builder.ai_builder_send_lease."
        "_send_lock_refresh_interval_seconds",
        lambda: 0,
    )


@pytest.mark.asyncio
async def test_claim_ai_builder_send_turn_raises_without_release_when_claim_fails() -> (
    None
):
    fake_repo = _FakeSendLeaseRepo(
        claim_error=AIBuilderBadRequestException(
            "already processing",
            code=AIBuilderErrorCode.SESSION_MESSAGE_IN_PROGRESS,
        )
    )
    client_turn_id = uuid4()

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        async with claim_ai_builder_send_turn(
            repo=cast(AIBuilderRepository, fake_repo),
            session_id=uuid4(),
            tenant_id=uuid4(),
            accepted_turn=_accepted_turn(client_turn_id),
            preparation_baseline=_preparation_baseline(),
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
        accepted_turn=_accepted_turn(uuid4()),
        preparation_baseline=_preparation_baseline(),
    ) as claimed:
        assert claimed.turn.base_planning_state_version == 11
        assert claimed.lease_lost_event.is_set() is False
        await asyncio.wait_for(fake_repo.refresh_started.wait(), timeout=1)
        fake_repo.finish_refresh.set()

    assert fake_repo.events == ["claim", "refresh-start", "refresh-end", "release"]
    assert fake_repo.released_lease == fake_repo.claimed_lease


def _accepted_turn(client_turn_id: UUID) -> SessionTurnAcceptance:
    message = ConversationMessage(role="user", content="Build a flow")
    return SessionTurnAcceptance(
        client_turn_id=client_turn_id,
        request_fingerprint="a" * 64,
        request={
            "client_turn_id": str(client_turn_id),
            "message": message.content,
        },
        user_message=message,
        file_ids=(),
    )


def _preparation_baseline() -> SessionTurnPreparationBaseline:
    return SessionTurnPreparationBaseline(
        session_status=SessionStatus.CHATTING,
        latest_plan_id=None,
        planning_state_version=11,
        latest_turn_id=None,
        latest_turn_state=None,
        attachment_file_ids=(),
    )
