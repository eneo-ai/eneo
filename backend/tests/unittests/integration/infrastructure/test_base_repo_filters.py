"""Exercise repository predicates against SQLite, without external services."""

from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import MetaData, Uuid, create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, Session, mapped_column

from eneo.base.base_entity import Entity, EntityMapper
from eneo.database.tables.base_class import BasePublic
from eneo.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl
from eneo.main.exceptions import NotFoundException


class ScopedRecord(BasePublic):
    __tablename__ = "integration_filter_contract"
    metadata = MetaData()
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    user_id: Mapped[UUID] = mapped_column(Uuid)


@pytest.fixture
def records():
    return [
        ScopedRecord(id=uuid4(), tenant_id=uuid4(), user_id=uuid4()),
        ScopedRecord(id=uuid4(), tenant_id=uuid4(), user_id=uuid4()),
    ]


@pytest.fixture
def repo(records):
    engine = create_engine("sqlite://")
    ScopedRecord.__table__.create(engine)
    with Session(engine) as session:
        session.add_all(records)
        session.flush()
        # Only adapt the async boundary; execute the real SQL and mapper input.
        async_session = AsyncMock(spec=AsyncSession)
        async_session.scalar.side_effect = session.scalar
        mapper = Mock(spec=EntityMapper)
        mapper.to_entity.side_effect = lambda record: Entity(id=record.id)
        yield BaseRepoImpl(async_session, ScopedRecord, mapper)
    engine.dispose()


async def test_id_and_scope_must_match_the_same_record(repo, records):
    own, foreign = records
    assert await repo.one_or_none(id=foreign.id, tenant_id=own.tenant_id) is None
    assert await repo.one_or_none(id=foreign.id, user_id=own.user_id) is None
    assert await repo.one_or_none(id=uuid4(), tenant_id=own.tenant_id) is None
    with pytest.raises(NotFoundException):
        await repo.one(id=foreign.id, tenant_id=own.tenant_id)


async def test_combined_filters_return_the_requested_record(repo, records):
    own = records[0]
    result = await repo.one(id=own.id, tenant_id=own.tenant_id, user_id=own.user_id)
    assert result.id == own.id


async def test_id_only_and_filter_only_lookups_still_work(repo, records):
    own = records[0]
    assert (await repo.one(id=own.id)).id == own.id
    assert (await repo.one(tenant_id=own.tenant_id)).id == own.id


async def test_unfiltered_lookup_is_rejected(repo):
    with pytest.raises(ValueError, match="No filter"):
        await repo.one_or_none()
