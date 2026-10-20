"""Writes to integration knowledge against PostgreSQL: a batch import leaves
nothing behind for an item it reports as failed, and a rename made while a
sync holds the row keeps what the sync wrote."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.integration_knowledge_spaces_table import (
    IntegrationKnowledgesSpaces,
)
from eneo.database.tables.integration_table import (
    Integration,
    IntegrationKnowledge,
    TenantIntegration,
    UserIntegration,
)
from eneo.database.tables.spaces_table import Spaces, SpacesEmbeddingModels
from eneo.integration.application.integration_knowledge_service import (
    IntegrationKnowledgeService,
)
from eneo.integration.application.user_integration_service import (
    AuthorizedIntegration,
)
from eneo.integration.domain.repositories.integration_knowledge_repo import (
    IntegrationKnowledgeSyncingError,
)
from eneo.integration.infrastructure.auth_service.org_token_provider import (
    SharePointCredentialsInvalidError,
)
from eneo.integration.presentation.models import IntegrationType


@dataclass
class Setup:
    personal_space: UUID
    organization_space: UUID
    child_spaces: list[UUID]
    embedding_model: UUID
    connection: UUID


@pytest.fixture
async def setup(db_container, admin_user, embedding_model_factory) -> Setup:
    async with db_container() as container:
        session = container.session()
        model = await embedding_model_factory(session)
        personal = Spaces(
            name=f"personal-{uuid4().hex[:6]}",
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
        )
        session.add(personal)
        await session.flush()
        organization = await session.scalar(
            sa.select(Spaces.id).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        assert organization is not None
        session.add(
            Spaces(
                name=f"child-{uuid4().hex[:6]}",
                tenant_id=admin_user.tenant_id,
                tenant_space_id=organization,
            )
        )
        await session.flush()
        children = (
            await session.scalars(
                sa.select(Spaces.id).where(Spaces.tenant_space_id == organization)
            )
        ).all()
        spaces = {"personal": personal.id, "organization": organization}
        await session.execute(
            sa.insert(SpacesEmbeddingModels),
            [
                dict(space_id=space_id, embedding_model_id=model.id)
                for space_id in spaces.values()
            ],
        )
        integration = Integration(
            name=f"sharepoint-{uuid4().hex[:8]}",
            description="SharePoint",
            integration_type="sharepoint",
        )
        session.add(integration)
        await session.flush()
        tenant_integration = TenantIntegration(
            tenant_id=admin_user.tenant_id, integration_id=integration.id
        )
        session.add(tenant_integration)
        await session.flush()
        connection = UserIntegration(
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            tenant_integration_id=tenant_integration.id,
            authenticated=True,
        )
        session.add(connection)
        await session.flush()
        # Read before the commit expires the instances.
        built = Setup(
            personal_space=spaces["personal"],
            organization_space=spaces["organization"],
            child_spaces=sorted(children),
            embedding_model=model.id,
            connection=connection.id,
        )
    return built


class _Dispatches:
    """Jobs handed to the worker; the hand-over waits for the commit."""

    def __init__(self) -> None:
        self.knowledge_ids: list[UUID] = []
        self._changed = asyncio.Event()

    async def record(self, task, job_id, params) -> None:
        self.knowledge_ids.append(params.integration_knowledge_id)
        self._changed.set()

    async def wait_for(self, count: int) -> None:
        async def reached() -> None:
            while len(self.knowledge_ids) < count:
                self._changed.clear()
                await self._changed.wait()

        await asyncio.wait_for(reached(), timeout=5)


@pytest.fixture
def dispatches(monkeypatch) -> _Dispatches:
    recorder = _Dispatches()
    monkeypatch.setattr("eneo.jobs.job_manager.job_manager.enqueue", recorder.record)
    return recorder


def _service(container, *, job_service, organization_token=None):
    """The real service and repositories, with Graph, the job queue and the
    token sources replaced."""
    oauth_token = MagicMock(id=uuid4(), is_sharepoint=True)
    oauth_token.token_type = IntegrationType.Sharepoint
    oauth_token_repo = AsyncMock()
    oauth_token_repo.one.return_value = oauth_token
    subscriptions = AsyncMock()
    subscriptions.ensure_subscription_for_site.return_value = None
    user_integration_service = container.user_integration_service()
    if organization_token is not None:
        # An organization connection without a stored app: the authorization
        # rules are covered elsewhere, the writes are what is tested here.
        real = user_integration_service.get_authorized_integration

        async def authorized(id, *, space=None):
            connection = (await real(id, space=None)).integration
            return AuthorizedIntegration(
                integration=connection, tenant_app=MagicMock(id=uuid4())
            )

        user_integration_service = MagicMock()
        user_integration_service.get_authorized_integration = authorized
    org_token_provider = AsyncMock()
    if organization_token is not None:
        org_token_provider.get_access_token.side_effect = organization_token
    return IntegrationKnowledgeService(
        job_service=job_service,
        user=container.user(),
        oauth_token_repo=oauth_token_repo,
        space_repo=container.space_repo(),
        integration_knowledge_repo=container.integration_knowledge_repo(),
        embedding_model_repo=container.embedding_model_repo2(),
        user_integration_service=user_integration_service,
        actor_manager=container.actor_manager(),
        sharepoint_subscription_service=subscriptions,
        tenant_sharepoint_app_repo=AsyncMock(),
        tenant_app_auth_service=AsyncMock(),
        org_token_provider=org_token_provider,
    )


def _items(*names: str) -> list:
    return [
        {
            "name": name,
            "key": "contoso.sharepoint.com,site,web",
            "url": f"https://contoso.sharepoint.com/sites/KS/{name}",
            "folder_id": f"folder-{name}",
            "folder_path": f"/{name}",
            "selected_item_type": "folder",
            "resource_type": "site",
        }
        for name in names
    ]


async def _stored(container, space_id: UUID) -> tuple[list[str], list[UUID]]:
    session = container.session()
    names = (
        await session.scalars(
            sa.select(IntegrationKnowledge.name)
            .where(IntegrationKnowledge.space_id == space_id)
            .order_by(IntegrationKnowledge.name)
        )
    ).all()
    distributed = (
        await session.scalars(
            sa.select(IntegrationKnowledgesSpaces.space_id)
            .join(
                IntegrationKnowledge,
                IntegrationKnowledge.id
                == IntegrationKnowledgesSpaces.integration_knowledge_id,
            )
            .where(IntegrationKnowledge.space_id == space_id)
        )
    ).all()
    return list(names), list(distributed)


def _jobs(*failures: Exception | None) -> AsyncMock:
    job_service = AsyncMock()
    job_service.queue_job.side_effect = [
        failure if failure is not None else MagicMock(id=uuid4())
        for failure in failures
    ]
    return job_service


async def test_a_batch_item_that_fails_after_its_write_leaves_nothing(
    db_container, setup
):
    async with db_container() as container:
        service = _service(
            container, job_service=_jobs(None, RuntimeError("queue down"), None)
        )
        results = await service.create_space_integration_knowledge_batch(
            user_integration_id=setup.connection,
            embedding_model_id=setup.embedding_model,
            space_id=setup.personal_space,
            items=_items("Budget", "Protokoll", "Rutiner"),
            wrapper_name="Kommunstyrelsen",
        )

        assert [result["status"] for result in results] == [
            "created",
            "failed",
            "created",
        ]
        assert await _stored(container, setup.personal_space) == (
            ["Budget", "Rutiner"],
            [],
        )

    async with db_container() as container:
        # And so it is after the request's commit.
        assert await _stored(container, setup.personal_space) == (
            ["Budget", "Rutiner"],
            [],
        )


async def test_jobs_reach_the_worker_only_after_the_commit_and_only_for_kept_items(
    db_container, setup, dispatches
):
    async with db_container() as container:
        # The real hand-over to the worker; only the job rows are faked.
        job_service = container.job_service()
        job_service.queue_job = _jobs(None, RuntimeError("queue down"), None).queue_job
        service = _service(container, job_service=job_service)
        results = await service.create_space_integration_knowledge_batch(
            user_integration_id=setup.connection,
            embedding_model_id=setup.embedding_model,
            space_id=setup.personal_space,
            items=_items("Budget", "Protokoll", "Rutiner"),
        )
        await asyncio.sleep(0.05)
        assert dispatches.knowledge_ids == []

    await dispatches.wait_for(2)
    assert dispatches.knowledge_ids == [
        results[0]["integration_knowledge_id"],
        results[2]["integration_knowledge_id"],
    ]


async def test_a_rolled_back_request_hands_no_job_to_the_worker(
    db_container, setup, dispatches
):
    with pytest.raises(RuntimeError, match="request failed"):
        async with db_container() as container:
            service = _service(container, job_service=container.job_service())
            await service.create_space_integration_knowledge(
                user_integration_id=setup.connection,
                name="Budget",
                embedding_model_id=setup.embedding_model,
                space_id=setup.personal_space,
                **{
                    key: value
                    for key, value in _items("Budget")[0].items()
                    if key != "name"
                },
            )
            raise RuntimeError("request failed")

    await asyncio.sleep(0.05)
    assert dispatches.knowledge_ids == []


async def test_a_resync_survives_a_database_error_in_its_subscription_step(
    db_container, setup, dispatches
):
    """The error was swallowed but left the transaction aborted, so queueing
    the job failed and the resync was a 500."""
    async with db_container() as container:
        knowledge = IntegrationKnowledge(
            name="Protokoll",
            url="https://contoso.sharepoint.com/sites/KS/Protokoll",
            space_id=setup.personal_space,
            tenant_id=container.user().tenant_id,
            embedding_model_id=setup.embedding_model,
            user_integration_id=setup.connection,
            site_id="contoso.sharepoint.com,site,web",
            resource_type="site",
        )
        container.session().add(knowledge)
        await container.session().flush()
        knowledge_id = knowledge.id

    async with db_container() as container:
        service = _service(container, job_service=container.job_service())

        async def failing_ensure(**_):
            await container.session().execute(sa.text("SELECT 1/0"))

        subscriptions = service.sharepoint_subscription_service
        subscriptions.ensure_subscription_for_site.side_effect = failing_ensure
        job, _ = await service.trigger_full_sync(setup.personal_space, knowledge_id)

    await dispatches.wait_for(1)
    assert dispatches.knowledge_ids == [knowledge_id]
    async with db_container() as container:
        assert await container.job_service().get_job(job.id)


async def test_a_failed_item_in_the_organization_space_loses_its_distribution(
    db_container, setup
):
    async with db_container() as container:
        service = _service(
            container,
            job_service=_jobs(RuntimeError("queue down"), None),
            organization_token=["access-token"],
        )
        results = await service.create_space_integration_knowledge_batch(
            user_integration_id=setup.connection,
            embedding_model_id=setup.embedding_model,
            space_id=setup.organization_space,
            items=_items("Protokoll", "Rutiner"),
        )

    assert [result["status"] for result in results] == ["failed", "created"]
    async with db_container() as container:
        names, distributed = await _stored(container, setup.organization_space)
    assert names == ["Rutiner"]
    assert sorted(distributed) == setup.child_spaces


async def test_refused_organization_credentials_write_no_item(db_container, setup):
    job_service = _jobs()
    with pytest.raises(SharePointCredentialsInvalidError):
        async with db_container() as container:
            service = _service(
                container,
                job_service=job_service,
                organization_token=SharePointCredentialsInvalidError("invalid_client"),
            )
            await service.create_space_integration_knowledge_batch(
                user_integration_id=setup.connection,
                embedding_model_id=setup.embedding_model,
                space_id=setup.organization_space,
                items=_items("Budget", "Protokoll", "Rutiner"),
            )

    job_service.queue_job.assert_not_awaited()
    async with db_container() as container:
        assert await _stored(container, setup.organization_space) == ([], [])


async def test_a_rename_during_a_sync_keeps_what_the_sync_wrote(db_container, setup):
    async with db_container() as container:
        knowledge = IntegrationKnowledge(
            name="Protokoll",
            original_name="Protokoll",
            url="https://contoso.sharepoint.com/sites/KS/Protokoll",
            space_id=setup.personal_space,
            tenant_id=container.user().tenant_id,
            embedding_model_id=setup.embedding_model,
            user_integration_id=setup.connection,
            size=0,
            last_sync_status="never",
        )
        container.session().add(knowledge)
        await container.session().flush()
        knowledge_id = knowledge.id

    async with db_container() as sync:
        # The sync's first write locks the row until the sync commits.
        await sync.integration_knowledge_repo().update_sync_state(
            knowledge_id,
            delta_token="delta-after-first-import",
            size=52_000,
            last_sync_status="success",
            last_sync_summary={"files_processed": 12},
        )
        async with db_container() as rename:
            pid = await rename.session().scalar(sa.text("SELECT pg_backend_pid()"))
            pending = asyncio.create_task(
                rename.integration_knowledge_service().update_knowledge_name(
                    setup.personal_space, knowledge_id, "Protokoll KS"
                )
            )
            try:
                async with asyncio.timeout(10):
                    while not await sync.session().scalar(
                        sa.text(
                            "SELECT wait_event_type = 'Lock' "
                            "FROM pg_stat_activity WHERE pid = :pid"
                        ),
                        {"pid": pid},
                    ):
                        if pending.done():
                            await pending
                            pytest.fail("The rename did not wait for the sync")
                        await asyncio.sleep(0.01)
                await sync.session().commit()
                renamed = await asyncio.wait_for(pending, timeout=10)
            finally:
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)

    # The response is read after the rename's write, so it shows the sync too.
    assert (renamed.name, renamed.delta_token, renamed.size) == (
        "Protokoll KS",
        "delta-after-first-import",
        52_000,
    )
    async with db_container() as container:
        row = (
            await container.session().execute(
                sa.select(
                    IntegrationKnowledge.name,
                    IntegrationKnowledge.original_name,
                    IntegrationKnowledge.delta_token,
                    IntegrationKnowledge.size,
                    IntegrationKnowledge.last_sync_status,
                    IntegrationKnowledge.last_sync_summary,
                ).where(IntegrationKnowledge.id == knowledge_id)
            )
        ).one()
    assert tuple(row) == (
        "Protokoll KS",
        "Protokoll",
        "delta-after-first-import",
        52_000,
        "success",
        {"files_processed": 12},
    )


async def _held_by_a_sync(db_container, setup, monkeypatch):
    """An item and a sync's open transaction holding its row, with a short
    lock timeout for the change under test."""
    monkeypatch.setattr(
        "eneo.integration.infrastructure.repo_impl.integration_knowledge_repo_impl."
        "ROW_LOCK_TIMEOUT",
        "300ms",
    )
    async with db_container() as container:
        knowledge = IntegrationKnowledge(
            name="Protokoll",
            original_name="Protokoll",
            url="https://contoso.sharepoint.com/sites/KS/Protokoll",
            space_id=setup.personal_space,
            tenant_id=container.user().tenant_id,
            embedding_model_id=setup.embedding_model,
            user_integration_id=setup.connection,
            wrapper_id=uuid4(),
            wrapper_name="Kommunstyrelsen",
        )
        container.session().add(knowledge)
        await container.session().flush()
        return knowledge.id, knowledge.wrapper_id


@pytest.mark.parametrize("change", ["rename", "rename_wrapper", "delete"])
async def test_a_change_to_a_syncing_source_answers_at_once(
    db_container, setup, monkeypatch, change
):
    """The change used to hold its request open until the sync committed."""
    knowledge_id, wrapper_id = await _held_by_a_sync(db_container, setup, monkeypatch)

    async with db_container() as sync:
        await sync.integration_knowledge_repo().update_sync_state(
            knowledge_id, last_sync_status="success"
        )
        with pytest.raises(IntegrationKnowledgeSyncingError):
            async with db_container() as request:
                service = request.integration_knowledge_service()
                async with asyncio.timeout(5):
                    if change == "rename":
                        await service.update_knowledge_name(
                            setup.personal_space, knowledge_id, "Protokoll KS"
                        )
                    elif change == "rename_wrapper":
                        await service.update_wrapper_name(
                            setup.personal_space, wrapper_id, "KS"
                        )
                    else:
                        await service.remove_knowledge(
                            setup.personal_space, knowledge_id
                        )

    async with db_container() as container:
        row = (
            await container.session().execute(
                sa.select(
                    IntegrationKnowledge.name, IntegrationKnowledge.wrapper_name
                ).where(IntegrationKnowledge.id == knowledge_id)
            )
        ).one()
    assert tuple(row) == ("Protokoll", "Kommunstyrelsen")


async def test_a_change_after_the_sync_restores_the_lock_timeout(
    db_container, setup, monkeypatch
):
    knowledge_id, _ = await _held_by_a_sync(db_container, setup, monkeypatch)

    async with db_container() as request:
        before = await request.session().scalar(sa.text("SHOW lock_timeout"))
        await request.integration_knowledge_service().update_knowledge_name(
            setup.personal_space, knowledge_id, "Protokoll KS"
        )
        after = await request.session().scalar(sa.text("SHOW lock_timeout"))

    assert after == before
