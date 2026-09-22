"""Integration tests for collection ownership transfer.

After a transfer, the destination space owns the collection, it is the only
space the collection is distributed to, and no assistant or service holds a
binding to a collection its own space cannot see.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from eneo.database.tables.assistant_table import AssistantsGroups
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.groups_spaces_table import GroupsSpaces
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.service_table import ServicesGroups
from eneo.database.tables.spaces_table import Spaces, SpacesEmbeddingModels, SpacesUsers
from eneo.main.exceptions import UnauthorizedException
from eneo.main.models import ModelId
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.users.user import UserAdd, UserState
from tests.integration.test_space_view_membership import (
    _create_shared_space,
)
from tests.integration.test_space_view_membership import (
    admin_token as _admin_token,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

admin_token = _admin_token


@dataclass
class TransferCollection:
    id: UUID
    source: UUID
    destination: UUID
    other: UUID
    organization: UUID
    assistants: dict[UUID, UUID]
    services: dict[UUID, UUID]


@pytest.fixture
async def transfer_collection(
    client,
    db_container,
    admin_user,
    admin_token,
    completion_model_factory,
    assistant_factory,
    service_factory,
):
    space_ids = [
        UUID(await _create_shared_space(client, admin_token=admin_token))
        for _ in range(3)
    ]
    source, destination, other = space_ids
    response = await client.post(
        f"/api/v1/spaces/{source}/knowledge/groups/",
        json={"name": "Transfer collection"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201, response.text
    group_id = UUID(response.json()["id"])
    assistants = {}
    services = {}
    async with db_container() as container:
        session = container.session()
        organization = await session.scalar(
            sa.select(Spaces.tenant_space_id).where(Spaces.id == source)
        )
        assert organization is not None
        embedding_model_id = await session.scalar(
            sa.select(CollectionsTable.embedding_model_id).where(
                CollectionsTable.id == group_id
            )
        )
        await session.execute(
            pg_insert(SpacesEmbeddingModels)
            .values(space_id=organization, embedding_model_id=embedding_model_id)
            .on_conflict_do_nothing()
        )
        model = await completion_model_factory(session, f"transfer-{uuid4().hex[:8]}")
        for space_id in space_ids:
            assistant = await assistant_factory(
                session, "Bound assistant", model.id, space_id=space_id
            )
            service = await service_factory(
                session, "Bound service", model.id, space_id=space_id
            )
            assistants[space_id] = assistant.id
            services[space_id] = service.id
            session.add_all(
                [
                    AssistantsGroups(assistant_id=assistant.id, group_id=group_id),
                    ServicesGroups(service_id=service.id, group_id=group_id),
                ]
            )
            await container.group_repo().link_group_to_space(group_id, space_id)
        for title in ("First document", "Second document"):
            session.add(
                InfoBlobs(
                    text=title,
                    title=title,
                    size=len(title),
                    source_id=uuid4(),
                    version_state="active",
                    user_id=admin_user.id,
                    tenant_id=admin_user.tenant_id,
                    group_id=group_id,
                )
            )
    return TransferCollection(
        group_id, source, destination, other, organization, assistants, services
    )


async def _collection_state(db_container, group_id):
    async with db_container() as container:
        session = container.session()
        queries = {
            "collection": sa.select(*CollectionsTable.__table__.columns).where(
                CollectionsTable.id == group_id
            ),
            "documents": sa.select(*InfoBlobs.__table__.columns)
            .where(InfoBlobs.group_id == group_id)
            .order_by(InfoBlobs.id),
            "distribution": sa.select(
                GroupsSpaces.collection_id,
                GroupsSpaces.space_id,
                GroupsSpaces.created_at,
            )
            .where(GroupsSpaces.collection_id == group_id)
            .order_by(GroupsSpaces.space_id),
            "assistants": sa.select(*AssistantsGroups.__table__.columns)
            .where(AssistantsGroups.group_id == group_id)
            .order_by(AssistantsGroups.assistant_id),
            "services": sa.select(*ServicesGroups.__table__.columns)
            .where(ServicesGroups.group_id == group_id)
            .order_by(ServicesGroups.service_id),
        }
        return {
            name: (await session.execute(query)).mappings().all()
            for name, query in queries.items()
        }


async def _transfer(client, token, collection, destination):
    return await client.post(
        f"/api/v1/groups/{collection.id}/transfer/",
        json={"target_space_id": str(destination)},
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.parametrize("to_organization", [False, True])
async def test_collection_transfer_persists_owner_and_visible_bindings(
    client, db_container, admin_token, transfer_collection, to_organization
):
    collection = transfer_collection
    destination = collection.organization if to_organization else collection.destination
    before = await _collection_state(db_container, collection.id)
    response = await _transfer(client, admin_token, collection, destination)
    assert response.status_code == 204, response.text
    after = await _collection_state(db_container, collection.id)
    assert after["collection"][0]["space_id"] == destination
    assert len(before["documents"]) == 2
    assert after["documents"] == before["documents"]
    assert [row["space_id"] for row in after["distribution"]] == [destination]
    visible_spaces = (
        {collection.source, collection.destination, collection.other}
        if to_organization
        else {destination}
    )
    assert {row["assistant_id"] for row in after["assistants"]} == {
        collection.assistants[space_id] for space_id in visible_spaces
    }
    assert {row["service_id"] for row in after["services"]} == {
        collection.services[space_id] for space_id in visible_spaces
    }
    for space_id in (collection.source, destination):
        response = await client.get(
            f"/api/v1/spaces/{space_id}/knowledge/",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200, response.text
        owned = {
            UUID(group["id"])
            for group in response.json()["groups"]["items"]
            if UUID(group["space_id"]) == space_id
        }
        assert (collection.id in owned) == (space_id == destination)


@pytest.mark.parametrize("denied_space", ["source", "destination"])
async def test_collection_transfer_denied_permission_preserves_all_rows(
    client, db_container, admin_user, admin_token, transfer_collection, denied_space
):
    collection = transfer_collection
    async with db_container() as container:
        await container.session().execute(
            sa.update(SpacesUsers)
            .where(
                SpacesUsers.space_id == getattr(collection, denied_space),
                SpacesUsers.user_id == admin_user.id,
            )
            .values(role=SpaceRoleValue.VIEWER.value)
        )
    before = await _collection_state(db_container, collection.id)
    response = await _transfer(client, admin_token, collection, collection.destination)
    assert response.status_code == 403, response.text
    assert await _collection_state(db_container, collection.id) == before


async def test_collection_transfer_missing_embedding_model_preserves_all_rows(
    client, db_container, admin_token, transfer_collection
):
    collection = transfer_collection
    async with db_container() as container:
        await container.session().execute(
            sa.delete(SpacesEmbeddingModels).where(
                SpacesEmbeddingModels.space_id == collection.destination
            )
        )
    before = await _collection_state(db_container, collection.id)
    response = await _transfer(client, admin_token, collection, collection.destination)
    assert response.status_code == 400, response.text
    assert await _collection_state(db_container, collection.id) == before


async def test_collection_transfer_same_space_preserves_all_rows(
    client, db_container, admin_token, transfer_collection
):
    collection = transfer_collection
    before = await _collection_state(db_container, collection.id)
    response = await _transfer(client, admin_token, collection, collection.source)
    assert response.status_code == 204, response.text
    assert await _collection_state(db_container, collection.id) == before


async def test_concurrent_collection_transfer_authorizes_the_locked_owner(
    db_container, admin_user, transfer_collection
):
    collection = transfer_collection
    async with db_container() as container:
        user = await container.user_repo().add(
            UserAdd(
                email=f"transfer-{uuid4().hex[:8]}@example.com",
                username=f"transfer_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id) for role in admin_user.roles],
            )
        )
        container.session().add_all(
            [
                SpacesUsers(space_id=space_id, user_id=user.id, role=role.value)
                for space_id, role in (
                    (collection.source, SpaceRoleValue.ADMIN),
                    (collection.other, SpaceRoleValue.ADMIN),
                    (collection.destination, SpaceRoleValue.VIEWER),
                )
            ]
        )
    pid_ready = asyncio.Future()

    async def competing_transfer():
        async with db_container(user=user) as container:
            pid_ready.set_result(
                await container.session().scalar(sa.text("SELECT pg_backend_pid()"))
            )
            await container.resource_mover_service().move_collection_to_space(
                collection.id, collection.other
            )

    task = None
    try:
        async with db_container() as container:
            await container.resource_mover_service().move_collection_to_space(
                collection.id, collection.destination
            )
            task = asyncio.create_task(competing_transfer())
            pid = await asyncio.wait_for(pid_ready, timeout=5)
            async with asyncio.timeout(5):
                while True:
                    blocked = await container.session().scalar(
                        sa.text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": pid},
                    )
                    if blocked:
                        break
                    assert not task.done(), (
                        "Competing transfer did not wait for the owner lock"
                    )
                    await asyncio.sleep(0.01)
        with pytest.raises(UnauthorizedException):
            await asyncio.wait_for(task, timeout=5)
    finally:
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    after = await _collection_state(db_container, collection.id)
    assert after["collection"][0]["space_id"] == collection.destination
    assert [row["space_id"] for row in after["distribution"]] == [
        collection.destination
    ]
    assert {row["assistant_id"] for row in after["assistants"]} == {
        collection.assistants[collection.destination]
    }
    assert {row["service_id"] for row in after["services"]} == {
        collection.services[collection.destination]
    }
