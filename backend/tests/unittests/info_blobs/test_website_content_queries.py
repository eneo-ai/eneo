"""Bounded, scoped SQL contracts; directory semantics are also tested in PostgreSQL."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from eneo.database.tables.info_blobs_table import (
    website_navigation_path,
    website_path_below,
)
from eneo.info_blobs.info_blob_repo import InfoBlobRepository


async def test_content_filters_apply_to_both_count_and_page_without_loading_text():
    session = AsyncMock()
    session.scalar.return_value = 0
    session.scalars.return_value = []
    website_id = uuid4()
    cursor = uuid4()
    await InfoBlobRepository(session).get_by_website_page(
        website_id,
        q="50%_pdf",
        prefix="https://example.test/A%20B_/",
        cursor=cursor,
        limit=20,
    )
    statements = [session.scalar.await_args.args[0], session.scalars.await_args.args[0]]
    sql = [
        str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        .replace("%%", "%")
        .replace("\\\\", "\\")
        for statement in statements
    ]
    for statement in sql:
        assert str(website_id) in statement
        assert "version_state = 'active'" in statement
        # A byte-order range, not LIKE: the website path index serves it.
        assert "COLLATE \"C\") >= 'https://example.test/A%20B_/'" in statement
        assert "COLLATE \"C\") < 'https://example.test/A%20B_0'" in statement
        assert "LIKE 'https://example.test" not in statement
        assert r"ILIKE '%50\%\_pdf%'" in statement
        # The search runs below the selected directory, never over the host.
        assert "substr(" in statement
        assert "info_blobs.text" not in statement
    assert str(cursor) not in sql[0]
    assert str(cursor) in sql[1]
    assert "LIMIT 21" in sql[1]


async def test_search_without_a_directory_skips_the_scheme_and_host():
    session = AsyncMock()
    session.scalar.return_value = 0
    session.scalars.return_value = []
    await InfoBlobRepository(session).get_by_website_page(uuid4(), q="kommun", limit=20)
    sql = str(
        session.scalars.await_args.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).replace("%%", "%")
    assert "regexp_replace(" in sql
    assert "^https?://[^/]+" in sql
    assert "ILIKE '%kommun%'" in sql


async def test_directory_query_limits_output_and_filters_before_grouping():
    session = AsyncMock()
    response = MagicMock()
    response.all.return_value = []
    session.execute.return_value = response
    website_id = uuid4()
    result = await InfoBlobRepository(session).get_website_folders(
        website_id,
        prefix="https://example.test/A/",
        cursor="https://example.test/A/B/",
        limit=10,
    )
    statement = session.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert str(website_id) in sql
    assert "version_state = 'active'" in sql
    assert "GROUP BY" in sql
    assert "LIMIT 11" in sql
    assert "info_blobs.text" not in sql
    assert result.items == []
    assert result.next_cursor is None


def test_navigation_path_inlines_its_constants_like_its_index():
    compiled = website_navigation_path().compile(dialect=postgresql.dialect())
    assert compiled.params == {}
    assert "'^https?://[^/]+$'" in str(compiled)


def test_directory_range_ends_at_the_successor_of_its_last_character():
    compiled = website_path_below("https://example.test/Å/").compile(
        dialect=postgresql.dialect()
    )
    assert sorted(compiled.params.values()) == [
        "https://example.test/Å/",
        "https://example.test/Å0",
    ]
