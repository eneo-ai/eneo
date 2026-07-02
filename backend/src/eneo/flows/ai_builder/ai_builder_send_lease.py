from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from eneo.main.config import get_settings
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ClaimedSessionSendTurn:
    turn: SessionSendTurn
    lease_lost_event: asyncio.Event


@asynccontextmanager
async def claim_ai_builder_send_turn(
    *,
    repo: "AIBuilderRepository",
    session_id: UUID,
    tenant_id: UUID,
    base_planning_state_version: int,
) -> AsyncGenerator[ClaimedSessionSendTurn]:
    lease = SessionSendLease(request_id=uuid4(), lock_token=uuid4())
    turn = SessionSendTurn(
        session_id=session_id,
        tenant_id=tenant_id,
        lease=lease,
        base_planning_state_version=base_planning_state_version,
    )
    lease_stop_event = asyncio.Event()
    lease_lost_event = asyncio.Event()

    claimed = await repo.claim_session_send(
        session_id=session_id,
        tenant_id=tenant_id,
        lease=lease,
        lock_expires_at=_next_send_lock_expiry(),
    )
    if not claimed:
        raise AIBuilderBadRequestException(
            "Another AI Builder message is already being processed for this session.",
            code=AIBuilderErrorCode.SESSION_MESSAGE_IN_PROGRESS,
        )

    lease_task = asyncio.create_task(
        _maintain_send_lock_lease(
            repo=repo,
            session_id=session_id,
            tenant_id=tenant_id,
            lease=lease,
            stop_event=lease_stop_event,
            lease_lost_event=lease_lost_event,
        )
    )
    try:
        yield ClaimedSessionSendTurn(turn=turn, lease_lost_event=lease_lost_event)
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
        await repo.release_session_send(
            session_id=session_id,
            tenant_id=tenant_id,
            lease=lease,
        )


def _send_lock_lease_seconds() -> int:
    return max(30, int(get_settings().ai_builder_send_lock_lease_seconds))


def _next_send_lock_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=_send_lock_lease_seconds())


def _send_lock_refresh_interval_seconds() -> int:
    return max(5, _send_lock_lease_seconds() // 3)


async def _maintain_send_lock_lease(
    *,
    repo: "AIBuilderRepository",
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
                refreshed = await repo.refresh_session_send_lease(
                    session_id=session_id,
                    tenant_id=tenant_id,
                    lease=lease,
                    lock_expires_at=_next_send_lock_expiry(),
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
