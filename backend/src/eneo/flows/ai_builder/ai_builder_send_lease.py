from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

import anyio

from eneo.database.database import sessionmanager
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderTurnState,
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderProviderOutcomeUnknownException,
    AIBuilderPublicError,
)
from eneo.flows.ai_builder.ai_builder_provider_call import ProviderWorkGate
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
    SessionTurnAcceptance,
    SessionTurnClaimDisposition,
    SessionTurnPreparationBaseline,
)
from eneo.main.config import get_settings
from eneo.main.logging import get_logger

logger = get_logger(__name__)

# How long the cleanup may spend clearing one row before it gives up. It is
# this module's own safety bound, not operator policy: the send lease is how
# long a lost turn stays unrecoverable, and it must not also decide how long a
# stuck write may hold a request task and a pooled connection.
_SEND_LOCK_RELEASE_TIMEOUT_SECONDS = 30.0
# How quickly a cancel or a takeover reaches the turn's work in flight: the
# ownership probe reads the row every interval and waits at most its timeout
# for the answer. They are this module's mechanism bounds, like the release
# timeout above; the lock-extending refresh stays at a third of the lease. A
# probe that fails or times out proves nothing and is tried again at the next
# interval; after the turn's first failure, which is logged in full, failures
# are summarised at most once per summary interval.
_SEND_OWNERSHIP_PROBE_INTERVAL_SECONDS = 2.0
_SEND_OWNERSHIP_PROBE_TIMEOUT_SECONDS = 5.0
_SEND_OWNERSHIP_PROBE_FAILURE_SUMMARY_SECONDS = 60.0
# The longest a confirmed loss can go unnoticed while probes answer: a probe
# whose read predates the loss may take its whole timeout to answer "owned",
# one interval passes, and the next probe may take its whole timeout to answer
# "not owned". It assumes a timed-out probe's cancellation ends promptly (the
# wait includes its cleanup). The provider stream then closes within its own
# close bound. Probes that keep failing give no finite guarantee; only a
# refresh that finds the row gone (every third of the lease) confirms the loss
# then.
SEND_OWNERSHIP_LOSS_DETECTION_SECONDS = (
    _SEND_OWNERSHIP_PROBE_INTERVAL_SECONDS + 2 * _SEND_OWNERSHIP_PROBE_TIMEOUT_SECONDS
)
# The whole wait the turn's cleanup spends stopping the heartbeat before it
# releases the row: half for a beat in progress to finish, the rest for a
# cancelled one to end. A refresh stuck on the database must not spend the
# release's own budget, or the lock stays for the whole lease.
_SEND_HEARTBEAT_DRAIN_TIMEOUT_SECONDS = 5.0
# Heartbeat tasks that ignored their cancellation stay referenced here until
# they end, so none is garbage-collected while it still runs.
_UNFINISHED_HEARTBEAT_TASKS: set[asyncio.Task[None]] = set()


@asynccontextmanager
async def _lease_repository() -> AsyncGenerator[AIBuilderRepository]:
    """Open a repository on a session of the lease's own.

    The heartbeat and the release must not ride the request's connection: it
    is cancelled and torn down the moment the client disconnects.
    """

    async with sessionmanager.session() as session:
        yield AIBuilderRepository(session)


@dataclass(frozen=True, slots=True)
class ClaimedSessionSendTurn:
    """A claimed turn and the gate its provider work answers to."""

    turn: SessionSendTurn
    provider_gate: ProviderWorkGate
    user_message: ConversationMessage
    replayed: bool = False
    committed_error: AIBuilderPublicError | None = None


@asynccontextmanager
async def claim_ai_builder_send_turn(
    *,
    repo: "AIBuilderRepository",
    session_id: UUID,
    tenant_id: UUID,
    accepted_turn: SessionTurnAcceptance,
    preparation_baseline: SessionTurnPreparationBaseline,
) -> AsyncGenerator[ClaimedSessionSendTurn]:
    lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())
    lease_stop_event = asyncio.Event()

    claim = await repo.accept_session_turn(
        session_id=session_id,
        tenant_id=tenant_id,
        lease=lease,
        lock_lease_seconds=_send_lock_lease_seconds(),
        acceptance=accepted_turn,
        preparation_baseline=preparation_baseline,
    )
    turn = SessionSendTurn(
        session_id=session_id,
        tenant_id=tenant_id,
        lease=lease,
        base_planning_state_version=claim.base_planning_state_version,
    )

    async def admit_provider_work() -> None:
        await repo.mark_session_turn_processing(turn=turn)

    gate = ProviderWorkGate(
        admit=admit_provider_work,
        ownership_lost=asyncio.Event(),
        lease_lost=asyncio.Event(),
        session_id=str(session_id),
        request_id=str(lease.request_id),
    )
    if claim.disposition is SessionTurnClaimDisposition.PROVIDER_OUTCOME_UNKNOWN:
        raise AIBuilderProviderOutcomeUnknownException()
    if claim.disposition is SessionTurnClaimDisposition.REPLAY_COMMITTED:
        yield ClaimedSessionSendTurn(
            turn=turn,
            provider_gate=gate,
            user_message=claim.user_message,
            replayed=True,
            committed_error=claim.committed_error,
        )
        return
    heartbeat_tasks = tuple(
        asyncio.create_task(
            beat(
                session_id=session_id,
                tenant_id=tenant_id,
                lease=lease,
                stop_event=lease_stop_event,
                lease_lost_event=gate.lease_lost,
                ownership_lost_event=gate.ownership_lost,
            ),
            name=f"ai-builder-send-{label}-{lease.request_id}",
        )
        for label, beat in (
            ("lease-refresh", _maintain_send_lock_lease),
            ("ownership-probe", _watch_send_ownership),
        )
    )
    caught_error: Exception | None = None
    released_state: BuilderTurnState | None = None
    try:
        yield ClaimedSessionSendTurn(
            turn=turn,
            provider_gate=gate,
            user_message=claim.user_message,
        )
    except Exception as error:
        caught_error = error
    finally:
        lease_stop_event.set()
        # A client that reloads mid-stream cancels the response's scope, and
        # every await here would then re-raise before it ran: the lock stayed
        # for the whole lease and the user was told to wait 15 minutes. The
        # cleanup is therefore shielded, and bounded, so a stuck write cannot
        # hold the request task instead. The cancellation still propagates
        # once the lock is released.
        with anyio.move_on_after(
            _SEND_LOCK_RELEASE_TIMEOUT_SECONDS,
            shield=True,
        ) as release_scope:
            released_state = await _finalize_send_turn(
                session_id=session_id,
                tenant_id=tenant_id,
                lease=lease,
                heartbeat_tasks=heartbeat_tasks,
            )
        if release_scope.cancelled_caught:
            # Nothing further can be done here: the turn's own lease is
            # what the next claim falls back to, and it projects the same
            # terminal state once it runs out.
            logger.error(
                "AI Builder send lock release timed out; the lock is left to "
                "its lease.",
                extra={
                    "session_id": str(session_id),
                    "request_id": str(lease.request_id),
                },
            )
    if caught_error is not None:
        if (
            released_state is BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN
            and not isinstance(caught_error, AIBuilderBadRequestException)
        ):
            # The wrap hides the cause from the client by design, so this log
            # is the only place the real failure is observable. Without it,
            # 81 wedged sessions accumulated with no trace of what broke.
            logger.error(
                "AI Builder turn released into provider-outcome-unknown; "
                "wrapping the causing error.",
                exc_info=caught_error,
                extra={
                    "session_id": str(session_id),
                    "request_id": str(lease.request_id),
                },
            )
            raise AIBuilderProviderOutcomeUnknownException() from caught_error
        raise caught_error.with_traceback(caught_error.__traceback__)


def _send_lock_lease_seconds() -> int:
    return max(30, int(get_settings().ai_builder_send_lock_lease_seconds))


def _send_lock_refresh_interval_seconds() -> int:
    return max(5, _send_lock_lease_seconds() // 3)


async def _maintain_send_lock_lease(
    *,
    session_id: UUID,
    tenant_id: UUID,
    lease: SessionSendLease,
    stop_event: asyncio.Event,
    lease_lost_event: asyncio.Event,
    ownership_lost_event: asyncio.Event,
) -> None:
    while await _next_beat(stop_event, _send_lock_refresh_interval_seconds()):
        try:
            refreshed = await _refresh_session_send_lease(
                session_id=session_id,
                tenant_id=tenant_id,
                lease=lease,
                lock_lease_seconds=_send_lock_lease_seconds(),
            )
        except Exception as error:
            # A failed refresh proves nothing about ownership, so the work
            # goes on; but the lease is no longer renewed or trusted, so the
            # turn's results are fenced.
            logger.warning(
                "AI Builder send lease refresh failed.",
                exc_info=error,
                extra=_lease_log_context(session_id, lease),
            )
            lease_lost_event.set()
            return
        if not refreshed:
            _confirm_ownership_lost(
                "AI Builder send lease lost while processing.",
                session_id=session_id,
                lease=lease,
                lease_lost_event=lease_lost_event,
                ownership_lost_event=ownership_lost_event,
            )
            return


async def _watch_send_ownership(
    *,
    session_id: UUID,
    tenant_id: UUID,
    lease: SessionSendLease,
    stop_event: asyncio.Event,
    lease_lost_event: asyncio.Event,
    ownership_lost_event: asyncio.Event,
) -> None:
    """Signal the turn's stop once a read confirms the row is not ours.

    Unlike the refresh, a failed or slow probe never asserts the loss: it is
    logged and tried again, so a database hiccup cannot cancel healthy work.
    """

    failures = _ProbeFailureLog(session_id=session_id, lease=lease)
    while await _next_beat(stop_event, _SEND_OWNERSHIP_PROBE_INTERVAL_SECONDS):
        try:
            owned = await asyncio.wait_for(
                _probe_session_send_ownership(
                    session_id=session_id,
                    tenant_id=tenant_id,
                    lease=lease,
                ),
                timeout=_SEND_OWNERSHIP_PROBE_TIMEOUT_SECONDS,
            )
        except Exception as error:
            failures.record(error)
            continue
        if not owned:
            _confirm_ownership_lost(
                "AI Builder send lease taken while processing; stopping the turn.",
                session_id=session_id,
                lease=lease,
                lease_lost_event=lease_lost_event,
                ownership_lost_event=ownership_lost_event,
            )
            return


async def _next_beat(stop_event: asyncio.Event, interval: float) -> bool:
    """Wait one interval; False once the turn has stopped its heartbeat."""

    if stop_event.is_set():
        return False
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=interval)
    except asyncio.TimeoutError:
        return True
    return False


def _confirm_ownership_lost(
    message: str,
    *,
    session_id: UUID,
    lease: SessionSendLease,
    lease_lost_event: asyncio.Event,
    ownership_lost_event: asyncio.Event,
) -> None:
    logger.warning(message, extra=_lease_log_context(session_id, lease))
    lease_lost_event.set()
    ownership_lost_event.set()


class _ProbeFailureLog:
    """A turn's first probe failure in full, later ones as periodic summaries."""

    def __init__(self, *, session_id: UUID, lease: SessionSendLease) -> None:
        self._context = _lease_log_context(session_id, lease)
        self._failures = 0
        self._unreported = 0
        self._last_logged_at = 0.0

    def record(self, error: Exception) -> None:
        self._failures += 1
        now = time.monotonic()
        if self._failures == 1:
            logger.warning(
                "AI Builder send ownership probe failed; trying again.",
                exc_info=error,
                extra=self._context,
            )
            self._last_logged_at = now
            return
        self._unreported += 1
        if now - self._last_logged_at < _SEND_OWNERSHIP_PROBE_FAILURE_SUMMARY_SECONDS:
            return
        logger.warning(
            "AI Builder send ownership probe keeps failing; trying again.",
            extra={
                **self._context,
                "probe_failures": self._failures,
                "probe_failures_since_last_log": self._unreported,
                "last_probe_error": type(error).__name__,
            },
        )
        self._unreported = 0
        self._last_logged_at = now


def _lease_log_context(session_id: UUID, lease: SessionSendLease) -> dict[str, str]:
    return {"session_id": str(session_id), "request_id": str(lease.request_id)}


async def _finalize_send_turn(
    *,
    session_id: UUID,
    tenant_id: UUID,
    lease: SessionSendLease,
    heartbeat_tasks: tuple[asyncio.Task[None], ...],
) -> BuilderTurnState | None:
    await _drain_heartbeat(heartbeat_tasks, session_id=session_id, lease=lease)
    async with _lease_repository() as repo:
        return await repo.release_session_send(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=lease,
        )


async def _drain_heartbeat(
    heartbeat_tasks: tuple[asyncio.Task[None], ...],
    *,
    session_id: UUID,
    lease: SessionSendLease,
) -> None:
    """Stop the heartbeat within ``_SEND_HEARTBEAT_DRAIN_TIMEOUT_SECONDS``."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + _SEND_HEARTBEAT_DRAIN_TIMEOUT_SECONDS
    _, pending = await asyncio.wait(
        heartbeat_tasks, timeout=_SEND_HEARTBEAT_DRAIN_TIMEOUT_SECONDS / 2
    )
    for task in pending:
        task.cancel()
    if pending:
        _, pending = await asyncio.wait(
            pending, timeout=max(0.0, deadline - loop.time())
        )
    context = _lease_log_context(session_id, lease)
    for task in pending:
        _UNFINISHED_HEARTBEAT_TASKS.add(task)
        task.add_done_callback(_UNFINISHED_HEARTBEAT_TASKS.discard)
        logger.error(
            "AI Builder send heartbeat task ignored its cancellation; "
            "releasing without it.",
            extra={**context, "task_name": task.get_name()},
        )
    for task in heartbeat_tasks:
        if not task.done() or task.cancelled():
            continue
        error = task.exception()
        if error is not None:
            logger.warning(
                "AI Builder lease task exited with an unexpected error.",
                exc_info=error,
                extra=context,
            )


async def _probe_session_send_ownership(
    *,
    session_id: UUID,
    tenant_id: UUID,
    lease: SessionSendLease,
) -> bool:
    async with _lease_repository() as repo:
        return await repo.owns_session_send_lease(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=lease,
        )


async def _refresh_session_send_lease(
    *,
    session_id: UUID,
    tenant_id: UUID,
    lease: SessionSendLease,
    lock_lease_seconds: int,
) -> bool:
    async with _lease_repository() as repo:
        return await repo.refresh_session_send_lease(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=lease,
            lock_lease_seconds=lock_lease_seconds,
        )
