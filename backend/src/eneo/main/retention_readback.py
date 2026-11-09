"""Run retention until no due work is left: the readback after a restore.

`run-cron --until-complete run_retention` runs this in its own process, with
traffic closed and every worker stopped. It runs the worker's own retention
cron, round after round, until every registered task shows that nothing due
is left, then drives the object-content reconciliation and reports separately
whether the store has confirmed every removal. It prints counts and reasons,
never content.

Exit 0: retention is complete (storage confirmed or pending). Exit 1: it is
not, or storage was not reachable or failed under it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import cast

from eneo.data_retention.application.retention_readback import (
    RetentionReadback,
    RetentionReadbackFailed,
)
from eneo.data_retention.application.retention_runner import RetentionRunReport
from eneo.data_retention.infrastructure.retention_worker import run_retention
from eneo.database.database import sessionmanager
from eneo.main.config import get_settings
from eneo.main.retention_tasks import retention_task_registrations
from eneo.object_content.content import ObjectContentError
from eneo.object_content.object_store_connection import ObjectStoreConnectionError
from eneo.object_content.runtime import object_content_runtime
from eneo.settings.encryption_service import EncryptionService

Emit = Callable[[str], None]


async def read_back_retention(*, emit: Emit) -> bool:
    """True when retention is complete and storage did not fail under it."""
    readback = RetentionReadback(
        registration.name
        for registration in retention_task_registrations(get_settings())
    )
    rounds = 0
    try:
        while True:
            rounds += 1
            reports = cast(list[RetentionRunReport], await run_retention({}))
            for report in reports:
                emit(_describe(rounds, report))
            if readback.add_round(reports):
                break
    except RetentionReadbackFailed as failed:
        emit("retention: not complete")
        for reason in failed.reasons:
            emit(f"  {reason}")
        return False
    emit(f"retention: complete after {rounds} rounds")
    return await _read_back_storage(emit)


async def _read_back_storage(emit: Emit) -> bool:
    runtime = object_content_runtime
    await runtime.refresh_object_store_configuration()
    if runtime.object_store_configured:
        try:
            await runtime.service.check_object_store_ready()
        except (ObjectContentError, ObjectStoreConnectionError) as error:
            emit(f"storage: not reachable ({error.code})")
            return False
    pending = await runtime.removal_readback()
    # Each pass removes at least one claimable payload or the loop ends; what
    # it cannot remove now (held, retried later) is reported as pending.
    while pending.pending:
        result = await runtime.reconcile_once()
        if result.store_failures:
            emit(
                f"storage: failed ({result.store_failures} store operations "
                "failed during reconciliation)"
            )
            return False
        after = await runtime.removal_readback()
        if after.pending >= pending.pending:
            pending = after
            break
        pending = after
    if pending.pending:
        emit(
            f"storage: pending {pending.pending} (held {pending.held}, "
            f"retrying {pending.retrying}, waiting {pending.waiting})"
        )
    else:
        emit("storage: confirmed")
    return True


def _describe(round_number: int, report: RetentionRunReport) -> str:
    outcome = report.outcome.value if report.outcome is not None else "held"
    removed = sum(report.disposed.values())
    return f"round {round_number}: {report.task} {outcome}, removed {removed}"


async def _main() -> int:
    settings = get_settings()
    sessionmanager.init(settings.database_url)
    object_content_runtime.start(
        encryption=EncryptionService(
            None if settings.testing else settings.encryption_key
        )
    )
    try:
        await object_content_runtime.validate_configuration()
        return 0 if await read_back_retention(emit=print) else 1
    except (ObjectContentError, ObjectStoreConnectionError) as error:
        print(f"storage: not reachable ({error.code})")
        return 1
    finally:
        await object_content_runtime.stop()
        await sessionmanager.close()


def main() -> int:
    return asyncio.run(_main())
