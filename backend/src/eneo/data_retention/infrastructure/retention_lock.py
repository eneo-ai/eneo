"""The advisory locks that serialize retention (retention deletion) with retention decisions.

One lock per subject of retention. Every transaction that deletes a subject's
history takes the subject's lock SHARED, so deletions run side by side. Every
change to what may be deleted (retention policies, legal holds) takes it
EXCLUSIVE, so it waits for open deletions to commit and they wait for it. A
deletion therefore never acts on a decision older than its own lock.
Transaction-level: released at commit or rollback.

Take it before any row lock in the transaction, so the lock order is the same
everywhere. The wait is bounded; a busy lock is refused as a typed conflict.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.main.exceptions import ConflictException

RETENTION_LOCK_TIMEOUT: Final = "5s"
_LOCK_NOT_AVAILABLE_SQLSTATE: Final = "55P03"


class RetentionSubject(Enum):
    """What a retention lock covers: (advisory key, refusal code when busy).

    One installation-wide key per subject (single-tenant deployment); any int8 not
    used by another advisory lock in the schema.
    """

    FLOW_HISTORY = (7_340_200_411_031_001, "flow_retention_lock_busy")

    @property
    def key(self) -> int:
        return self.value[0]

    @property
    def busy_code(self) -> str:
        return self.value[1]


class RetentionLockBusy(ConflictException):
    def __init__(self, subject: RetentionSubject) -> None:
        super().__init__(
            "Retention is busy with another change or deletion. Try again.",
            code=subject.busy_code,
        )
        self.subject = subject


def shared_lock_statement(subject: RetentionSubject) -> sa.Select[tuple[object]]:
    return sa.select(
        sa.func.pg_advisory_xact_lock_shared(
            sa.literal(subject.key, type_=sa.BigInteger)
        )
    )


def exclusive_lock_statement(subject: RetentionSubject) -> sa.Select[tuple[object]]:
    return sa.select(
        sa.func.pg_advisory_xact_lock(sa.literal(subject.key, type_=sa.BigInteger))
    )


async def acquire_shared(session: AsyncSession, subject: RetentionSubject) -> None:
    """For a transaction that deletes the subject's history."""
    await _acquire(session, subject, shared_lock_statement(subject))


async def acquire_exclusive(session: AsyncSession, subject: RetentionSubject) -> None:
    """For a transaction that changes what may be deleted (policy, legal hold)."""
    await _acquire(session, subject, exclusive_lock_statement(subject))


async def _acquire(
    session: AsyncSession,
    subject: RetentionSubject,
    statement: sa.Select[tuple[object]],
) -> None:
    previous = await session.scalar(sa.select(sa.func.current_setting("lock_timeout")))
    await session.execute(
        sa.select(sa.func.set_config("lock_timeout", RETENTION_LOCK_TIMEOUT, True))
    )
    try:
        await session.execute(statement)
    except DBAPIError as exc:
        if _is_lock_not_available(exc):
            raise RetentionLockBusy(subject) from exc
        raise
    # Restore the caller's setting so row locks taken later wait as before.
    await session.execute(sa.select(sa.func.set_config("lock_timeout", previous, True)))


def _is_lock_not_available(error: DBAPIError) -> bool:
    orig = error.orig
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return sqlstate == _LOCK_NOT_AVAILABLE_SQLSTATE
