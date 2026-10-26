"""The audit log's description search: case rules and its trigram index."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

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
