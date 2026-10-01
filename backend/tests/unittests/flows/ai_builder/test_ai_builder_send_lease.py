from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from time import monotonic
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.flows.ai_builder import ai_builder_send_lease
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderTurnState,
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
        # The request session is gone once the response scope is cancelled, so
        # nothing may release through it. The checkpoint stands for the round
        # trip a real release makes: a cancelled scope re-raises there.
        await asyncio.sleep(0)
        self.events.append("request-release")
        self.released_lease = lease
        assert session_id
        assert tenant_id


class _FakeHeartbeatRepo:
    def __init__(self, request_repo: _FakeSendLeaseRepo) -> None:
        self.request_repo = request_repo
        self.released_lease: SessionSendLease | None = None
        self.released_state: BuilderTurnState | None = None
        self.release_never_returns = False

    async def owns_session_send_lease(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        lease: SessionSendLease,
    ) -> bool:
        return True

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

    async def release_session_send(
        self,
        *,
        session_id: UUID,
        tenant_id: UUID,
        lease: SessionSendLease,
    ) -> BuilderTurnState | None:
        await asyncio.sleep(0)
        if self.release_never_returns:
            await asyncio.Event().wait()
        self.request_repo.events.append("release")
        self.released_lease = lease
        assert session_id
        assert tenant_id
        return self.released_state


def _install_independent_session(
    monkeypatch: pytest.MonkeyPatch,
    request_repo: _FakeSendLeaseRepo,
    heartbeat_repo: _FakeHeartbeatRepo,
) -> None:
    """Patch the heartbeat/release session scope the lease opens for itself."""

    independent_session = cast(AsyncSession, object())

    @contextlib.asynccontextmanager
    async def session_scope() -> AsyncGenerator[AsyncSession, None]:
        request_repo.events.append("heartbeat-session-open")
        try:
            yield independent_session
        finally:
            request_repo.events.append("heartbeat-session-close")

    monkeypatch.setattr(
        ai_builder_send_lease.sessionmanager,
        "session",
        session_scope,
    )
    monkeypatch.setattr(
        ai_builder_send_lease,
        "AIBuilderRepository",
        lambda session: heartbeat_repo if session is independent_session else None,
    )


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

    from eneo.flows.ai_builder.ai_builder_error_contract import (
        AIBuilderProviderOutcomeUnknownException,
    )

    request_repo = _FakeSendLeaseRepo()
    request_repo.refresh_result = True
    request_repo.finish_refresh.set()
    _force_fast_send_lock_refresh(monkeypatch)
    heartbeat_repo = _FakeHeartbeatRepo(request_repo)
    heartbeat_repo.released_state = BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN
    _install_independent_session(monkeypatch, request_repo, heartbeat_repo)

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
    _force_fast_send_lock_refresh(monkeypatch)
    _install_independent_session(monkeypatch, request_repo, heartbeat_repo)

    async with claim_ai_builder_send_turn(
        repo=cast(AIBuilderRepository, request_repo),
        session_id=uuid4(),
        tenant_id=uuid4(),
        accepted_turn=_accepted_turn(uuid4()),
        preparation_baseline=_preparation_baseline(),
    ) as claimed:
        assert claimed.turn.base_planning_state_version == 11
        assert claimed.provider_gate.lease_lost.is_set() is False
        assert claimed.provider_gate.ownership_lost.is_set() is False
        await asyncio.wait_for(request_repo.refresh_started.wait(), timeout=1)
        request_repo.finish_refresh.set()

    assert request_repo.events == [
        "claim",
        "heartbeat-session-open",
        "refresh-start",
        "refresh-end",
        "heartbeat-session-close",
        "heartbeat-session-open",
        "release",
        "heartbeat-session-close",
    ]
    assert heartbeat_repo.released_lease == request_repo.claimed_lease
    assert request_repo.released_lease is None


@pytest.mark.asyncio
async def test_client_disconnect_releases_the_send_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reload mid-stream must not strand the session for the whole lease.

    Starlette cancels the response's scope when the client disconnects, and a
    cancelled scope re-raises at every await inside it, including the ones
    that clear the lock. The row then kept `processing` with a 15-minute lock
    and the user was told to wait for it.
    """

    request_repo = _FakeSendLeaseRepo()
    request_repo.fail_request_refresh = True
    request_repo.finish_refresh.set()
    heartbeat_repo = _FakeHeartbeatRepo(request_repo)
    _install_independent_session(monkeypatch, request_repo, heartbeat_repo)

    with anyio.CancelScope() as response_scope:
        async with claim_ai_builder_send_turn(
            repo=cast(AIBuilderRepository, request_repo),
            session_id=uuid4(),
            tenant_id=uuid4(),
            accepted_turn=_accepted_turn(uuid4()),
            preparation_baseline=_preparation_baseline(),
        ):
            response_scope.cancel()
            await anyio.sleep(0)

    assert response_scope.cancelled_caught
    assert heartbeat_repo.released_lease == request_repo.claimed_lease
    # The request's own connection goes down with the response scope, so the
    # release must not be attempted on it.
    assert request_repo.released_lease is None


@pytest.mark.asyncio
async def test_a_release_that_never_returns_is_bounded_and_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stuck cleanup must not hold the request task for the lease's length.

    The lock is then left to its lease, which the next claim already projects
    to the same terminal state; the log is the only trace that it happened.
    """

    request_repo = _FakeSendLeaseRepo()
    request_repo.fail_request_refresh = True
    request_repo.finish_refresh.set()
    heartbeat_repo = _FakeHeartbeatRepo(request_repo)
    heartbeat_repo.release_never_returns = True
    _install_independent_session(monkeypatch, request_repo, heartbeat_repo)
    monkeypatch.setattr(
        ai_builder_send_lease,
        "_SEND_LOCK_RELEASE_TIMEOUT_SECONDS",
        0.05,
    )

    import logging as std_logging

    log_name = "test.ai_builder_send_lease.release_timeout"
    monkeypatch.setattr(
        ai_builder_send_lease,
        "logger",
        std_logging.getLogger(log_name),
    )

    started = monotonic()
    with caplog.at_level("ERROR", logger=log_name):
        async with claim_ai_builder_send_turn(
            repo=cast(AIBuilderRepository, request_repo),
            session_id=uuid4(),
            tenant_id=uuid4(),
            accepted_turn=_accepted_turn(uuid4()),
            preparation_baseline=_preparation_baseline(),
        ) as claimed:
            session_id = claimed.turn.session_id

    assert monotonic() - started < 5
    timeout_records = [
        record
        for record in caplog.records
        if "release timed out" in record.getMessage()
    ]
    assert len(timeout_records) == 1
    assert timeout_records[0].session_id == str(session_id)
    assert timeout_records[0].request_id == str(request_repo.claimed_lease.request_id)
    assert heartbeat_repo.released_lease is None


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
        ownership_lost_event=asyncio.Event(),
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
    ownership_lost_event = asyncio.Event()
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
            ownership_lost_event=ownership_lost_event,
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
    # A refresh that finds the row is no longer this turn's confirms the loss
    # and stops the work in flight; a refresh that failed proves nothing, so it
    # only fences later commits (the heartbeat stops renewing either way).
    assert ownership_lost_event.is_set() is (refresh_outcome is False)
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
        ownership_lost_event=asyncio.Event(),
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


# The ownership probe: a read-only check, on its own short interval, that the
# row is still this turn's. Only a probe that answers "not ours" stops the work
# in flight; a probe that fails or hangs is logged and tried again.


async def _watch(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: list[object],
    *,
    lease: SessionSendLease,
    on_probe: list[tuple[bool, bool]],
    ownership_lost_event: asyncio.Event,
    lease_lost_event: asyncio.Event,
) -> None:
    monkeypatch.setattr(
        ai_builder_send_lease, "_SEND_OWNERSHIP_PROBE_INTERVAL_SECONDS", 0
    )
    monkeypatch.setattr(
        ai_builder_send_lease, "_SEND_OWNERSHIP_PROBE_TIMEOUT_SECONDS", 0.01
    )

    async def probe(**kwargs: object) -> bool:
        assert kwargs["lease"] == lease
        on_probe.append((ownership_lost_event.is_set(), lease_lost_event.is_set()))
        outcome = outcomes.pop(0)
        if outcome == "hang":
            await asyncio.Event().wait()
        if isinstance(outcome, Exception):
            raise outcome
        return cast(bool, outcome)

    monkeypatch.setattr(ai_builder_send_lease, "_probe_session_send_ownership", probe)
    await asyncio.wait_for(
        ai_builder_send_lease._watch_send_ownership(
            session_id=uuid4(),
            tenant_id=uuid4(),
            lease=lease,
            stop_event=asyncio.Event(),
            lease_lost_event=lease_lost_event,
            ownership_lost_event=ownership_lost_event,
        ),
        timeout=5,
    )


@pytest.mark.asyncio
async def test_a_probe_that_finds_the_row_taken_stops_the_turns_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())
    ownership_lost_event, lease_lost_event = asyncio.Event(), asyncio.Event()
    on_probe: list[tuple[bool, bool]] = []

    await _watch(
        monkeypatch,
        [True, False],
        lease=lease,
        on_probe=on_probe,
        ownership_lost_event=ownership_lost_event,
        lease_lost_event=lease_lost_event,
    )

    assert on_probe == [(False, False), (False, False)]
    assert ownership_lost_event.is_set()
    assert lease_lost_event.is_set()


@pytest.mark.asyncio
async def test_a_probe_that_fails_or_hangs_is_retried_without_stopping_healthy_work(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging as std_logging

    log_name = "test.ai_builder_send_lease.probe"
    monkeypatch.setattr(
        ai_builder_send_lease, "logger", std_logging.getLogger(log_name)
    )
    lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())
    ownership_lost_event, lease_lost_event = asyncio.Event(), asyncio.Event()
    on_probe: list[tuple[bool, bool]] = []

    with caplog.at_level("WARNING", logger=log_name):
        await _watch(
            monkeypatch,
            [RuntimeError("pool exhausted"), "hang", True, False],
            lease=lease,
            on_probe=on_probe,
            ownership_lost_event=ownership_lost_event,
            lease_lost_event=lease_lost_event,
        )

    # Neither the failure nor the hang stopped anything; the probe after them
    # still found the loss.
    assert on_probe == [(False, False)] * 4
    assert ownership_lost_event.is_set()
    # The turn's first failure is logged in full; the second falls inside the
    # summary interval.
    probe_records = [
        record for record in caplog.records if "probe" in record.getMessage()
    ]
    assert len(probe_records) == 1
    assert probe_records[0].exc_info is not None


@pytest.mark.asyncio
async def test_repeated_probe_failures_are_summarised_not_logged_in_full(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging as std_logging

    log_name = "test.ai_builder_send_lease.probe_summary"
    monkeypatch.setattr(
        ai_builder_send_lease, "logger", std_logging.getLogger(log_name)
    )
    monkeypatch.setattr(
        ai_builder_send_lease, "_SEND_OWNERSHIP_PROBE_FAILURE_SUMMARY_SECONDS", 0
    )
    lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())

    with caplog.at_level("WARNING", logger=log_name):
        await _watch(
            monkeypatch,
            [RuntimeError("one"), RuntimeError("two"), TimeoutError(), False],
            lease=lease,
            on_probe=[],
            ownership_lost_event=asyncio.Event(),
            lease_lost_event=asyncio.Event(),
        )

    probe_records = [
        record for record in caplog.records if "probe" in record.getMessage()
    ]
    assert [record.exc_info is not None for record in probe_records] == [
        True,
        False,
        False,
    ]
    assert [
        (
            getattr(record, "probe_failures"),
            getattr(record, "probe_failures_since_last_log"),
            getattr(record, "last_probe_error"),
        )
        for record in probe_records[1:]
    ] == [(2, 1, "RuntimeError"), (3, 1, "TimeoutError")]


@pytest.mark.asyncio
async def test_a_refresh_that_never_returns_does_not_keep_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The heartbeat is drained within its own bound, then the row is released.

    A refresh stuck on the database must not spend the release's budget: the
    lock would then stay for the whole lease although the turn had ended.
    """

    request_repo = _FakeSendLeaseRepo()
    request_repo.fail_request_refresh = True
    heartbeat_repo = _FakeHeartbeatRepo(request_repo)
    _force_fast_send_lock_refresh(monkeypatch)
    _install_independent_session(monkeypatch, request_repo, heartbeat_repo)
    monkeypatch.setattr(
        ai_builder_send_lease,
        "_SEND_HEARTBEAT_DRAIN_TIMEOUT_SECONDS",
        0.01,
        raising=False,
    )
    monkeypatch.setattr(
        ai_builder_send_lease, "_SEND_LOCK_RELEASE_TIMEOUT_SECONDS", 0.5
    )

    started = monotonic()
    async with claim_ai_builder_send_turn(
        repo=cast(AIBuilderRepository, request_repo),
        session_id=uuid4(),
        tenant_id=uuid4(),
        accepted_turn=_accepted_turn(uuid4()),
        preparation_baseline=_preparation_baseline(),
    ):
        await asyncio.wait_for(request_repo.refresh_started.wait(), timeout=1)

    assert monotonic() - started < 0.5
    assert heartbeat_repo.released_lease == request_repo.claimed_lease
    assert "refresh-end" not in request_repo.events


@pytest.mark.asyncio
async def test_a_blocked_refresh_and_a_blocked_release_leave_the_lock_to_its_lease(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both bounds hold together; nothing of the lease keeps running after."""

    import logging as std_logging

    log_name = "test.ai_builder_send_lease.blocked"
    monkeypatch.setattr(
        ai_builder_send_lease, "logger", std_logging.getLogger(log_name)
    )
    request_repo = _FakeSendLeaseRepo()
    request_repo.fail_request_refresh = True
    heartbeat_repo = _FakeHeartbeatRepo(request_repo)
    heartbeat_repo.release_never_returns = True
    _force_fast_send_lock_refresh(monkeypatch)
    _install_independent_session(monkeypatch, request_repo, heartbeat_repo)
    monkeypatch.setattr(
        ai_builder_send_lease,
        "_SEND_HEARTBEAT_DRAIN_TIMEOUT_SECONDS",
        0.01,
        raising=False,
    )
    monkeypatch.setattr(
        ai_builder_send_lease, "_SEND_LOCK_RELEASE_TIMEOUT_SECONDS", 0.05
    )

    before = asyncio.all_tasks()
    started = monotonic()
    with caplog.at_level("ERROR", logger=log_name):
        async with claim_ai_builder_send_turn(
            repo=cast(AIBuilderRepository, request_repo),
            session_id=uuid4(),
            tenant_id=uuid4(),
            accepted_turn=_accepted_turn(uuid4()),
            preparation_baseline=_preparation_baseline(),
        ):
            await asyncio.wait_for(request_repo.refresh_started.wait(), timeout=1)

    assert monotonic() - started < 1
    assert heartbeat_repo.released_lease is None
    assert any("release timed out" in record.getMessage() for record in caplog.records)
    await asyncio.sleep(0)
    assert [task for task in asyncio.all_tasks() - before if not task.done()] == []


@pytest.mark.asyncio
async def test_a_heartbeat_that_ignores_cancellation_is_named_and_kept_while_the_row_is_released(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The drain is one bound, cancellation included; nothing is left unreferenced."""

    import logging as std_logging

    log_name = "test.ai_builder_send_lease.stubborn"
    monkeypatch.setattr(
        ai_builder_send_lease, "logger", std_logging.getLogger(log_name)
    )
    request_repo = _FakeSendLeaseRepo()
    request_repo.fail_request_refresh = True
    heartbeat_repo = _FakeHeartbeatRepo(request_repo)
    _force_fast_send_lock_refresh(monkeypatch)
    _install_independent_session(monkeypatch, request_repo, heartbeat_repo)
    monkeypatch.setattr(
        ai_builder_send_lease, "_SEND_HEARTBEAT_DRAIN_TIMEOUT_SECONDS", 0.05
    )
    let_go = asyncio.Event()

    async def refresh_ignoring_cancellation(**_: object) -> bool:
        request_repo.refresh_started.set()
        while not let_go.is_set():
            try:
                await let_go.wait()
            except asyncio.CancelledError:
                continue
        return True

    monkeypatch.setattr(
        ai_builder_send_lease,
        "_refresh_session_send_lease",
        refresh_ignoring_cancellation,
    )

    started = monotonic()
    try:
        with caplog.at_level("ERROR", logger=log_name):
            async with claim_ai_builder_send_turn(
                repo=cast(AIBuilderRepository, request_repo),
                session_id=uuid4(),
                tenant_id=uuid4(),
                accepted_turn=_accepted_turn(uuid4()),
                preparation_baseline=_preparation_baseline(),
            ):
                await asyncio.wait_for(request_repo.refresh_started.wait(), timeout=1)
        elapsed = monotonic() - started
        kept = list(ai_builder_send_lease._UNFINISHED_HEARTBEAT_TASKS)
    finally:
        # The stubborn task must end whatever the assertions find, or the
        # test's event loop could never close.
        let_go.set()

    assert elapsed < 1
    assert heartbeat_repo.released_lease == request_repo.claimed_lease
    ignored = [
        record
        for record in caplog.records
        if "ignored its cancellation" in record.getMessage()
    ]
    assert len(ignored) == 1
    task_name = getattr(ignored[0], "task_name")
    assert task_name.startswith("ai-builder-send-lease-refresh-")
    assert [task.get_name() for task in kept] == [task_name]
    await asyncio.wait(kept, timeout=1)
    assert ai_builder_send_lease._UNFINISHED_HEARTBEAT_TASKS == set()


@pytest.mark.asyncio
async def test_a_loss_behind_a_slow_stale_positive_probe_is_noticed_within_the_stated_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worst case the bound names: interval + two whole probe waits.

    The first probe reads the row just before the loss and answers "owned" at
    the end of its wait; the next probe, an interval later, answers "not
    owned" at the end of its own wait.
    """

    # The published bound is derived from the probe constants, not written.
    assert ai_builder_send_lease.SEND_OWNERSHIP_LOSS_DETECTION_SECONDS == (
        ai_builder_send_lease._SEND_OWNERSHIP_PROBE_INTERVAL_SECONDS
        + 2 * ai_builder_send_lease._SEND_OWNERSHIP_PROBE_TIMEOUT_SECONDS
    )
    interval, wait = 0.1, 0.2
    monkeypatch.setattr(
        ai_builder_send_lease, "_SEND_OWNERSHIP_PROBE_INTERVAL_SECONDS", interval
    )
    monkeypatch.setattr(
        ai_builder_send_lease, "_SEND_OWNERSHIP_PROBE_TIMEOUT_SECONDS", wait
    )
    bound = interval + 2 * wait
    loop = asyncio.get_running_loop()
    lost_at: list[float] = []
    answers = [True, False]

    async def slow_probe(**_: object) -> bool:
        if not lost_at:
            lost_at.append(loop.time())
        await asyncio.sleep(wait * 0.9)
        return answers.pop(0)

    monkeypatch.setattr(
        ai_builder_send_lease, "_probe_session_send_ownership", slow_probe
    )
    ownership_lost_event = asyncio.Event()

    await asyncio.wait_for(
        ai_builder_send_lease._watch_send_ownership(
            session_id=uuid4(),
            tenant_id=uuid4(),
            lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
            stop_event=asyncio.Event(),
            lease_lost_event=asyncio.Event(),
            ownership_lost_event=ownership_lost_event,
        ),
        timeout=5,
    )
    noticed_after = loop.time() - lost_at[0]

    assert ownership_lost_event.is_set()
    # Longer than one interval plus one wait, the bound the first version
    # stated; within the bound the module names (with scheduling slack).
    assert noticed_after > interval + wait
    assert noticed_after <= bound + 0.15
