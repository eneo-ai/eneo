"""The readback after a restore runs the worker's own retention cron in this
process until no due work is left, and fails, naming why, when it cannot show
that."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import sessionmanager
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.main.retention_readback import read_back_retention
from eneo.object_content.reconciliation import ReconciliationResult, RemovalReadback
from eneo.object_content.runtime import object_content_runtime
from tests.integration.data_retention.test_empty_sessions import (
    _assistant,
    _question,
    _session,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture
async def object_content() -> AsyncIterator[None]:
    started_here = not object_content_runtime.enabled
    if started_here:
        object_content_runtime.start()
        await object_content_runtime.validate_configuration()
    yield
    if started_here:
        await object_content_runtime.stop()


async def _exists(model: type[Questions] | type[Sessions], row_id: object) -> bool:
    async with sessionmanager.session() as session, session.begin():
        return await session.get(model, row_id) is not None


async def test_the_readback_removes_due_history_and_then_completes(
    retention_session: AsyncSession,
    object_content: None,
    test_tenant,
    admin_user,
    completion_model_factory,
) -> None:
    old = datetime.now(timezone.utc) - timedelta(days=60)
    assistant = await _assistant(
        retention_session,
        completion_model_factory,
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
    )
    chat = await _session(retention_session, user_id=admin_user.id, created_at=old)
    due = await _question(
        retention_session,
        tenant_id=test_tenant.id,
        session_id=chat.id,
        assistant_id=assistant.id,
        created_at=old,
    )
    due_id, chat_id = due.id, chat.id
    await retention_session.commit()
    lines: list[str] = []

    assert await read_back_retention(emit=lines.append) is True

    assert not await _exists(Questions, due_id)
    assert not await _exists(Sessions, chat_id)
    assert any(line.startswith("retention: complete") for line in lines), lines
    assert "storage: confirmed" in lines


async def test_a_locked_empty_session_fails_the_readback_until_it_is_released(
    retention_session: AsyncSession, object_content: None, admin_user
) -> None:
    """Work skipped because another transaction holds it is due work left
    behind, not work that is done."""
    empty = await _session(
        retention_session,
        user_id=admin_user.id,
        created_at=datetime.now(timezone.utc) - timedelta(days=3),
    )
    empty_id = empty.id
    await retention_session.commit()

    async with sessionmanager.session() as holder, holder.begin():
        await holder.execute(
            sa.select(Sessions.id).where(Sessions.id == empty_id).with_for_update()
        )
        held: list[str] = []
        assert await read_back_retention(emit=held.append) is False
    assert any("sessions.empty" in line and "root_locked" in line for line in held), (
        held
    )
    assert await _exists(Sessions, empty_id)

    released: list[str] = []
    assert await read_back_retention(emit=released.append) is True
    assert not await _exists(Sessions, empty_id)


async def test_a_store_failure_during_reconciliation_fails_the_readback(
    retention_session: AsyncSession,
    object_content: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Storage pending is reported, not failed; a store that failed under the
    readback is a failure."""

    async def pending() -> RemovalReadback:
        return RemovalReadback(held=0, retrying=0, waiting=1)

    async def failed_pass() -> ReconciliationResult:
        return replace(ReconciliationResult.empty(), store_failures=1)

    monkeypatch.setattr(object_content_runtime, "removal_readback", pending)
    monkeypatch.setattr(object_content_runtime, "reconcile_once", failed_pass)
    await retention_session.commit()
    lines: list[str] = []

    assert await read_back_retention(emit=lines.append) is False
    assert any(line.startswith("storage:") and "failed" in line for line in lines), (
        lines
    )


async def test_removals_kept_by_storage_are_reported_as_pending(
    retention_session: AsyncSession,
    object_content: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def pending() -> RemovalReadback:
        return RemovalReadback(held=2, retrying=1, waiting=0)

    async def quiet_pass() -> ReconciliationResult:
        return ReconciliationResult.empty()

    monkeypatch.setattr(object_content_runtime, "removal_readback", pending)
    monkeypatch.setattr(object_content_runtime, "reconcile_once", quiet_pass)
    await retention_session.commit()
    lines: list[str] = []

    assert await read_back_retention(emit=lines.append) is True
    assert "storage: pending 3 (held 2, retrying 1, waiting 0)" in lines
