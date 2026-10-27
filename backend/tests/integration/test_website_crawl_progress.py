"""The running crawls of the websites a space shows: what the websites tab polls
while a crawl runs, instead of the whole space."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.spaces_table import SpacesUsers
from eneo.database.tables.websites_spaces_table import WebsitesSpaces
from eneo.database.tables.websites_table import CrawlAttempts, CrawlRuns, Websites
from eneo.websites.domain.crawl_run import CrawlOrigin, CrawlPhase, CrawlType

pytestmark = pytest.mark.integration


async def _website(session, admin_user, space_id: UUID, name: str) -> UUID:
    model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
    website = Websites(
        name=name,
        url=f"https://{uuid4().hex[:8]}.example.test",
        size=0,
        download_files=False,
        crawl_type=CrawlType.CRAWL,
        update_interval="never",
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        space_id=space_id,
        embedding_model_id=model_id,
    )
    session.add(website)
    await session.flush()
    return website.id


async def _finished_run(
    session, admin_user, website_id: UUID, created_at: datetime
) -> UUID:
    run_id = uuid4()
    session.add(
        CrawlRuns(
            id=run_id,
            website_id=website_id,
            tenant_id=admin_user.tenant_id,
            created_at=created_at,
            phase=CrawlPhase.TERMINAL.value,
            outcome="succeeded",
            finished_at=created_at,
            origin=CrawlOrigin.MANUAL.value,
        )
    )
    await session.flush()
    return run_id


async def _running_run(session, admin_user, website_id: UUID, pages: int) -> UUID:
    job = Jobs(user_id=admin_user.id, task="crawl", status="in progress", name="Crawl")
    session.add(job)
    await session.flush()
    run_id = uuid4()
    session.add(
        CrawlRuns(
            id=run_id,
            tenant_id=admin_user.tenant_id,
            website_id=website_id,
            job_id=job.id,
            phase=CrawlPhase.RUNNING.value,
            origin=CrawlOrigin.MANUAL.value,
            attempt_count=1,
            pages_crawled=pages,
        )
    )
    await session.flush()
    session.add(
        CrawlAttempts(
            crawl_run_id=run_id,
            attempt_number=1,
            dispatch_id=job.id,
            dispatch_payload={},
        )
    )
    await session.flush()
    return run_id


@pytest.fixture
async def headers(db_container, admin_user, patch_auth_service_jwt):
    async with db_container(user=admin_user) as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def space_id(db_container, admin_user, space_factory) -> UUID:
    async with db_container(user=admin_user) as container:
        session = container.session()
        space = await space_factory(session, f"Crawl progress {uuid4()}")
        session.add(
            SpacesUsers(space_id=space.id, user_id=admin_user.id, role="editor")
        )
        await session.flush()
        return space.id


def _url(space_id: UUID) -> str:
    return f"/api/v1/spaces/{space_id}/knowledge/websites/crawl-progress/"


async def test_lists_only_the_running_latest_crawls_without_loading_the_space(
    client, db_container, admin_user, space_id, headers, monkeypatch
) -> None:
    from eneo.spaces.space_repo import SpaceRepository

    async def forbid_aggregate(*args, **kwargs):
        pytest.fail("Polling crawl progress must not build the space aggregate")

    now = datetime.now(timezone.utc)
    async with db_container(user=admin_user) as container:
        session = container.session()
        running = await _website(session, admin_user, space_id, "Running")
        await _finished_run(session, admin_user, running, now - timedelta(days=1))
        running_run = await _running_run(session, admin_user, running, pages=7)
        idle = await _website(session, admin_user, space_id, "Idle")
        await _finished_run(session, admin_user, idle, now)
        await _website(session, admin_user, space_id, "Never crawled")

    monkeypatch.setattr(SpaceRepository, "_get_from_query", forbid_aggregate)
    response = await client.get(_url(space_id), headers=headers)

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [(item["website_id"], item["latest_crawl"]["id"]) for item in items] == [
        (str(running), str(running_run))
    ]
    assert items[0]["latest_crawl"]["phase"] == "running"
    assert items[0]["latest_crawl"]["pages_crawled"] == 7


async def test_includes_a_website_distributed_to_the_space_from_one_the_caller_cannot_read(
    client, db_container, admin_user, space_id, space_factory, headers
) -> None:
    async with db_container(user=admin_user) as container:
        session = container.session()
        owner = await space_factory(session, f"Owner {uuid4()}")
        shared = await _website(session, admin_user, owner.id, "Shared")
        session.add(WebsitesSpaces(website_id=shared, space_id=space_id))
        await session.flush()
        run_id = await _running_run(session, admin_user, shared, pages=3)

    # The space shows the website, so its running crawl is listed with it, as
    # the space itself would list it; the owning space is not this caller's.
    response = await client.get(_url(space_id), headers=headers)
    assert response.status_code == 200, response.text
    assert [item["latest_crawl"]["id"] for item in response.json()["items"]] == [
        str(run_id)
    ]
    space = await client.get(f"/api/v1/spaces/{space_id}/", headers=headers)
    shown = space.json()["knowledge"]["websites"]["items"]
    assert [website["latest_crawl"]["id"] for website in shown] == [str(run_id)]


async def test_follows_the_space_reads_refusals_and_website_visibility(
    client, db_container, admin_user, space_id, headers
) -> None:
    async with db_container(user=admin_user) as container:
        session = container.session()
        website = await _website(session, admin_user, space_id, "Running")
        await _running_run(session, admin_user, website, pages=1)

    # A viewer sees the space but no websites in it, so no crawls either.
    async with db_container(user=admin_user) as container:
        await container.session().execute(
            sa.update(SpacesUsers)
            .where(SpacesUsers.space_id == space_id)
            .values(role="viewer")
        )
    space = await client.get(f"/api/v1/spaces/{space_id}/", headers=headers)
    assert space.status_code == 200, space.text
    assert space.json()["knowledge"]["websites"]["items"] == []
    response = await client.get(_url(space_id), headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"items": []}

    # Not a member: refused like the space itself; an unknown space is not found.
    async with db_container(user=admin_user) as container:
        await container.session().execute(
            sa.delete(SpacesUsers).where(SpacesUsers.space_id == space_id)
        )
    space = await client.get(f"/api/v1/spaces/{space_id}/", headers=headers)
    response = await client.get(_url(space_id), headers=headers)
    assert response.status_code == space.status_code == 403, response.text
    unknown = await client.get(_url(uuid4()), headers=headers)
    assert unknown.status_code == 404, unknown.text


async def test_reads_a_fixed_number_of_statements_however_many_crawls_run(
    client, db_container, admin_user, space_id, headers
) -> None:
    async def statements_for(count: int) -> int:
        async with db_container(user=admin_user) as container:
            session = container.session()
            for n in range(count):
                website = await _website(session, admin_user, space_id, f"Site {n}")
                await _running_run(session, admin_user, website, pages=n)
            engine = session.bind
        sync_engine = getattr(engine, "sync_engine", engine)
        executed = 0

        def count_statement(*_args, **_kwargs):
            nonlocal executed
            executed += 1

        sa.event.listen(sync_engine, "before_cursor_execute", count_statement)
        try:
            response = await client.get(_url(space_id), headers=headers)
        finally:
            sa.event.remove(sync_engine, "before_cursor_execute", count_statement)
        assert response.status_code == 200, response.text
        return executed

    one = await statements_for(1)
    many = await statements_for(9)
    assert many == one
