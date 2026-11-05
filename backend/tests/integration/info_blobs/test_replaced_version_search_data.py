"""Replaced knowledge versions keep their text but release their search data.

Only the active version of a source is ever searched, so a replaced version's
chunks and vectors are released once its replacement is published. The row,
its text and its original stay readable for historical citations.
"""

from __future__ import annotations

import asyncio
import math
import signal
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.dialects.postgresql.asyncpg import dialect as asyncpg_dialect

from eneo.database.database import sessionmanager
from eneo.database.tables.info_blob_chunk_table import InfoBlobChunks
from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from eneo.database.tables.questions_table import InfoBlobReferences, Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.info_blobs import replaced_versions
from eneo.info_blobs.info_blob_repo import InfoBlobRepository, ReplacedPage
from eneo.info_blobs.replaced_versions import (
    CleanupProgress,
    StatusProgress,
    _execute,
    release_all,
    scan_remaining,
)
from eneo.worker.crawl.persistence import (
    _publish_prepared_pages,
    _refresh_http_validators,
)
from tests.integration.info_blobs.test_info_blob_version_publication import (
    _embedding_result,
    _inline_original,
    _leased_crawl_context,
    _prepared_page,
    _seed_active_document,
)


async def _versions_of(session, website_id):
    return list(
        await session.scalars(
            sa.select(InfoBlobs)
            .where(InfoBlobs.website_id == website_id)
            .order_by(InfoBlobs.created_at, InfoBlobs.id)
        )
    )


async def _chunk_count(session, info_blob_id) -> int:
    return int(
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(InfoBlobChunks)
            .where(InfoBlobChunks.info_blob_id == info_blob_id)
        )
    )


async def test_changed_crawl_page_releases_the_replaced_versions_search_data(
    db_session,
    admin_user,
    space_factory,
) -> None:
    ctx = await _leased_crawl_context(db_session, admin_user, space_factory)
    url = "https://example.com/opening-hours"
    first = _prepared_page(ctx, url=url, title="Opening hours", text="Open 8-16")
    published, failures = await _publish_prepared_pages(prepared_pages=[first], ctx=ctx)
    assert not failures and published == [url]

    changed = _prepared_page(ctx, url=url, title="Opening hours", text="Open 9-17")
    published, failures = await _publish_prepared_pages(
        prepared_pages=[changed], ctx=ctx
    )
    assert not failures and published == [url]

    async with db_session() as session:
        previous, active = await _versions_of(session, ctx.website_id)
        assert previous.version_state == InfoBlobVersionState.SUPERSEDED.value
        assert active.version_state == InfoBlobVersionState.ACTIVE.value
        assert previous.text == "Open 8-16"
        assert await _chunk_count(session, previous.id) == 0
        assert await _chunk_count(session, active.id) == 1
        assert previous.size == len("Open 8-16".encode())
        retained = await InfoBlobRepository(session).get_retained_size_of_tenant(
            ctx.tenant_id
        )
        assert retained == previous.size + active.size


async def test_recrawl_releases_only_the_previous_version_of_the_changed_page(
    db_session,
    admin_user,
    space_factory,
) -> None:
    ctx = await _leased_crawl_context(db_session, admin_user, space_factory)
    urls = [f"https://example.com/page-{index}" for index in range(3)]
    pages = [
        _prepared_page(ctx, url=url, title=f"Page {index}", text=f"Original {index}")
        for index, url in enumerate(urls)
    ]
    published, failures = await _publish_prepared_pages(prepared_pages=pages, ctx=ctx)
    assert not failures and published == urls
    async with db_session() as session:
        before = {
            row.url: row.id for row in await _versions_of(session, ctx.website_id)
        }

    recrawl = [
        pages[0],
        _prepared_page(ctx, url=urls[1], title="Page 1", text="Changed 1"),
        pages[2],
    ]
    published, failures = await _publish_prepared_pages(prepared_pages=recrawl, ctx=ctx)
    assert not failures and published == urls

    async with db_session() as session:
        versions = await _versions_of(session, ctx.website_id)
        active = {
            row.url: row
            for row in versions
            if row.version_state == InfoBlobVersionState.ACTIVE.value
        }
        replaced = [
            row
            for row in versions
            if row.version_state == InfoBlobVersionState.SUPERSEDED.value
        ]
        # Unchanged pages keep the same version and their chunks.
        for url in (urls[0], urls[2]):
            assert active[url].id == before[url]
            assert await _chunk_count(session, active[url].id) == 1
        # The changed page has a new searchable version; only its previous
        # version lost its chunks, and it still has its text.
        assert [row.id for row in replaced] == [before[urls[1]]]
        assert replaced[0].text == "Original 1"
        assert await _chunk_count(session, replaced[0].id) == 0
        assert active[urls[1]].text == "Changed 1"
        assert await _chunk_count(session, active[urls[1]].id) == 1


async def test_upload_replacement_that_fits_after_release_is_published_at_full_quota(
    db_container,
) -> None:
    async with db_container() as container:
        group, embedding_model, _, _ = await _seed_active_document(
            container, text="Unrelated fixture", title="fixture.txt"
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))
        user = container.user()
        user.tenant.quota_limit = 1_000_000
        first = await container.text_processor().process_text(
            text="x" * 400,
            title="handbook.txt",
            embedding_model=embedding_model,
            group_id=group.id,
        )
        limit = await _fill_tenant_quota(container.session(), user.tenant_id)
        user.tenant.quota_limit = limit

        replacement = await container.text_processor().process_text(
            text="y" * 20,
            title="handbook.txt",
            embedding_model=embedding_model,
            group_id=group.id,
        )

        assert replacement.source_id == first.source_id
        historical = await container.info_blob_repo().get(first.id)
        assert historical.text == "x" * 400
        assert historical.size == 400
        retained = await container.info_blob_repo().get_retained_size_of_tenant(
            user.tenant_id
        )
        assert retained <= limit


async def test_upload_prechecks_credit_the_version_a_changed_file_replaces(
    db_container,
) -> None:
    async with db_container() as container:
        group, embedding_model, _, _ = await _seed_active_document(
            container, text="Unrelated fixture", title="fixture.txt"
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))
        user = container.user()
        user.tenant.quota_limit = 1_000_000
        async with _inline_original(
            container, b"a" * 10, filename="guide.txt"
        ) as first:
            await container.text_processor().process_text(
                text="x" * 400,
                title="guide.txt",
                embedding_model=embedding_model,
                group_id=group.id,
                original=first,
            )
        limit = await _fill_tenant_quota(container.session(), user.tenant_id)
        user.tenant.quota_limit = limit

        async with _inline_original(
            container, b"b" * 10, filename="guide.txt"
        ) as changed:
            await container.info_blob_service().precheck_knowledge_upload_capacity(
                group_id=group.id,
                title="guide.txt",
                embedding_model_id=embedding_model.id,
                original=changed,
            )
            await container.text_processor().precheck_knowledge_publication_capacity(
                text="y" * 20,
                embedding_model=embedding_model,
                title="guide.txt",
                group_id=group.id,
                original=changed,
            )
            await container.text_processor().process_text(
                text="y" * 20,
                title="guide.txt",
                embedding_model=embedding_model,
                group_id=group.id,
                original=changed,
            )

        retained = await container.info_blob_repo().get_retained_size_of_tenant(
            user.tenant_id
        )
        assert retained <= limit


async def test_citation_of_a_replaced_version_stays_readable(db_container) -> None:
    async with db_container() as container:
        group, embedding_model, _, _ = await _seed_active_document(
            container, text="Unrelated fixture", title="fixture.txt"
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))
        container.user().tenant.quota_limit = 1_000_000
        cited = await container.text_processor().process_text(
            text="Opening hours are 8-16",
            title="hours.txt",
            embedding_model=embedding_model,
            group_id=group.id,
        )
        chat = Sessions(name="Opening hours", user_id=container.user().id)
        container.session().add(chat)
        await container.session().flush()
        question = Questions(
            question="When are you open?",
            answer="8-16",
            num_tokens_question=4,
            num_tokens_answer=2,
            tenant_id=container.user().tenant_id,
            session_id=chat.id,
        )
        container.session().add(question)
        await container.session().flush()
        container.session().add(
            InfoBlobReferences(question_id=question.id, info_blob_id=cited.id)
        )
        await container.session().flush()

        await container.text_processor().process_text(
            text="Opening hours are 9-17",
            title="hours.txt",
            embedding_model=embedding_model,
            group_id=group.id,
        )

        assert await _chunk_count(container.session(), cited.id) == 0
        answered = await container.question_repo().get(question.id)
        assert answered is not None
        assert [(blob.id, blob.title) for blob in answered.info_blobs] == [
            (cited.id, "hours.txt")
        ]
        historical = await container.info_blob_repo().get(cited.id)
        assert historical.text == "Opening hours are 8-16"


async def test_failed_upload_after_release_restores_the_previous_search_data(
    db_container,
    monkeypatch,
) -> None:
    async with db_container() as container:
        group, embedding_model, _, _ = await _seed_active_document(
            container, text="Unrelated fixture", title="fixture.txt"
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = _embedding_result
        container.create_embeddings_service.override(providers.Object(embeddings))
        container.user().tenant.quota_limit = 1_000_000
        group_id = group.id
        first = await container.text_processor().process_text(
            text="Published policy",
            title="policy.txt",
            embedding_model=embedding_model,
            group_id=group_id,
        )
        first_id, first_size = first.id, first.size
        release = InfoBlobRepository.release_replaced_search_data

        async def release_then_fail(self, info_blob_ids):
            await release(self, info_blob_ids)
            raise RuntimeError("injected failure after release")

        monkeypatch.setattr(
            InfoBlobRepository, "release_replaced_search_data", release_then_fail
        )
        with pytest.raises(RuntimeError, match="injected failure after release"):
            await container.text_processor().process_text(
                text="Replacement policy",
                title="policy.txt",
                embedding_model=embedding_model,
                group_id=group_id,
            )

        active = await container.info_blob_repo().get_by_group(group_id)
        assert [blob.id for blob in active if blob.title == "policy.txt"] == [first_id]
        restored = await container.info_blob_repo().get(first_id)
        assert restored.size == first_size
        assert await _chunk_count(container.session(), first_id) == 1


async def test_crawl_rejected_at_commit_restores_the_previous_search_data(
    db_session,
    admin_user,
    space_factory,
    monkeypatch,
) -> None:
    ctx = await _leased_crawl_context(db_session, admin_user, space_factory)
    url = "https://example.com/contact"
    first = _prepared_page(ctx, url=url, title="Contact", text="x" * 40)
    published, failures = await _publish_prepared_pages(prepared_pages=[first], ctx=ctx)
    assert not failures and published == [url]
    async with db_session() as session:
        limit = await _fill_tenant_quota(session, ctx.tenant_id)
        (before,) = await _versions_of(session, ctx.website_id)
        before_id, before_size = before.id, before.size

    # Skip the preliminary check so only the commit-time check can reject.
    monkeypatch.setattr(
        "eneo.worker.crawl.persistence.ensure_quota_capacity", lambda **_: None
    )
    longer = _prepared_page(ctx, url=url, title="Contact", text="y" * 60)
    published, failures = await _publish_prepared_pages(
        prepared_pages=[longer], ctx=ctx
    )

    assert published == []
    assert list(failures) == ["TENANT_QUOTA_EXCEEDED"]
    async with db_session() as session:
        (only,) = await _versions_of(session, ctx.website_id)
        assert only.id == before_id
        assert only.version_state == InfoBlobVersionState.ACTIVE.value
        assert only.size == before_size
        assert await _chunk_count(session, before_id) == 1
        retained = await InfoBlobRepository(session).get_retained_size_of_tenant(
            ctx.tenant_id
        )
        assert retained == limit


async def test_validator_refresh_updates_several_pages_in_one_batch(
    db_session,
    admin_user,
    space_factory,
    monkeypatch,
) -> None:
    ctx = await _leased_crawl_context(db_session, admin_user, space_factory)
    urls = ["https://example.com/a", "https://example.com/b"]
    pages = [
        _prepared_page(ctx, url=url, title="Page", text=f"Content {url}")
        for url in urls
    ]
    published, failures = await _publish_prepared_pages(prepared_pages=pages, ctx=ctx)
    assert not failures and published == urls
    changed = _prepared_page(ctx, url=urls[0], title="Page", text="Changed a")
    published, failures = await _publish_prepared_pages(
        prepared_pages=[changed], ctx=ctx
    )
    assert not failures
    monkeypatch.setattr(
        "eneo.worker.crawl.persistence._require_current_publication_lease",
        AsyncMock(),
    )

    refreshed = await _refresh_http_validators(
        ctx=ctx,
        rows=[
            {"url": url, "content": "", "etag": '"v2"', "last_modified": None}
            for url in urls
        ],
    )

    assert refreshed is True
    async with db_session() as session:
        etags = {
            (row.url, row.version_state): row.http_etag
            for row in await _versions_of(session, ctx.website_id)
        }
    assert etags == {
        (urls[0], InfoBlobVersionState.SUPERSEDED.value): None,
        (urls[0], InfoBlobVersionState.ACTIVE.value): '"v2"',
        (urls[1], InfoBlobVersionState.ACTIVE.value): '"v2"',
    }


def _plan_scans(node: dict) -> list[dict]:
    children = [scan for child in node.get("Plans", []) for scan in _plan_scans(child)]
    return [node, *children] if node.get("Relation Name") else children


async def test_user_quota_query_uses_the_active_size_index_in_generic_plans(
    db_session,
    admin_user,
) -> None:
    # The application sends this statement as an asyncpg prepared statement;
    # PostgreSQL may plan it once for all parameter values (a generic plan).
    statement = (
        InfoBlobRepository(None)
        ._sum_stmt()
        .where(  # type: ignore[arg-type]
            InfoBlobs.user_id == sa.bindparam("user_id", type_=PostgreSQLUUID)
        )
    )
    compiled = statement.compile(dialect=asyncpg_dialect())
    # 'active' is part of the SQL text, so only the user is a parameter.
    assert list(compiled.positiontup or ()) == ["user_id"]
    name = f"user_quota_{uuid4().hex}"

    async with db_session() as session:
        # Plan against statistics from this test's own rows, then roll them
        # back so the shared database keeps its statistics.
        savepoint = await session.begin_nested()
        try:
            # The shape that made the quota sum expensive: a user whose
            # documents have a long history, in a tenant with more knowledge.
            colleague = Users(
                username=f"colleague-{uuid4().hex[:8]}",
                email=f"colleague-{uuid4().hex[:8]}@example.com",
                state="active",
                used_tokens=0,
                tenant_id=admin_user.tenant_id,
            )
            session.add(colleague)
            await session.flush()
            rows = [(admin_user.id, InfoBlobVersionState.ACTIVE)] * 100
            rows += [(admin_user.id, InfoBlobVersionState.SUPERSEDED)] * 2000
            rows += [(colleague.id, InfoBlobVersionState.ACTIVE)] * 2000
            session.add_all(
                InfoBlobs(
                    text="x",
                    size=1,
                    source_id=uuid4(),
                    version_state=state.value,
                    user_id=user_id,
                    tenant_id=admin_user.tenant_id,
                )
                for user_id, state in rows
            )
            await session.flush()
            connection = await session.connection()
            await connection.exec_driver_sql("ANALYZE info_blobs")
            await connection.exec_driver_sql(
                "SET LOCAL plan_cache_mode = force_generic_plan"
            )
            await connection.exec_driver_sql("SET LOCAL enable_seqscan = off")
            await connection.exec_driver_sql("SET LOCAL enable_bitmapscan = off")
            await connection.exec_driver_sql(f"PREPARE {name} AS {compiled}")
            explained = await connection.exec_driver_sql(
                f"EXPLAIN (FORMAT JSON) EXECUTE {name}('{admin_user.id}')"
            )
            # asyncpg decodes the JSON plan.
            (document,) = explained.scalar_one()
            await connection.exec_driver_sql(f"DEALLOCATE {name}")
        finally:
            await savepoint.rollback()

    # Whether PostgreSQL also skips the heap (an index-only scan) depends on
    # the visibility map, which only VACUUM maintains; the index is the point.
    scans = _plan_scans(document["Plan"])
    assert [scan.get("Index Name") for scan in scans] == [
        "ix_info_blobs_active_user_size"
    ], scans


async def _add_history_from_an_earlier_release(session, active, *, text: str):
    """A replaced version as releases before this fix left it: with chunks."""
    replaced = InfoBlobs(
        text=text,
        title=active.title,
        url=active.url,
        size=0,
        content_hash=None,
        source_id=active.source_id,
        version_state=InfoBlobVersionState.SUPERSEDED.value,
        user_id=active.user_id,
        tenant_id=active.tenant_id,
        website_id=active.website_id,
        embedding_model_id=active.embedding_model_id,
    )
    session.add(replaced)
    await session.flush()
    session.add(
        InfoBlobChunks(
            info_blob_id=replaced.id,
            tenant_id=active.tenant_id,
            chunk_no=0,
            text=text,
            size=len(text.encode()) + 12,
            embedding=[0.1, 0.2, 0.3],
        )
    )
    await session.flush()
    await session.execute(
        sa.update(InfoBlobs)
        .where(InfoBlobs.id == replaced.id)
        .values(size=2 * len(text.encode()) + 12)
    )
    return replaced.id


async def _website_with_history(db_session, admin_user, space_factory, count: int):
    ctx = await _leased_crawl_context(db_session, admin_user, space_factory)
    url = "https://example.com/history"
    page = _prepared_page(ctx, url=url, title="History", text="Current text")
    published, failures = await _publish_prepared_pages(prepared_pages=[page], ctx=ctx)
    assert not failures and published == [url]
    async with db_session() as session:
        (active,) = await _versions_of(session, ctx.website_id)
        replaced_ids = [
            await _add_history_from_an_earlier_release(
                session, active, text=f"Old text {index}"
            )
            for index in range(count)
        ]
        active_id = active.id
    return ctx, active_id, replaced_ids


async def _add_replaced_without_search_data(session, active, count: int) -> None:
    """Replaced versions that already hold no chunks, as after a cleanup."""
    session.add_all(
        InfoBlobs(
            text="Released",
            size=8,
            source_id=active.source_id,
            version_state=InfoBlobVersionState.SUPERSEDED.value,
            user_id=active.user_id,
            tenant_id=active.tenant_id,
            website_id=active.website_id,
        )
        for _ in range(count)
    )
    await session.flush()


async def test_backlog_command_releases_history_from_earlier_releases(
    db_session,
    admin_user,
    space_factory,
) -> None:
    ctx, active_id, replaced_ids = await _website_with_history(
        db_session, admin_user, space_factory, count=3
    )
    before = await scan_remaining(sessionmanager, StatusProgress(), limit=2)
    assert (before.versions_read, before.remaining_observed) == (3, 3)
    assert before.pass_complete

    result = await release_all(
        sessionmanager, CleanupProgress(), limit=2, pause_seconds=0
    )

    assert (result.versions_read, result.released_versions) == (3, 3)
    assert result.released_bytes == sum(
        len(f"Old text {i}".encode()) + 12 for i in range(3)
    )
    assert (result.skipped_busy, result.pass_complete) == (0, True)
    async with db_session() as session:
        last_id = await session.scalar(
            sa.select(InfoBlobs.id).order_by(InfoBlobs.id.desc()).limit(1)
        )
    assert result.last_confirmed_id == last_id
    async with db_session() as session:
        for index, replaced_id in enumerate(replaced_ids):
            assert await _chunk_count(session, replaced_id) == 0
            replaced = await session.get(InfoBlobs, replaced_id)
            assert replaced is not None
            assert replaced.text == f"Old text {index}"
            assert replaced.size == len(f"Old text {index}".encode())
        assert await _chunk_count(session, active_id) == 1

    rerun = await release_all(
        sessionmanager, CleanupProgress(), limit=2, pause_seconds=0
    )
    assert (rerun.released_versions, rerun.pass_complete) == (0, True)
    after = await scan_remaining(sessionmanager, StatusProgress(), limit=2)
    assert (after.remaining_observed, after.pass_complete) == (0, True)


async def _add_active_without_search_data(session, active, ids) -> None:
    """Active versions of other pages, at chosen positions in the id order."""
    session.add_all(
        InfoBlobs(
            id=id_,
            text="Other page",
            size=10,
            source_id=uuid4(),
            version_state=InfoBlobVersionState.ACTIVE.value,
            user_id=active.user_id,
            tenant_id=active.tenant_id,
            website_id=active.website_id,
        )
        for id_ in ids
    )
    await session.flush()


async def test_backlog_pages_are_bounded_by_versions_read(
    db_session,
    admin_user,
    space_factory,
    monkeypatch,
) -> None:
    _, active_id, _ = await _website_with_history(
        db_session, admin_user, space_factory, count=2
    )
    async with db_session() as session:
        active = await session.get(InfoBlobs, active_id)
        assert active is not None
        await _add_replaced_without_search_data(session, active, count=12)
        # Long runs of active versions at both ends of the id order, where a
        # page filtered by state would have to read on until the next match.
        await _add_active_without_search_data(
            session,
            active,
            [UUID(int=n) for n in range(1, 21)]
            + [UUID(int=2**128 - n) for n in range(1, 21)],
        )
        total = await session.scalar(sa.select(sa.func.count()).select_from(InfoBlobs))
    scans: list[int] = []
    pauses: list[float] = []
    original_scan = InfoBlobRepository.scan_replaced_page
    original_sleep = asyncio.sleep
    pause = 0.0125

    async def recording_scan(self, *, after, limit):
        page = await original_scan(self, after=after, limit=limit)
        scans.append(len(page.with_search_data))
        return page

    async def recording_sleep(delay, *args, **kwargs):
        if 0 < delay <= pause:
            pauses.append(delay)
        return await original_sleep(delay, *args, **kwargs)

    monkeypatch.setattr(InfoBlobRepository, "scan_replaced_page", recording_scan)
    monkeypatch.setattr(asyncio, "sleep", recording_sleep)

    status = await scan_remaining(sessionmanager, StatusProgress(), limit=4)
    status_scans = len(scans)
    result = await release_all(
        sessionmanager, CleanupProgress(), limit=4, pause_seconds=pause
    )

    # Every page reads four versions of any state, plus one empty page that
    # ends the walk, so the number of pages follows from the table size.
    assert status_scans == len(scans) - status_scans == math.ceil(total / 4) + 1
    assert (status.versions_read, status.remaining_observed) == (14, 2)
    assert (result.versions_read, result.released_versions) == (14, 2)
    assert status.pass_complete and result.pass_complete
    # Pauses follow the releases: a full page would wait `pause`.
    assert sum(pauses) == pytest.approx(pause * result.released_versions / 4)


async def test_backlog_command_skips_versions_another_transaction_holds(
    db_session,
    admin_user,
    space_factory,
) -> None:
    _, _, replaced_ids = await _website_with_history(
        db_session, admin_user, space_factory, count=2
    )
    busy_id = min(replaced_ids)

    async with db_session() as holder:
        await holder.execute(
            sa.select(InfoBlobs.id).where(InfoBlobs.id == busy_id).with_for_update()
        )
        payload, exit_code = await _execute("run", sessionmanager)

    assert exit_code == 2
    assert payload["released_versions"] == 1
    assert payload["skipped_busy"] == 1
    assert payload["pass_complete"] is True
    payload, exit_code = await _execute("run", sessionmanager)
    assert (exit_code, payload["released_versions"]) == (0, 1)


async def test_backlog_command_counts_only_versions_it_released(
    db_session,
    admin_user,
    space_factory,
    monkeypatch,
) -> None:
    _, _, replaced_ids = await _website_with_history(
        db_session, admin_user, space_factory, count=2
    )
    async with db_session() as session:
        await InfoBlobRepository(session).release_replaced_search_data(
            [replaced_ids[0]]
        )
    original = InfoBlobRepository.scan_replaced_page

    async def stale_scan(self, *, after, limit):
        # As if a concurrent run released that version after this one read it.
        page = await original(self, after=after, limit=limit)
        if page.last_id is None:
            return page
        return ReplacedPage(
            page.last_id,
            page.versions_read,
            sorted({*page.with_search_data, replaced_ids[0]}),
        )

    monkeypatch.setattr(InfoBlobRepository, "scan_replaced_page", stale_scan)

    result = await release_all(
        sessionmanager, CleanupProgress(), limit=10, pause_seconds=0
    )

    assert (result.released_versions, result.skipped_busy) == (1, 0)


@pytest.mark.parametrize(
    "stop",
    [RuntimeError("injected failure"), asyncio.CancelledError()],
    ids=["failure", "ctrl-c-or-sigterm"],
)
async def test_backlog_run_keeps_committed_batches_when_a_later_batch_stops(
    db_session,
    admin_user,
    space_factory,
    monkeypatch,
    stop,
) -> None:
    _, _, replaced_ids = await _website_with_history(
        db_session, admin_user, space_factory, count=2
    )
    first, second = sorted(replaced_ids)
    monkeypatch.setattr(replaced_versions, "BATCH_SIZE", 1)
    monkeypatch.setattr(replaced_versions, "PAUSE_SECONDS", 0)
    release = InfoBlobRepository.release_replaced_search_data
    calls = 0

    async def fail_the_second_batch(self, info_blob_ids):
        nonlocal calls
        calls += 1
        released = await release(self, info_blob_ids)
        if calls == 2:
            raise stop
        return released

    monkeypatch.setattr(
        InfoBlobRepository, "release_replaced_search_data", fail_the_second_batch
    )

    payload, exit_code = await _execute("run", sessionmanager)

    assert exit_code == 3
    assert payload["outcome"] == "incomplete"
    assert payload["released_versions"] == 1
    assert payload["pass_complete"] is False
    # The cursor stops at the last committed page, before the failed one; the
    # active version may sit between the two replaced ones in id order.
    assert first <= UUID(payload["last_confirmed_id"]) < second
    async with db_session() as session:
        assert await _chunk_count(session, first) == 0
        assert await _chunk_count(session, second) == 1


async def test_backlog_run_does_not_depend_on_the_status_walk(
    db_session,
    admin_user,
    space_factory,
    monkeypatch,
) -> None:
    await _website_with_history(db_session, admin_user, space_factory, count=1)

    async def unavailable(*args, **kwargs):
        raise sa.exc.OperationalError("count", {}, Exception("statement timeout"))

    monkeypatch.setattr(replaced_versions, "scan_remaining", unavailable)

    payload, exit_code = await _execute("run", sessionmanager)

    assert (exit_code, payload["released_versions"]) == (0, 1)
    assert payload["pass_complete"] is True


async def test_backlog_commands_report_a_locked_table_instead_of_waiting(
    db_session,
) -> None:
    async with db_session() as holder:
        await holder.execute(sa.text("LOCK TABLE info_blobs IN ACCESS EXCLUSIVE MODE"))
        status, status_exit = await asyncio.wait_for(
            _execute("status", sessionmanager), timeout=15
        )
        run, run_exit = await asyncio.wait_for(
            _execute("run", sessionmanager), timeout=15
        )

    assert (status_exit, status["outcome"], status["pass_complete"]) == (
        3,
        "inconclusive",
        False,
    )
    assert (run_exit, run["outcome"], run["released_versions"]) == (
        3,
        "incomplete",
        0,
    )


async def test_backlog_transactions_set_their_own_limits(db_session) -> None:
    settings = (
        "lock_timeout",
        "statement_timeout",
        "max_parallel_workers_per_gather",
    )
    async with replaced_versions._bounded(sessionmanager) as repo:
        inside = [
            await repo.session.scalar(sa.text(f"SHOW {name}")) for name in settings
        ]
    async with db_session() as session:
        outside = [await session.scalar(sa.text(f"SHOW {name}")) for name in settings]

    assert inside == ["2s", "1min", "0"]
    assert outside[2] != "0"
    assert outside[:2] != inside[:2]


@pytest.mark.parametrize(
    "stop",
    [RuntimeError("injected failure"), asyncio.CancelledError()],
    ids=["failure", "ctrl-c-or-sigterm"],
)
async def test_backlog_result_survives_a_stop_while_closing_the_database(
    monkeypatch,
    stop,
) -> None:
    sigterm_while_closing = []

    class Database:
        def init(self, url):
            pass

        async def close(self):
            sigterm_while_closing.append(signal.getsignal(signal.SIGTERM))
            raise stop

    async def finished(command, database):
        return {"pass_complete": True}, 0

    monkeypatch.setattr("eneo.database.database.DatabaseSessionManager", Database)
    monkeypatch.setattr(replaced_versions, "_execute", finished)

    assert await replaced_versions._run("run") == ({"pass_complete": True}, 0)
    # SIGTERM still reaches the command while it closes, and not after.
    assert sigterm_while_closing[0] not in (signal.SIG_DFL, signal.SIG_IGN)
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL


async def test_backlog_release_keeps_the_recorded_size_of_legacy_crawled_pages(
    db_session,
    admin_user,
    space_factory,
) -> None:
    # The 2.1 crawler recorded a page's size as its text and chunk sizes
    # without embedding bytes; releasing its chunks leaves that size alone.
    ctx, _, _ = await _website_with_history(
        db_session, admin_user, space_factory, count=0
    )
    text = "Legacy page"
    async with db_session() as session:
        (active,) = await _versions_of(session, ctx.website_id)
        legacy = InfoBlobs(
            text=text,
            size=len(text.encode()),
            source_id=active.source_id,
            version_state=InfoBlobVersionState.SUPERSEDED.value,
            user_id=active.user_id,
            tenant_id=active.tenant_id,
            website_id=active.website_id,
        )
        session.add(legacy)
        await session.flush()
        session.add(
            InfoBlobChunks(
                info_blob_id=legacy.id,
                tenant_id=active.tenant_id,
                chunk_no=0,
                text=text,
                size=len(text.encode()),
                embedding=[0.1, 0.2, 0.3],
            )
        )
        legacy_id = legacy.id

    result = await release_all(
        sessionmanager, CleanupProgress(), limit=10, pause_seconds=0
    )

    assert (result.released_versions, result.released_bytes) == (1, len(text.encode()))
    async with db_session() as session:
        assert await _chunk_count(session, legacy_id) == 0
        released = await session.get(InfoBlobs, legacy_id)
        assert released is not None
        assert released.size == len(text.encode())


async def _fill_tenant_quota(session, tenant_id) -> int:
    retained = await InfoBlobRepository(session).get_retained_size_of_tenant(tenant_id)
    await session.execute(
        sa.update(Tenants).where(Tenants.id == tenant_id).values(quota_limit=retained)
    )
    return retained


async def test_crawl_replacement_that_fits_after_release_is_published_at_full_quota(
    db_session,
    admin_user,
    space_factory,
) -> None:
    ctx = await _leased_crawl_context(db_session, admin_user, space_factory)
    url = "https://example.com/news"
    first = _prepared_page(ctx, url=url, title="News", text="x" * 40)
    published, failures = await _publish_prepared_pages(prepared_pages=[first], ctx=ctx)
    assert not failures and published == [url]
    async with db_session() as session:
        limit = await _fill_tenant_quota(session, ctx.tenant_id)

    # 20 bytes of text plus a 32-byte chunk replace a 52-byte chunk: the
    # tenant ends at its limit, so the replacement fits.
    shorter = _prepared_page(ctx, url=url, title="News", text="y" * 20)
    published, failures = await _publish_prepared_pages(
        prepared_pages=[shorter], ctx=ctx
    )

    assert not failures and published == [url]
    async with db_session() as session:
        retained = await InfoBlobRepository(session).get_retained_size_of_tenant(
            ctx.tenant_id
        )
        assert retained == limit


async def test_crawl_replacement_over_quota_keeps_the_previous_version_searchable(
    db_session,
    admin_user,
    space_factory,
) -> None:
    ctx = await _leased_crawl_context(db_session, admin_user, space_factory)
    url = "https://example.com/events"
    first = _prepared_page(ctx, url=url, title="Events", text="x" * 40)
    published, failures = await _publish_prepared_pages(prepared_pages=[first], ctx=ctx)
    assert not failures and published == [url]
    async with db_session() as session:
        limit = await _fill_tenant_quota(session, ctx.tenant_id)

    longer = _prepared_page(ctx, url=url, title="Events", text="y" * 60)
    published, failures = await _publish_prepared_pages(
        prepared_pages=[longer], ctx=ctx
    )

    assert published == []
    assert list(failures) == ["TENANT_QUOTA_EXCEEDED"]
    async with db_session() as session:
        (only,) = await _versions_of(session, ctx.website_id)
        assert only.version_state == InfoBlobVersionState.ACTIVE.value
        assert only.text == "x" * 40
        assert await _chunk_count(session, only.id) == 1
        retained = await InfoBlobRepository(session).get_retained_size_of_tenant(
            ctx.tenant_id
        )
        assert retained == limit
