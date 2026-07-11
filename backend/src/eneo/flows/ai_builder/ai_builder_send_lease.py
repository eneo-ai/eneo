from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

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


@dataclass(frozen=True, slots=True)
class ClaimedSessionSendTurn:
    turn: SessionSendTurn
    lease_lost_event: asyncio.Event
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
    lease_lost_event = asyncio.Event()

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
    if claim.disposition is SessionTurnClaimDisposition.PROVIDER_OUTCOME_UNKNOWN:
        raise AIBuilderProviderOutcomeUnknownException()
    if claim.disposition is SessionTurnClaimDisposition.REPLAY_COMMITTED:
        yield ClaimedSessionSendTurn(
            turn=turn,
            lease_lost_event=lease_lost_event,
            user_message=claim.user_message,
            replayed=True,
            committed_error=claim.committed_error,
        )
        return
    lease_task = asyncio.create_task(
        _maintain_send_lock_lease(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=lease,
            stop_event=lease_stop_event,
            lease_lost_event=lease_lost_event,
        )
    )
    caught_error: Exception | None = None
    try:
        yield ClaimedSessionSendTurn(
            turn=turn,
            lease_lost_event=lease_lost_event,
            user_message=claim.user_message,
        )
    except Exception as error:
        caught_error = error
    finally:
        lease_stop_event.set()
        try:
            await lease_task
        except asyncio.CancelledError:
            pass
        except Exception as error:
            logger.warning(
                "AI Builder lease task exited with an unexpected error.",
                exc_info=error,
                extra={
                    "session_id": str(session_id),
                    "request_id": str(lease.request_id),
                },
            )
        released_state = await repo.release_session_send(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=lease,
        )
    if caught_error is not None:
        if (
            released_state is BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN
            and not isinstance(caught_error, AIBuilderBadRequestException)
        ):
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
) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=_send_lock_refresh_interval_seconds(),
            )
            return
        except asyncio.TimeoutError:
            try:
                refreshed = await _refresh_session_send_lease(
                    session_id=session_id,
                    tenant_id=tenant_id,
                    lease=lease,
                    lock_lease_seconds=_send_lock_lease_seconds(),
                )
            except Exception as error:
                logger.warning(
                    "AI Builder send lease refresh failed.",
                    exc_info=error,
                    extra={
                        "session_id": str(session_id),
                        "request_id": str(lease.request_id),
                    },
                )
                lease_lost_event.set()
                return

            if not refreshed:
                logger.warning(
                    "AI Builder send lease lost while processing.",
                    extra={
                        "session_id": str(session_id),
                        "request_id": str(lease.request_id),
                    },
                )
                lease_lost_event.set()
                return


async def _refresh_session_send_lease(
    *,
    session_id: UUID,
    tenant_id: UUID,
    lease: SessionSendLease,
    lock_lease_seconds: int,
) -> bool:
    async with sessionmanager.session() as session:
        return await AIBuilderRepository(session).refresh_session_send_lease(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=lease,
            lock_lease_seconds=lock_lease_seconds,
        )
