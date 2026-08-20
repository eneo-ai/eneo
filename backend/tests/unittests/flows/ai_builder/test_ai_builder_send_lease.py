from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.flows.ai_builder import ai_builder_send_lease
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
        self.fail_request_refresh = False

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
        if self.fail_request_refresh:
            raise AssertionError(
                "The request repository must not refresh the heartbeat."
            )
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


class _FakeHeartbeatRepo:
    def __init__(self, request_repo: _FakeSendLeaseRepo) -> None:
        self.request_repo = request_repo

    async def refresh_session_send_lease(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        lease: SessionSendLease,
        lock_lease_seconds: int,
    ) -> bool:
        request_repo = self.request_repo
        request_repo.events.append("refresh-start")
        request_repo.refresh_started.set()
        await request_repo.finish_refresh.wait()
        request_repo.events.append("refresh-end")
        assert session_id
        assert tenant_id
        assert lease == request_repo.claimed_lease
        assert lock_lease_seconds >= 30
        return request_repo.refresh_result


def _force_fast_send_lock_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_send_lease."
        "_send_lock_refresh_interval_seconds",
        lambda: 0,
    )


@pytest.mark.asyncio
async def test_unknown_outcome_wrap_logs_the_causing_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The wrap hides the cause from the client; the log is the only trace.

    Before this, sessions accumulated in provider_outcome_unknown with no
    record anywhere of what actually broke (81 in one dev space).
    """

    from eneo.flows.ai_builder.ai_builder_domain_models import BuilderTurnState
    from eneo.flows.ai_builder.ai_builder_error_contract import (
        AIBuilderProviderOutcomeUnknownException,
    )

    request_repo = _FakeSendLeaseRepo()
    request_repo.refresh_result = True
    request_repo.finish_refresh.set()
    _force_fast_send_lock_refresh(monkeypatch)

    async def release_unknown(**kwargs: object) -> BuilderTurnState:
        request_repo.events.append("release")
        return BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN

    monkeypatch.setattr(request_repo, "release_session_send", release_unknown)

    @contextlib.asynccontextmanager
    async def heartbeat_session_scope() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, object())

    monkeypatch.setattr(
        ai_builder_send_lease.sessionmanager,
        "session",
        heartbeat_session_scope,
    )
    monkeypatch.setattr(
        ai_builder_send_lease,
        "AIBuilderRepository",
        lambda session: _FakeHeartbeatRepo(request_repo),
    )

    # SimpleLogger instances are not registered with the logging manager, so
    # caplog cannot attach by name; route the module logger through a
    # standard one for the assertion.
    import logging as std_logging

    monkeypatch.setattr(
        ai_builder_send_lease,
        "logger",
        std_logging.getLogger("test.ai_builder_send_lease"),
    )

    cause = RuntimeError("attachment blob missing")
    with caplog.at_level("ERROR", logger="test.ai_builder_send_lease"):
        with pytest.raises(AIBuilderProviderOutcomeUnknownException) as exc_info:
            async with claim_ai_builder_send_turn(
                repo=cast(AIBuilderRepository, request_repo),
                session_id=uuid4(),
                tenant_id=uuid4(),
                accepted_turn=_accepted_turn(uuid4()),
                preparation_baseline=_preparation_baseline(),
            ):
                request_repo.finish_refresh.set()
                raise cause

    assert exc_info.value.__cause__ is cause
    wrap_records = [
        record
        for record in caplog.records
        if "provider-outcome-unknown" in record.getMessage()
    ]
    assert len(wrap_records) == 1
    assert wrap_records[0].exc_info is not None
    assert wrap_records[0].exc_info[1] is cause


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
async def test_claim_ai_builder_send_turn_refreshes_with_independent_session_before_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_repo = _FakeSendLeaseRepo()
    request_repo.fail_request_refresh = True
    heartbeat_repo = _FakeHeartbeatRepo(request_repo)
    heartbeat_session = cast(AsyncSession, object())
    _force_fast_send_lock_refresh(monkeypatch)

    @contextlib.asynccontextmanager
    async def heartbeat_session_scope() -> AsyncGenerator[AsyncSession, None]:
        request_repo.events.append("heartbeat-session-open")
        try:
            yield heartbeat_session
        finally:
            request_repo.events.append("heartbeat-session-close")

    monkeypatch.setattr(
        ai_builder_send_lease.sessionmanager,
        "session",
        heartbeat_session_scope,
    )
    monkeypatch.setattr(
        ai_builder_send_lease,
        "AIBuilderRepository",
        lambda session: heartbeat_repo if session is heartbeat_session else None,
    )

    async with claim_ai_builder_send_turn(
        repo=cast(AIBuilderRepository, request_repo),
        session_id=uuid4(),
        tenant_id=uuid4(),
        accepted_turn=_accepted_turn(uuid4()),
        preparation_baseline=_preparation_baseline(),
    ) as claimed:
        assert claimed.turn.base_planning_state_version == 11
        assert claimed.lease_lost_event.is_set() is False
        await asyncio.wait_for(request_repo.refresh_started.wait(), timeout=1)
        request_repo.finish_refresh.set()

    assert request_repo.events == [
        "claim",
        "heartbeat-session-open",
        "refresh-start",
        "refresh-end",
        "heartbeat-session-close",
        "release",
    ]
    assert request_repo.released_lease == request_repo.claimed_lease


@pytest.mark.parametrize(
    ("configured_seconds", "expected_lease", "expected_refresh"),
    [(1, 30, 10), (15, 30, 10), (31, 31, 10), (90, 90, 30)],
)
def test_send_lock_timing_applies_the_minimum_and_one_third_refresh(
    monkeypatch: pytest.MonkeyPatch,
    configured_seconds: int,
    expected_lease: int,
    expected_refresh: int,
) -> None:
    monkeypatch.setattr(
        ai_builder_send_lease,
        "get_settings",
        lambda: SimpleNamespace(ai_builder_send_lock_lease_seconds=configured_seconds),
    )

    assert ai_builder_send_lease._send_lock_lease_seconds() == expected_lease
    assert (
        ai_builder_send_lease._send_lock_refresh_interval_seconds() == expected_refresh
    )


async def test_lease_maintenance_stops_without_refresh_when_already_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop_event = asyncio.Event()
    stop_event.set()
    lease_lost_event = asyncio.Event()

    async def unexpected_refresh(**kwargs: object) -> bool:
        raise AssertionError(f"unexpected refresh: {kwargs}")

    monkeypatch.setattr(
        ai_builder_send_lease,
        "_refresh_session_send_lease",
        unexpected_refresh,
    )

    await ai_builder_send_lease._maintain_send_lock_lease(
        session_id=uuid4(),
        tenant_id=uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        stop_event=stop_event,
        lease_lost_event=lease_lost_event,
    )

    assert lease_lost_event.is_set() is False


@pytest.mark.parametrize("refresh_outcome", [False, RuntimeError("redis unavailable")])
async def test_lease_maintenance_marks_loss_after_failed_refresh(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    refresh_outcome: bool | Exception,
) -> None:
    session_id = uuid4()
    tenant_id = uuid4()
    lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())
    stop_event = asyncio.Event()
    lease_lost_event = asyncio.Event()
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        ai_builder_send_lease,
        "_send_lock_refresh_interval_seconds",
        lambda: 0,
    )
    monkeypatch.setattr(
        ai_builder_send_lease,
        "_send_lock_lease_seconds",
        lambda: 73,
    )

    async def refresh(**kwargs: object) -> bool:
        calls.append(kwargs)
        if isinstance(refresh_outcome, Exception):
            raise refresh_outcome
        return refresh_outcome

    monkeypatch.setattr(
        ai_builder_send_lease,
        "_refresh_session_send_lease",
        refresh,
    )

    import logging as std_logging

    log_name = "test.ai_builder_send_lease.maintenance"
    monkeypatch.setattr(
        ai_builder_send_lease,
        "logger",
        std_logging.getLogger(log_name),
    )

    with caplog.at_level("WARNING", logger=log_name):
        await ai_builder_send_lease._maintain_send_lock_lease(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=lease,
            stop_event=stop_event,
            lease_lost_event=lease_lost_event,
        )

    assert calls == [
        {
            "session_id": session_id,
            "tenant_id": tenant_id,
            "lease": lease,
            "lock_lease_seconds": 73,
        }
    ]
    assert lease_lost_event.is_set() is True
    if isinstance(refresh_outcome, Exception):
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.getMessage() == "AI Builder send lease refresh failed."
        assert record.exc_info is not None
        assert record.exc_info[1] is refresh_outcome
        assert record.session_id == str(session_id)
        assert record.request_id == str(lease.request_id)


async def test_lease_maintenance_continues_after_refresh_until_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop_event = asyncio.Event()
    lease_lost_event = asyncio.Event()
    refresh_count = 0

    monkeypatch.setattr(
        ai_builder_send_lease,
        "_send_lock_refresh_interval_seconds",
        lambda: 0,
    )

    async def refresh(**kwargs: object) -> bool:
        nonlocal refresh_count
        assert kwargs["lock_lease_seconds"] >= 30
        refresh_count += 1
        stop_event.set()
        return True

    monkeypatch.setattr(
        ai_builder_send_lease,
        "_refresh_session_send_lease",
        refresh,
    )

    await ai_builder_send_lease._maintain_send_lock_lease(
        session_id=uuid4(),
        tenant_id=uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        stop_event=stop_event,
        lease_lost_event=lease_lost_event,
    )

    assert refresh_count == 1
    assert lease_lost_event.is_set() is False


async def test_refresh_lease_opens_a_session_and_forwards_the_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid4()
    tenant_id = uuid4()
    lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())
    database_session = cast(AsyncSession, object())
    calls: list[dict[str, object]] = []

    @contextlib.asynccontextmanager
    async def session_scope() -> AsyncGenerator[AsyncSession, None]:
        yield database_session

    class RecordingRepo:
        def __init__(self, session: AsyncSession) -> None:
            assert session is database_session

        async def refresh_session_send_lease(self, **kwargs: object) -> bool:
            calls.append(kwargs)
            return True

    monkeypatch.setattr(ai_builder_send_lease.sessionmanager, "session", session_scope)
    monkeypatch.setattr(ai_builder_send_lease, "AIBuilderRepository", RecordingRepo)

    assert (
        await ai_builder_send_lease._refresh_session_send_lease(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=lease,
            lock_lease_seconds=47,
        )
        is True
    )
    assert calls == [
        {
            "session_id": session_id,
            "tenant_id": tenant_id,
            "lease": lease,
            "lock_lease_seconds": 47,
        }
    ]


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
