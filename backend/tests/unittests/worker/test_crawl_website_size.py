from typing import cast
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from intric.worker.crawl.website_size import update_website_size_after_crawl


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[sa.sql.ClauseElement] = []

    async def execute(self, statement: sa.sql.ClauseElement) -> None:
        self.statements.append(statement)


def _compile(statement: sa.sql.ClauseElement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


async def test_update_website_size_after_crawl_sets_coalesced_blob_size_sum() -> None:
    website_id = uuid4()
    tenant_id = uuid4()
    session = _RecordingSession()

    await update_website_size_after_crawl(
        cast(AsyncSession, session),
        website_id=website_id,
        tenant_id=tenant_id,
    )

    assert len(session.statements) == 1
    compiled_sql = _compile(session.statements[0])
    assert "UPDATE websites SET size=(" in compiled_sql
    assert "SELECT coalesce(sum(info_blobs.size), 0)" in compiled_sql
    assert f"info_blobs.website_id = '{website_id}'" in compiled_sql
    assert f"info_blobs.tenant_id = '{tenant_id}'" in compiled_sql
    assert f"websites.id = '{website_id}'" in compiled_sql
    assert f"websites.tenant_id = '{tenant_id}'" in compiled_sql
