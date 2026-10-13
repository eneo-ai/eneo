"""The SQL behind one page of an integration item's documents, without a database."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from eneo.info_blobs.info_blob_repo import InfoBlobRepository, _document_matches

ANCHOR = "https://contoso.sharepoint.com/sites/KS/Shared%20Documents/Protokoll"


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


async def test_page_filters_active_documents_of_the_item_on_title_or_path(session):
    knowledge_id = uuid4()
    record = _record(knowledge_id)
    session.scalars.return_value = [record]

    page = await InfoBlobRepository(session).get_integration_knowledge_page(
        knowledge_id, q="50%_x", url_anchor=ANCHOR, limit=50, offset=100
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
        assert (
            f"SUBSTRING(info_blobs.url FROM {len(ANCHOR) + 1}) "
            "ILIKE '%50\\%\\_x%' ESCAPE '\\'"
        ) in sql
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


@pytest.mark.parametrize(
    "q, anchor, expected_url_matches",
    [
        (
            "Årsmöte",
            ANCHOR,
            [
                f"SUBSTRING(info_blobs.url FROM {len(ANCHOR) + 1}) ILIKE '%Årsmöte%'",
                f"SUBSTRING(info_blobs.url FROM {len(ANCHOR) + 1}) "
                "ILIKE '%\\%C3\\%85rsm\\%C3\\%B6te%'",
            ],
        ),
        (
            "Shared Documents",
            ANCHOR,
            [
                f"SUBSTRING(info_blobs.url FROM {len(ANCHOR) + 1}) "
                "ILIKE '%Shared Documents%'",
                f"SUBSTRING(info_blobs.url FROM {len(ANCHOR) + 1}) "
                "ILIKE '%Shared\\%20Documents%'",
            ],
        ),
        # Nothing to encode: one URL match, below the anchor only, so the
        # site name KS in /sites/KS cannot match every document of the item.
        (
            "KS",
            ANCHOR,
            [f"SUBSTRING(info_blobs.url FROM {len(ANCHOR) + 1}) ILIKE '%KS%'"],
        ),
        ("KS", None, ["info_blobs.url ILIKE '%KS%'"]),
    ],
    ids=[
        "encoded Swedish folder",
        "encoded space",
        "site name below anchor",
        "no anchor",
    ],
)
def test_search_matches_the_title_and_the_url_below_the_item(
    q, anchor, expected_url_matches
):
    sql = _compiled(sa.select(sa.literal(1)).where(_document_matches(q, anchor)))

    assert f"info_blobs.title ILIKE '%{q}%'" in sql
    for expected in expected_url_matches:
        assert expected in sql
    assert sql.count("ILIKE") == 1 + len(expected_url_matches)
    if anchor:
        assert "info_blobs.url ILIKE" not in sql
