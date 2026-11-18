"""The audit log's description search: case rules and its trigram index."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.audit_log import AuditLog
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from tests.integration.flows.statement_capture_support import capture_queries

pytestmark = pytest.mark.integration


def _log(tenant_id, actor_id, description: str) -> AuditLog:
    return AuditLog(
        id=uuid4(),
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_type=ActorType.USER,
        action=ActionType.ASSISTANT_CREATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=uuid4(),
        timestamp=datetime.now(timezone.utc),
        description=description,
        metadata={},
        outcome=Outcome.SUCCESS,
    )


async def test_search_ignores_case_of_swedish_letters(
    db_session, test_tenant, test_user
) -> None:
    async with db_session() as session:
        repo = AuditLogRepositoryImpl(session)
        await repo.create(
            _log(test_tenant.id, test_user, "Skapade assistenten 'Ärendehjälp Å'")
        )
        await repo.create(_log(test_tenant.id, test_user, "Skapade 'Annat'"))

        for term in ("ärendehjälp å", "ÄRENDEHJÄLP Å", "ÄrEnDeHjÄlP"):
            logs, total = await repo.get_logs(tenant_id=test_tenant.id, search=term)
            assert total == 1, term
            assert logs[0].description == "Skapade assistenten 'Ärendehjälp Å'"


async def test_description_search_matches_the_trigram_index_expression(
    db_session, test_tenant, test_user
) -> None:
    """The index is on lower(description): an ILIKE on the column cannot use it.

    The planner only picks the index on a large table (1M rows: a searched count
    went from 221 ms to 9.5 ms), so this pins the predicate's form.
    """
    async with db_session() as session:
        repo = AuditLogRepositoryImpl(session)
        await repo.create(_log(test_tenant.id, test_user, "Updated 'Sales Bot'"))
        bind = session.sync_session.bind
        assert bind is not None
        with capture_queries(bind) as queries:
            logs, total = await repo.get_logs(tenant_id=test_tenant.id, search="sales")

    assert total == 1 and len(logs) == 1
    searched = [q.sql for q in queries if "audit_logs.description" in q.sql]
    assert searched
    for sql in searched:
        assert "lower(audit_logs.description) LIKE lower(" in sql
        assert "ILIKE" not in sql.upper()


_FORCE_CUSTOM_PLANS = "SET LOCAL plan_cache_mode = force_custom_plan"


@contextmanager
def _statements(bind: Connection | Engine) -> Iterator[list[str]]:
    """Every statement ``bind`` sends inside the block, in order."""
    sent: list[str] = []

    def record(_connection: object, _cursor: object, statement: str, *_: object):
        sent.append(statement)

    sa.event.listen(bind, "before_cursor_execute", record)
    try:
        yield sent
    finally:
        sa.event.remove(bind, "before_cursor_execute", record)


async def _plan_cache_mode(session: AsyncSession) -> str | None:
    return await session.scalar(sa.text("SELECT current_setting('plan_cache_mode')"))


async def test_search_plans_its_count_and_page_for_the_pattern(
    db_session, test_tenant, test_user
) -> None:
    """A pooled connection reuses the prepared count and page. After five runs
    Postgres may plan them once for any pattern, and that plan scans the
    trigram index even for a term matching most of the log."""
    async with db_session() as session:
        repo = AuditLogRepositoryImpl(session)
        await repo.create(_log(test_tenant.id, test_user, "Updated 'Sales Bot'"))
        before = await _plan_cache_mode(session)
        bind = session.sync_session.bind
        assert bind is not None

        with _statements(bind) as unsearched:
            await repo.get_logs(tenant_id=test_tenant.id)
        assert _FORCE_CUSTOM_PLANS not in unsearched
        assert await _plan_cache_mode(session) == before

        with _statements(bind) as searched:
            logs, total = await repo.get_logs(tenant_id=test_tenant.id, search="sales")
        assert total == 1 and len(logs) == 1
        assert searched.count(_FORCE_CUSTOM_PLANS) == 1
        after_set = searched[searched.index(_FORCE_CUSTOM_PLANS) + 1 :]
        count, page = [s for s in after_set if "lower(audit_logs.description)" in s]
        assert count.lstrip().startswith("SELECT count(")
        assert "ORDER BY audit_logs.timestamp DESC" in page
        assert await _plan_cache_mode(session) == "force_custom_plan"


@pytest.mark.parametrize("end", ["commit", "rollback"])
async def test_search_leaves_plan_cache_mode_as_it_was_after_its_transaction(
    db_session, test_tenant, test_user, end: str
) -> None:
    async with db_session() as session:
        await AuditLogRepositoryImpl(session).create(
            _log(test_tenant.id, test_user, "Updated 'Sales Bot'")
        )
        engine = session.bind
    assert isinstance(engine, AsyncEngine)

    # One physical connection across both transactions.
    async with engine.connect() as connection:
        mode = sa.text("SELECT current_setting('plan_cache_mode')")
        before = await connection.scalar(mode)
        await connection.rollback()

        session = AsyncSession(bind=connection)
        await AuditLogRepositoryImpl(session).get_logs(
            tenant_id=test_tenant.id, search="sales"
        )
        assert await _plan_cache_mode(session) == "force_custom_plan"
        await (session.commit() if end == "commit" else session.rollback())
        await session.close()

        assert await connection.scalar(mode) == before
        await connection.rollback()
