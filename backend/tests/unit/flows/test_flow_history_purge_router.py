from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import visitors

from eneo.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
)
from eneo.database.tables.flow_tables import (
    FLOW_RUN_TERMINAL_RETENTION_ANCHOR_INDEX_PREDICATE,
)
from eneo.settings.settings import FlowRunHistoryPurgeRequest
from eneo.settings.settings_router import (
    purge_flow_run_history,
    purge_organization_flow_run_history,
    purge_space_flow_run_history,
)


@pytest.mark.parametrize(
    "endpoint,scope_key",
    [
        (purge_organization_flow_run_history, None),
        (purge_space_flow_run_history, "space_id"),
        (purge_flow_run_history, "flow_id"),
    ],
)
async def test_purge_router_passes_only_resolved_scope_and_validated_request(
    endpoint, scope_key
):
    service = AsyncMock()
    container = MagicMock()
    container.flow_run_retention_policy_service.return_value = service
    scope = {} if scope_key is None else {scope_key: uuid4()}
    result = await endpoint(
        container=container, payload=FlowRunHistoryPurgeRequest(), **scope
    )
    service.purge_due_history.assert_awaited_once_with(dry_run=True, limit=100, **scope)
    assert result is service.purge_due_history.return_value


@pytest.mark.parametrize(
    "payload",
    [
        {"limit": 0},
        {"limit": 501},
        {"limit": True},
        {"limit": "1"},
        {"dry_run": "false"},
        {"tenant_id": str(uuid4())},
    ],
)
def test_purge_request_rejects_invalid_or_untrusted_options(payload):
    with pytest.raises(ValidationError):
        FlowRunHistoryPurgeRequest.model_validate(payload)


@pytest.mark.parametrize("query_kind", ["diagnostic", "batch"])
async def test_purge_queries_keep_the_terminal_index_predicate(query_kind):
    session = MagicMock(spec=AsyncSession)
    rows = MagicMock()
    rows.all.return_value = []
    session.execute.return_value = rows
    session.scalars.return_value = rows
    await DataRetentionService(session).purge_due_flow_run_history_for_tenant(
        tenant_id=uuid4(), now=datetime.now(timezone.utc), limit=2, dry_run=True
    )
    call = (
        session.execute.await_args
        if query_kind == "diagnostic"
        else session.scalars.await_args
    )
    sql = str(
        call.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    predicate = f"flow_runs.{FLOW_RUN_TERMINAL_RETENTION_ANCHOR_INDEX_PREDICATE}"
    assert any(
        predicate
        in str(
            query.whereclause.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        for query in visitors.iterate(call.args[0])
        if isinstance(query, sa.Select) and query.whereclause is not None
    )
    if query_kind == "diagnostic":
        assert "LIMIT 501" in sql
    else:
        assert "LIMIT 2" in sql
