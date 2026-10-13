"""The SQL behind one page of an integration item's documents, without a database."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from eneo.info_blobs.info_blob_repo import InfoBlobRepository


def _compiled(statement) -> str:
    """The statement as PostgreSQL runs it, with pyformat/E-string doubling undone."""
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    return sql.replace("%%", "%").replace("\\\\", "\\")


def _record(knowledge_id):
    return SimpleNamespace(
        id=uuid4(),
        url="https://contoso.sharepoint.com/sites/KS/Shared%20Documents/KS-1.pdf",
        title="KS-1.pdf",
        embedding_model_id=uuid4(),
        user_id=uuid4(),
        tenant_id=uuid4(),
        size=1000,
        group_id=None,
        website_id=None,
        integration_knowledge_id=knowledge_id,
        sharepoint_item_id="item-1",
        source_metadata=None,
        content_hash=None,
        source_id=uuid4(),
        version_state="active",
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 13, tzinfo=timezone.utc),
        group=None,
        website=None,
    )


@pytest.fixture
def session():
    session = AsyncMock()
    totals = MagicMock()
    totals.one.return_value = (312, 123456)
    session.execute.return_value = totals
    return session


async def test_page_filters_active_documents_of_the_item_on_title_or_url(session):
    knowledge_id = uuid4()
    record = _record(knowledge_id)
    session.scalars.return_value = [record]

    page = await InfoBlobRepository(session).get_integration_knowledge_page(
        knowledge_id, q="50%_x", limit=50, offset=100
    )

    assert page.total_count == 312
    assert page.total_size == 123456
    assert [item.id for item in page.items] == [record.id]
    assert page.items[0].url == record.url

    totals_sql = _compiled(session.execute.await_args.args[0])
    page_sql = _compiled(session.scalars.await_args.args[0])
    for sql in (totals_sql, page_sql):
        assert f"info_blobs.integration_knowledge_id = '{knowledge_id}'" in sql
        assert "info_blobs.version_state = 'active'" in sql
        assert "info_blobs.title ILIKE '%50\\%\\_x%' ESCAPE '\\'" in sql
        assert "info_blobs.url ILIKE '%50\\%\\_x%' ESCAPE '\\'" in sql
    assert "count(*)" in totals_sql
    assert "coalesce(sum(info_blobs.size), 0)" in totals_sql
    assert "LIMIT 50 OFFSET 100" in page_sql
    assert "info_blobs.text" not in page_sql


@pytest.mark.parametrize(
    "sort, descending, expected",
    [
        (
            "path",
            False,
            "ORDER BY regexp_replace(info_blobs.url, '/[^/]*$', '') ASC NULLS LAST, "
            "info_blobs.title ASC NULLS LAST, info_blobs.id ASC",
        ),
        ("name", True, "ORDER BY info_blobs.title DESC NULLS LAST, info_blobs.id ASC"),
        ("size", True, "ORDER BY info_blobs.size DESC NULLS LAST, info_blobs.id ASC"),
        (
            "updated_at",
            False,
            "ORDER BY info_blobs.updated_at ASC NULLS LAST, info_blobs.id ASC",
        ),
    ],
)
async def test_page_orders_by_the_requested_key_with_a_stable_tiebreak(
    session, sort, descending, expected
):
    session.scalars.return_value = []

    page = await InfoBlobRepository(session).get_integration_knowledge_page(
        uuid4(), sort=sort, descending=descending, limit=10
    )

    assert page.items == []
    page_sql = _compiled(session.scalars.await_args.args[0])
    assert expected in page_sql
    assert "ILIKE" not in page_sql
