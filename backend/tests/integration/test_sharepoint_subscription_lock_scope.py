"""The subscription lock never outlives ensure_subscription_for_site."""

import asyncio
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.integration_table import (
    IntegrationKnowledge as IntegrationKnowledgeDB,
)
from eneo.integration.infrastructure.sharepoint_subscription_service import (
    SharePointSubscriptionService,
)
from tests.integration.test_sharepoint_subscription_ensure_race import _connection
from tests.integration.test_sharepoint_sync_catch_up import _source

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("sharepoint_webhook_configured"),
]

TOKEN = MagicMock(access_token="token", base_url="https://graph")


@pytest.fixture
def graph():
    created: list[str] = []

    async def create_at_graph(**_kwargs) -> str:
        created.append(f"graph-{len(created)}")
        return created[-1]

    with (
        patch.object(
            SharePointSubscriptionService,
            "_create_graph_subscription",
            side_effect=create_at_graph,
        ),
        patch.object(
            SharePointSubscriptionService, "_resolve_drive_id", return_value="drive-1"
        ),
        patch.object(
            SharePointSubscriptionService,
            "_delete_graph_subscription",
            return_value=True,
        ),
    ):
        yield created


async def _ensure(container, connection_id: UUID, site: str):
    return (
        await container.sharepoint_subscription_service().ensure_subscription_for_site(
            user_integration_id=connection_id, site_id=site, token=TOKEN
        )
    )


async def test_an_import_waits_for_no_open_request_on_the_same_site(
    db_container, graph
):
    """A resync whose request is still open (its link waiting on a running
    sync, say) must not hold up an import of another folder on the site."""
    connection_id = await _connection(db_container)
    release = asyncio.Event()
    ensured = asyncio.Event()

    async def resync_left_open() -> None:
        async with db_container() as container:
            await _ensure(container, connection_id, "site-a")
            ensured.set()
            await release.wait()

    holder = asyncio.create_task(resync_left_open())
    try:
        await asyncio.wait_for(ensured.wait(), timeout=10)
        async with db_container() as container:
            subscription = await asyncio.wait_for(
                _ensure(container, connection_id, "site-a"), timeout=10
            )
    finally:
        release.set()
        await holder

    assert subscription is not None
    assert graph == ["graph-0"]


async def test_batches_over_two_sites_in_opposite_order_do_not_deadlock(
    db_container, graph
):
    connection_id = await _connection(db_container)
    both_started = asyncio.Barrier(2)

    async def batch(sites: list[str]) -> None:
        async with db_container() as container:
            await _ensure(container, connection_id, sites[0])
            await both_started.wait()
            await _ensure(container, connection_id, sites[1])

    await asyncio.wait_for(
        asyncio.gather(batch(["site-a", "site-b"]), batch(["site-b", "site-a"])),
        timeout=20,
    )

    assert sorted(graph) == ["graph-0", "graph-1"]


async def test_linking_a_row_a_sync_holds_does_not_wait(db_container):
    async with db_container() as container:
        knowledge_id = await _source(container)
        subscription_id = uuid4()

    async with sessionmanager.session() as sync, sync.begin():
        await sync.execute(
            sa.update(IntegrationKnowledgeDB)
            .where(IntegrationKnowledgeDB.id == knowledge_id)
            .values(last_sync_status="success")
        )
        async with db_container() as container:
            linked = await asyncio.wait_for(
                container.integration_knowledge_repo().link_subscription(
                    knowledge_id, subscription_id
                ),
                timeout=10,
            )

    assert linked is False


async def test_the_renewals_link_skips_a_row_a_sync_holds(db_container):
    from datetime import datetime, timedelta, timezone

    from eneo.database.tables.sharepoint_subscription_table import (
        SharePointSubscription as SubscriptionDB,
    )
    from eneo.integration.infrastructure.mappers.sharepoint_subscription_mapper import (
        SharePointSubscriptionMapper,
    )

    async with db_container() as container:
        syncing = await _source(container)
        idle = await _source(container)
        session = container.session()
        connections = dict(
            (
                await session.execute(
                    sa.select(
                        IntegrationKnowledgeDB.id,
                        IntegrationKnowledgeDB.user_integration_id,
                    ).where(IntegrationKnowledgeDB.id.in_([syncing, idle]))
                )
            ).all()
        )
        subscriptions = []
        for knowledge_id in (syncing, idle):
            row = SubscriptionDB(
                user_integration_id=connections[knowledge_id],
                site_id="site-1",
                subscription_id=f"graph-{knowledge_id}",
                drive_id="drive-1",
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
            session.add(row)
            await session.flush()
            subscriptions.append(SharePointSubscriptionMapper().to_entity(row))

    async with sessionmanager.session() as sync, sync.begin():
        await sync.execute(
            sa.update(IntegrationKnowledgeDB)
            .where(IntegrationKnowledgeDB.id == syncing)
            .values(last_sync_status="success")
        )
        async with db_container() as container:
            repo = container.sharepoint_subscription_repo()
            linked = [
                await asyncio.wait_for(
                    repo.link_unreferenced_knowledge(subscription), timeout=10
                )
                for subscription in subscriptions
            ]

    assert linked == [0, 1]
