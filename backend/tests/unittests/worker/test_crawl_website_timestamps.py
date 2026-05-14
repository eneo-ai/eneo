from collections.abc import Mapping
from uuid import uuid4

import pytest

from intric.websites.domain.crawl_run import CrawlType
from intric.worker.crawl.website_timestamps import (
    update_website_timestamps_after_crawl,
)


class _FakeExecuteResult:
    rowcount = 1


class _FakeSession:
    def __init__(self) -> None:
        self.executed: list[object] = []

    async def execute(self, stmt: object) -> _FakeExecuteResult:
        self.executed.append(stmt)
        return _FakeExecuteResult()


def _compiled_params(stmt: object) -> dict[str, object]:
    compile_stmt = getattr(stmt, "compile", None)
    assert callable(compile_stmt)
    params = compile_stmt().params
    assert isinstance(params, Mapping)
    return dict(params)


def _compiled_sql(stmt: object) -> str:
    compile_stmt = getattr(stmt, "compile", None)
    assert callable(compile_stmt)
    return str(compile_stmt())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "crawl_type",
        "crawl_is_partial",
        "pages_failed",
        "files_failed",
        "expected_columns",
    ),
    [
        (
            CrawlType.SITEMAP,
            False,
            0,
            0,
            ("last_crawled_at", "last_source_verified_at"),
        ),
        (CrawlType.SITEMAP, True, 0, 0, ("last_crawled_at",)),
        (CrawlType.SITEMAP, False, 1, 0, ("last_crawled_at",)),
        (CrawlType.SITEMAP, False, 0, 1, ("last_crawled_at",)),
        (CrawlType.CRAWL, False, 0, 0, ("last_crawled_at",)),
    ],
)
async def test_post_crawl_timestamp_update_uses_lifecycle_policy(
    crawl_type: CrawlType,
    crawl_is_partial: bool,
    pages_failed: int,
    files_failed: int,
    expected_columns: tuple[str, ...],
) -> None:
    website_id = uuid4()
    tenant_id = uuid4()
    session = _FakeSession()

    await update_website_timestamps_after_crawl(
        session,
        website_id=website_id,
        tenant_id=tenant_id,
        crawl_type=crawl_type,
        crawl_is_partial=crawl_is_partial,
        pages_failed=pages_failed,
        files_failed=files_failed,
    )

    assert len(session.executed) == 1
    sql = _compiled_sql(session.executed[0])
    params = _compiled_params(session.executed[0])
    assert params["id_1"] == website_id
    assert params["tenant_id_1"] == tenant_id
    assert "WHERE websites.id = :id_1" in sql
    assert "websites.tenant_id = :tenant_id_1" in sql
    normalized_sql = sql.lower().replace(" ", "")
    for column in expected_columns:
        assert column in sql
        assert f"{column}=now()" in normalized_sql

    unexpected_columns = {
        "last_crawled_at",
        "last_source_verified_at",
    } - set(expected_columns)
    for column in unexpected_columns:
        assert column not in sql
