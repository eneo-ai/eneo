"""The SQL behind one page of an integration item's documents, without a database."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.info_blobs.info_blob_repo import (
    InfoBlobRepository,
    _title_or_path_matches,
)

ANCHOR = "https://contoso.sharepoint.com/sites/KS/Shared%20Documents/Protokoll"
ANCHOR_LIKE = ANCHOR.replace("%", "\\%")
# The URL part below the anchor, or the whole URL when it does not start there.
BELOW_ANCHOR = (
    f"CASE WHEN (info_blobs.url ILIKE '{ANCHOR_LIKE}%' ESCAPE '\\') "
    f"THEN SUBSTRING(info_blobs.url FROM {len(ANCHOR) + 1}) "
    "ELSE info_blobs.url END"
)
# Each property value, also each entry of a multi-value list; never a name or
# label, which every document of a library shares, nor a yes/no value, stored
# as true/false. Postgres evaluates the path in
# tests/integration/info_blobs/test_integration_document_property_search.py.
PROPERTY_VALUE = (
    "EXISTS (SELECT * FROM jsonb_array_elements_text(jsonb_path_query_array("
    "info_blobs.source_metadata, "
    """'$[*] ? (!(@.kind == "boolean")).value[*]')) AS value WHERE value"""
)


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


async def test_page_filters_active_documents_of_the_item_on_title_path_or_property(
    session,
):
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
        assert f"{BELOW_ANCHOR} ILIKE '%50\\%\\_x%' ESCAPE '\\'" in sql
        assert f"{PROPERTY_VALUE} ILIKE '%50\\%\\_x%' ESCAPE '\\'" in " ".join(
            sql.split()
        )
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
                f"{BELOW_ANCHOR} ILIKE '%Årsmöte%'",
                f"{BELOW_ANCHOR} ILIKE '%\\%C3\\%85rsm\\%C3\\%B6te%'",
            ],
        ),
        (
            "Shared Documents",
            ANCHOR,
            [
                f"{BELOW_ANCHOR} ILIKE '%Shared Documents%'",
                f"{BELOW_ANCHOR} ILIKE '%Shared\\%20Documents%'",
            ],
        ),
        # Nothing to encode: one URL match, below the anchor only, so the
        # site name KS in /sites/KS cannot match every document of the item.
        ("KS", ANCHOR, [f"{BELOW_ANCHOR} ILIKE '%KS%'"]),
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
    sql = _compiled(sa.select(sa.literal(1)).where(_title_or_path_matches(q, anchor)))

    assert f"info_blobs.title ILIKE '%{q}%'" in sql
    for expected in expected_url_matches:
        assert expected in sql
    # Each URL match carries its own prefix test when an anchor is set.
    per_url_match = 2 if anchor else 1
    assert sql.count("ILIKE") == 1 + per_url_match * len(expected_url_matches)
    if anchor:
        assert f"info_blobs.url ILIKE '%{q}%'" not in sql


RENAMED_ANCHOR = "https://contoso.sharepoint.com/sites/KS/Shared%20Documents/Protokoll%20och%20beslut"
DOCUMENTS = [
    (f"{ANCHOR}/Beslut.pdf", "Beslut.pdf"),
    (f"{ANCHOR}/Arbetsgrupp/KS-1.pdf", "KS-1.pdf"),
    ("https://contoso.sharepoint.com/sites/KS/Shared%20Documents/Rutin.docx", "Rutin"),
]


@pytest.fixture
def documents():
    """``DOCUMENTS`` in a table SQLite evaluates the match against."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE info_blobs (url TEXT, title TEXT)"))
        connection.execute(
            sa.text("INSERT INTO info_blobs VALUES (:url, :title)"),
            [{"url": url, "title": title} for url, title in DOCUMENTS],
        )

    def matching(q: str, anchor: str | None) -> list[str]:
        query = sa.select(InfoBlobs.title).where(_title_or_path_matches(q, anchor))
        with engine.connect() as connection:
            return sorted(connection.scalars(query))

    return matching


@pytest.mark.parametrize(
    "q, anchor, expected",
    [
        ("KS", ANCHOR, ["KS-1.pdf", "Rutin"]),
        ("Protokoll", ANCHOR, []),
        ("Arbetsgrupp", ANCHOR, ["KS-1.pdf"]),
        ("Shared Documents", ANCHOR, ["Rutin"]),
        # The selected folder was renamed to a shorter name: documents carry
        # the new URL while the item still stores the old one.
        ("Arbetsgrupp", RENAMED_ANCHOR, ["KS-1.pdf"]),
        ("KS", RENAMED_ANCHOR, ["Beslut.pdf", "KS-1.pdf", "Rutin"]),
        ("KS", None, ["Beslut.pdf", "KS-1.pdf", "Rutin"]),
    ],
    ids=[
        "site name only in the title or outside the anchor",
        "anchor folder is not below the anchor",
        "nested folder below the anchor",
        "library of a document outside the anchor",
        "nested folder after the selected folder was renamed",
        "whole URL after the selected folder was renamed",
        "whole URL without an anchor",
    ],
)
def test_search_strips_the_anchor_only_from_urls_that_start_with_it(
    documents, q, anchor, expected
):
    assert documents(q, anchor) == expected
