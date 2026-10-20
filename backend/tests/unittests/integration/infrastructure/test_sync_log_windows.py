"""Execute the batched history queries against SQL, including empty windows."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.sync_log_table import SyncLog
from eneo.integration.infrastructure.mappers.sync_log_mapper import SyncLogMapper
from eneo.integration.infrastructure.repo_impl.sync_log_repo_impl import SyncLogRepoImpl


@pytest.fixture
def history():
    metadata = sa.MetaData()
    knowledge = sa.Table(
        IntegrationKnowledge.__tablename__,
        metadata,
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid),
    )
    logs = sa.Table(
        SyncLog.__tablename__,
        metadata,
        *[
            sa.Column(
                column.name,
                sa.JSON() if isinstance(column.type, JSONB) else column.type,
                primary_key=column.primary_key,
            )
            for column in SyncLog.__table__.columns
        ],
    )
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    tenant, foreign_tenant = uuid4(), uuid4()
    ids = [uuid4() for _ in range(60)]
    foreign = uuid4()
    with Session(engine) as session:
        session.execute(
            knowledge.insert(),
            [{"id": item_id, "tenant_id": tenant} for item_id in ids]
            + [{"id": foreign, "tenant_id": foreign_tenant}],
        )
        now = datetime.now(timezone.utc)
        session.execute(
            logs.insert(),
            [
                {
                    "id": uuid4(),
                    "integration_knowledge_id": item_id,
                    "sync_type": "delta",
                    "status": "success",
                    "error_message": None,
                    "sync_metadata": {"files_processed": index},
                    "started_at": now,
                    "completed_at": now,
                    "created_at": now - timedelta(minutes=index),
                    "updated_at": now,
                }
                for item_id in [*ids[:-1], foreign]
                for index in range(5)
            ],
        )
        boundary = AsyncMock(spec=AsyncSession)
        boundary.execute.side_effect = session.execute
        boundary.scalars.side_effect = session.scalars
        yield SyncLogRepoImpl(boundary, SyncLogMapper()), boundary, tenant, ids, foreign
    engine.dispose()


async def test_windows_have_independent_offsets_and_constant_query_count(history):
    repo, session, tenant, ids, foreign = history
    offsets = {item_id: index % 7 for index, item_id in enumerate(ids)}
    pages = await repo.get_windows(offsets, tenant_id=tenant, limit=2)
    for item_id, offset in offsets.items():
        assert pages[item_id].total == (0 if item_id == ids[-1] else 5)
        assert [log.files_processed for log in pages[item_id].logs] == (
            [] if item_id == ids[-1] else list(range(5))[offset : offset + 2]
        )
    assert session.execute.await_count + session.scalars.await_count == 2


async def test_query_keeps_tenant_boundary_even_if_caller_passes_foreign_ids(history):
    repo, _, tenant, ids, foreign = history
    pages = await repo.get_windows({ids[0]: 0, foreign: 0}, tenant_id=tenant, limit=1)
    assert len(pages[ids[0]].logs) == 1
    assert pages[foreign].total == 0
    assert pages[foreign].logs == []


async def test_no_query_for_empty_batch(history):
    repo, session, tenant, _, _ = history
    assert await repo.get_windows({}, tenant_id=tenant, limit=1) == {}
    session.execute.assert_not_awaited()
    session.scalars.assert_not_awaited()


@pytest.mark.parametrize("count, limit", [(0, 1), (51, 1), (1, 0), (1, 11), (2, 1)])
def test_batch_contract_rejects_empty_oversized_or_duplicate_requests(count, limit):
    from pydantic import ValidationError

    from eneo.integration.presentation.models import IntegrationSyncDetailsRequest

    item_id = uuid4()
    with pytest.raises(ValidationError):
        IntegrationSyncDetailsRequest.model_validate(
            {
                "items": [{"integration_knowledge_id": item_id} for _ in range(count)],
                "limit": limit,
            }
        )
