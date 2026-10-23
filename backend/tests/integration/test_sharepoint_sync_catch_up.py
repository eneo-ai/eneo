"""Which SharePoint sources the periodic catch-up may queue a sync for."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.database.database import sessionmanager
from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.integration_table import (
    Integration as IntegrationDB,
)
from eneo.database.tables.integration_table import (
    IntegrationKnowledge as IntegrationKnowledgeDB,
)
from eneo.database.tables.integration_table import (
    OauthToken as OauthTokenDB,
)
from eneo.database.tables.integration_table import (
    TenantIntegration as TenantIntegrationDB,
)
from eneo.database.tables.integration_table import (
    UserIntegration as UserIntegrationDB,
)
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_sharepoint_app_table import TenantSharePointApp
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)
from eneo.integration.infrastructure.sharepoint_sync_keys import (
    sync_catch_up_key,
    sync_pending_full_key,
    sync_queued_key,
)
from eneo.main.container.container import Container

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("sharepoint_webhook_configured"),
]

STALE = datetime.now(timezone.utc) - timedelta(hours=30)


class _Dispatches:
    """Jobs handed to the worker; they are handed over only after a commit."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID]] = []
        self._changed = asyncio.Event()

    async def record(self, task, _job_id, params) -> None:
        self.calls.append((task.value, params.integration_knowledge_id))
        self._changed.set()

    async def wait_for(self, count: int) -> None:
        async def reached() -> None:
            while len(self.calls) < count:
                self._changed.clear()
                await self._changed.wait()

        await asyncio.wait_for(reached(), timeout=5)


@pytest.fixture
def dispatches(monkeypatch) -> _Dispatches:
    recorder = _Dispatches()
    monkeypatch.setattr("eneo.jobs.job_service.job_manager.enqueue", recorder.record)
    return recorder


async def _space_and_model(container) -> tuple[UUID, UUID]:
    session = container.session()
    user = container.user()
    space_id = await session.scalar(
        sa.select(Spaces.id).where(Spaces.user_id == user.id).limit(1)
    )
    if space_id is None:
        space = Spaces(
            name=f"catch-up-{uuid4()}", tenant_id=user.tenant_id, user_id=user.id
        )
        session.add(space)
        await session.flush()
        space_id = space.id
    model = EmbeddingModels(
        name=f"catch-up-embedding-{uuid4()}",
        open_source=False,
        family="openai",
        stability="stable",
        hosting="usa",
        dimensions=1536,
        max_input=8192,
    )
    session.add(model)
    await session.flush()
    return space_id, model.id


async def _source(
    container,
    *,
    integration_type: str = "sharepoint",
    auth_type: str = "user_oauth",
    authenticated: bool = True,
    tenant_app_id: UUID | None = None,
    site_id: str | None = "site-1",
) -> UUID:
    session = container.session()
    user = container.user()
    integration = IntegrationDB(
        name=f"catch-up-{uuid4()}",
        description="catch-up test",
        integration_type=integration_type,
    )
    session.add(integration)
    await session.flush()
    tenant_integration = TenantIntegrationDB(
        tenant_id=user.tenant_id, integration_id=integration.id
    )
    session.add(tenant_integration)
    await session.flush()
    connection = UserIntegrationDB(
        user_id=user.id if auth_type == "user_oauth" else None,
        tenant_id=user.tenant_id,
        tenant_integration_id=tenant_integration.id,
        authenticated=authenticated,
        auth_type=auth_type,
        tenant_app_id=tenant_app_id,
    )
    session.add(connection)
    await session.flush()
    if auth_type == "user_oauth":
        session.add(
            OauthTokenDB(
                access_token="access",
                token_type="sharepoint",
                refresh_token="refresh",
                resources={},
                user_integration_id=connection.id,
            )
        )
        await session.flush()
    space_id, model_id = await _space_and_model(container)
    knowledge = IntegrationKnowledgeDB(
        name="Library",
        space_id=space_id,
        embedding_model_id=model_id,
        tenant_id=user.tenant_id,
        user_integration_id=connection.id,
        site_id=site_id,
        delta_token="token",
        last_synced_at=STALE,
        last_sync_attempted_at=STALE,
    )
    session.add(knowledge)
    await session.flush()
    return knowledge.id


async def _tenant_app(
    container,
    *,
    active: bool,
    failed_at: datetime | None = None,
    succeeded_at: datetime | None = None,
) -> UUID:
    session = container.session()
    user = container.user()
    app = TenantSharePointApp(
        id=uuid4(),
        tenant_id=user.tenant_id,
        client_id="client",
        client_secret_encrypted="secret",
        tenant_domain="contoso.onmicrosoft.com",
        is_active=active,
        created_by=user.id,
        last_auth_error="AADSTS7000222: the client secret has expired"
        if failed_at
        else None,
        last_auth_error_at=failed_at,
        last_auth_success_at=succeeded_at,
    )
    session.add(app)
    await session.flush()
    return app.id


async def _candidate_ids(container) -> set[UUID]:
    service = container.sharepoint_webhook_service()
    return {c.id for c in await service._catch_up_candidates()}  # pyright: ignore[reportPrivateUsage]


async def test_only_sources_that_can_still_sync_are_candidates(db_container):
    async with db_container() as container:
        personal = await _source(container)
        unauthenticated = await _source(container, authenticated=False)
        no_resource = await _source(container, site_id=None)
        confluence = await _source(container, integration_type="confluence")
        organization = await _source(
            container,
            auth_type="tenant_app",
            tenant_app_id=await _tenant_app(container, active=True),
        )

        candidates = await _candidate_ids(container)

    assert personal in candidates
    assert organization in candidates
    assert unauthenticated not in candidates
    assert no_resource not in candidates
    assert confluence not in candidates


async def test_an_inactive_tenant_app_is_not_a_candidate(db_container):
    async with db_container() as container:
        organization = await _source(
            container,
            auth_type="tenant_app",
            tenant_app_id=await _tenant_app(container, active=False),
        )
        orphaned = await _source(container, auth_type="tenant_app")

        candidates = await _candidate_ids(container)

    assert organization not in candidates
    assert orphaned not in candidates


@pytest.mark.parametrize("change", ["deleted", "inactive"])
async def test_a_connection_whose_owner_cannot_sign_in_is_not_a_candidate(
    db_container, change
):
    async with db_container() as container:
        personal = await _source(container)
        values = (
            {"deleted_at": datetime.now(timezone.utc)}
            if change == "deleted"
            else {"state": "inactive"}
        )
        await container.session().execute(
            sa.update(Users).where(Users.id == container.user().id).values(**values)
        )

        candidates = await _candidate_ids(container)

    assert personal not in candidates


async def _subscribe(container, knowledge_id: UUID) -> SharePointSubscription:
    from eneo.database.tables.sharepoint_subscription_table import (
        SharePointSubscription as SubscriptionDB,
    )

    session = container.session()
    connection_id = await session.scalar(
        sa.select(IntegrationKnowledgeDB.user_integration_id).where(
            IntegrationKnowledgeDB.id == knowledge_id
        )
    )
    subscription = SubscriptionDB(
        user_integration_id=connection_id,
        site_id="site-1",
        subscription_id=f"graph-{uuid4()}",
        drive_id="drive-1",
        expires_at=datetime.now(timezone.utc) + timedelta(days=10),
    )
    session.add(subscription)
    await session.flush()
    await session.execute(
        sa.update(IntegrationKnowledgeDB)
        .where(IntegrationKnowledgeDB.id == knowledge_id)
        .values(sharepoint_subscription_id=subscription.id)
    )
    return SharePointSubscription(
        id=subscription.id,
        user_integration_id=subscription.user_integration_id,
        site_id=subscription.site_id,
        subscription_id=subscription.subscription_id,
        drive_id=subscription.drive_id,
        expires_at=subscription.expires_at,
    )


async def _queue_by_path(container, path: str, knowledge_id: UUID) -> int:
    """Queue a sync the way one path does; how many it queued."""
    service = container.sharepoint_webhook_service()
    if path == "follow-up":
        return int(await service.queue_sync_for_knowledge(knowledge_id) is not None)
    subscription = await _subscribe(container, knowledge_id)
    if path == "missed-notifications":
        return await service.queue_syncs_for_subscription(subscription)
    jobs = sa.select(sa.func.count()).select_from(Jobs)
    before = await container.session().scalar(jobs)
    await service._queue_refresh_for_subscription(  # pyright: ignore[reportPrivateUsage]
        subscription, [{"resourceData": {"id": f"item-{uuid4()}"}}]
    )
    return await container.session().scalar(jobs) - before


@pytest.mark.parametrize("path", ["notification", "missed-notifications", "follow-up"])
@pytest.mark.parametrize("owner", ["active", "deleted", "inactive"])
async def test_no_path_queues_a_sync_for_an_owner_who_cannot_sign_in(
    db_container, redis_client, path, owner
):
    """The catch-up rule above holds for every other path that queues a sync."""
    async with db_container() as container:
        personal = await _source(container)
        if owner != "active":
            values = (
                {"deleted_at": datetime.now(timezone.utc)}
                if owner == "deleted"
                else {"state": "inactive"}
            )
            await container.session().execute(
                sa.update(Users).where(Users.id == container.user().id).values(**values)
            )
        try:
            queued = await _queue_by_path(container, path, personal)
        finally:
            await redis_client.delete(sync_queued_key(str(personal)))

    assert queued == (1 if owner == "active" else 0)


async def test_a_suspended_tenant_has_no_candidates(db_container):
    async with db_container() as container:
        personal = await _source(container)
        await container.session().execute(
            sa.update(Tenants)
            .where(Tenants.id == container.user().tenant_id)
            .values(state="suspended")
        )

        candidates = await _candidate_ids(container)

    assert personal not in candidates


async def test_last_activity_is_the_latest_attempt_or_success(db_container):
    recent = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with db_container() as container:
        personal = await _source(container)
        await container.session().execute(
            sa.update(IntegrationKnowledgeDB)
            .where(IntegrationKnowledgeDB.id == personal)
            .values(last_sync_attempted_at=recent)
        )
        service = container.sharepoint_webhook_service()

        [candidate] = [
            c
            for c in await service._catch_up_candidates()  # pyright: ignore[reportPrivateUsage]
            if c.id == personal
        ]

    assert abs((candidate.last_activity - recent).total_seconds()) < 1
    assert candidate.has_delta_token is True


async def test_a_stale_source_gets_one_delta_job_per_window(
    db_container, redis_client, dispatches
):
    stale_before = datetime.now(timezone.utc) - timedelta(hours=6)
    async with db_container() as container:
        personal = await _source(container)
    try:
        for _ in range(2):
            # As the cron runs it: a session with no transaction open.
            async with sessionmanager.session() as session:
                container = Container(session=providers.Object(session))
                summary = (
                    await container.sharepoint_webhook_service().queue_catch_up_syncs(
                        stale_before=stale_before, limit=25, window_seconds=3600
                    )
                )
            await dispatches.wait_for(1)
            # The first run's job has not started, and the window holds after.
            await redis_client.delete(sync_queued_key(str(personal)))
        async with db_container() as container:
            tasks = (
                await container.session().scalars(
                    sa.select(Jobs.task).where(Jobs.task == "sync_sharepoint_delta")
                )
            ).all()
    finally:
        await redis_client.delete(
            sync_queued_key(str(personal)), sync_catch_up_key(str(personal))
        )

    assert summary["queued"] == 0
    assert tasks == ["sync_sharepoint_delta"]
    assert dispatches.calls == [("sync_sharepoint_delta", personal)]


async def test_a_follow_up_queues_the_sync_its_markers_ask_for(
    db_container, redis_client, dispatches
):
    """What a lease holder does once its lease is released: read the markers,
    queue the sync they ask for on a session of its own, and hand it to the
    worker after that commits."""
    from eneo.integration.tasks import integration_task

    async with db_container() as container:
        personal = await _source(container)
    knowledge_id = str(personal)
    try:
        await integration_task._queue_follow_up(redis_client, personal)  # pyright: ignore[reportPrivateUsage]
        assert dispatches.calls == []

        await redis_client.set(sync_pending_full_key(knowledge_id), "1", ex=60)
        await integration_task._queue_follow_up(redis_client, personal)  # pyright: ignore[reportPrivateUsage]
        await dispatches.wait_for(1)
        async with db_container() as container:
            tasks = (
                await container.session().scalars(
                    sa.select(Jobs.task).where(Jobs.name == "Library")
                )
            ).all()
    finally:
        await redis_client.delete(
            sync_queued_key(knowledge_id), sync_pending_full_key(knowledge_id)
        )

    # The source has a delta token; the marker asked for a full sync.
    assert dispatches.calls == [("pull_sharepoint_content", personal)]
    assert tasks == ["pull_sharepoint_content"]


async def test_a_removed_subscription_is_recreated_and_its_sources_queued(
    db_container, redis_client, monkeypatch, dispatches
):
    from eneo.database.tables.sharepoint_subscription_table import (
        SharePointSubscription as SubscriptionDB,
    )
    from eneo.integration.infrastructure import sharepoint_subscription_worker
    from eneo.integration.infrastructure.sharepoint_subscription_service import (
        SharePointSubscriptionService,
    )
    from eneo.integration.infrastructure.sharepoint_webhook_service import (
        SubscriptionMaintenance,
    )

    async def token(*_args):
        return object()

    async def create_at_graph(self, **_kwargs):
        return "graph-new"

    async def delete_at_graph(self, **_kwargs):
        return True

    monkeypatch.setattr(
        sharepoint_subscription_worker, "get_token_for_subscription", token
    )
    monkeypatch.setattr(
        SharePointSubscriptionService, "_create_graph_subscription", create_at_graph
    )
    monkeypatch.setattr(
        SharePointSubscriptionService, "_delete_graph_subscription", delete_at_graph
    )
    async with db_container() as container:
        personal = await _source(container)
        session = container.session()
        connection_id = await session.scalar(
            sa.select(IntegrationKnowledgeDB.user_integration_id).where(
                IntegrationKnowledgeDB.id == personal
            )
        )
        subscription = SubscriptionDB(
            user_integration_id=connection_id,
            site_id="site-1",
            subscription_id="graph-removed",
            drive_id="drive-1",
            expires_at=datetime.now(timezone.utc) + timedelta(days=10),
        )
        session.add(subscription)
        await session.flush()
        subscription_id = subscription.id
        await session.execute(
            sa.update(IntegrationKnowledgeDB)
            .where(IntegrationKnowledgeDB.id == personal)
            .values(sharepoint_subscription_id=subscription_id)
        )
    try:
        await sharepoint_subscription_worker.maintain_subscriptions(
            [SubscriptionMaintenance(subscription_id, "subscriptionRemoved")]
        )
        await dispatches.wait_for(1)
    finally:
        await redis_client.delete(sync_queued_key(str(personal)))

    async with db_container() as container:
        graph_id = await container.session().scalar(
            sa.select(SubscriptionDB.subscription_id).where(
                SubscriptionDB.id == subscription_id
            )
        )
    assert graph_id == "graph-new"
    assert dispatches.calls == [("sync_sharepoint_delta", personal)]


@pytest.mark.parametrize(
    ("failed_hours_ago", "succeeded_hours_ago", "candidate"),
    [
        pytest.param(1, None, False, id="never-signed-in"),
        pytest.param(1, 2, False, id="failed-since"),
        pytest.param(2, 1, True, id="signed-in-since"),
        pytest.param(None, 1, True, id="healthy"),
    ],
)
async def test_sources_of_an_org_app_whose_sign_in_fails_are_skipped(
    db_container, failed_hours_ago, succeeded_hours_ago, candidate
):
    """A sync would fail the same way; the next successful sign-in elsewhere
    brings them back."""
    now = datetime.now(timezone.utc)
    async with db_container() as container:
        app_id = await _tenant_app(
            container,
            active=True,
            failed_at=now - timedelta(hours=failed_hours_ago)
            if failed_hours_ago
            else None,
            succeeded_at=now - timedelta(hours=succeeded_hours_ago)
            if succeeded_hours_ago
            else None,
        )
        organization = await _source(
            container, auth_type="tenant_app", tenant_app_id=app_id
        )

        candidates = await _candidate_ids(container)

    assert (organization in candidates) is candidate
