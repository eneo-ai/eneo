import asyncio

import pytest
from dependency_injector import providers
from sqlalchemy import delete, insert

from eneo.database.database import sessionmanager
from eneo.database.tables.object_content_policy_table import (
    ObjectContentDeploymentPolicy,
)
from eneo.database.tables.users_table import Users
from eneo.main.container.container import Container, SessionProxy
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import (
    DeploymentPolicy,
    DeploymentPolicyConflict,
    DeploymentPolicyRepository,
    DeploymentPolicyUpdate,
)
from eneo.object_content.deployment_policy_router import _read_projection
from eneo.server.dependencies.container import load_container_upload_admission


async def _seed_policy() -> None:
    async with sessionmanager.session() as session, session.begin():
        await session.execute(delete(ObjectContentDeploymentPolicy))
        await session.execute(
            insert(ObjectContentDeploymentPolicy).values(
                id=1,
                revision=1,
                new_write_storage_target=StorageKind.POSTGRES_INLINE.value,
                session_file_limit_bytes=10,
                session_image_limit_bytes=20,
                knowledge_file_limit_bytes=30,
                transcription_audio_limit_bytes=40,
                updated_by_actor="migration",
            )
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_policy_put_returns_the_committed_projection(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
) -> None:
    await _seed_policy()
    async with db_container() as container:
        session = container.session()
        stored_user = await session.get(Users, admin_user.id)
        assert stored_user is not None
        stored_user.is_platform_admin = True
        token = container.auth_service().create_access_token_for_user(admin_user)

    response = await client.put(
        "/api/v1/admin/object-content-policy",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "expected_revision": 1,
            "new_write_storage_target": "postgres_inline",
            "session_file_limit_bytes": 101,
            "session_image_limit_bytes": 102,
            "knowledge_file_limit_bytes": 103,
            "transcription_audio_limit_bytes": 104,
        },
    )

    assert response.status_code == 200, response.text
    policy = response.json()["policy"]
    assert policy["revision"] == 2
    assert policy["new_write_storage_target"] == "postgres_inline"
    assert policy["session_file_limit_bytes"] == 101
    assert policy["session_image_limit_bytes"] == 102
    assert policy["knowledge_file_limit_bytes"] == 103
    assert policy["transcription_audio_limit_bytes"] == 104
    assert policy["updated_by_actor"] == "platform_admin"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_policy_compare_and_swap_has_one_winner_and_atomic_read(
    admin_user,
) -> None:
    await _seed_policy()

    async def replace(value: int) -> DeploymentPolicy | DeploymentPolicyConflict:
        try:
            async with sessionmanager.session() as session, session.begin():
                return await DeploymentPolicyRepository(session).replace(
                    DeploymentPolicyUpdate(
                        expected_revision=1,
                        new_write_storage_target=StorageKind.POSTGRES_INLINE,
                        session_file_limit_bytes=value,
                        session_image_limit_bytes=value,
                        knowledge_file_limit_bytes=value,
                        transcription_audio_limit_bytes=value,
                    ),
                    actor_user_id=admin_user.id,
                )
        except DeploymentPolicyConflict as error:
            return error

    results = await asyncio.gather(replace(101), replace(202))

    winners = [result for result in results if isinstance(result, DeploymentPolicy)]
    conflicts = [
        result for result in results if isinstance(result, DeploymentPolicyConflict)
    ]
    assert len(winners) == 1
    assert len(conflicts) == 1

    async with sessionmanager.session() as session, session.begin():
        stored = await DeploymentPolicyRepository(session).get()
    winner = winners[0]
    assert stored.revision == 2
    assert (
        stored.session_file_limit_bytes,
        stored.session_image_limit_bytes,
        stored.knowledge_file_limit_bytes,
        stored.transcription_audio_limit_bytes,
    ) == (
        winner.session_file_limit_bytes,
        winner.session_image_limit_bytes,
        winner.knowledge_file_limit_bytes,
        winner.transcription_audio_limit_bytes,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_projection_is_bounded_and_sanitized(db_container) -> None:
    await _seed_policy()
    async with db_container():
        async with sessionmanager.session() as session:
            projection = await _read_projection(session)

    assert len(projection.capabilities) == 2
    assert len(projection.limits) == 5
    payload = projection.model_dump(mode="json")
    assert set(payload) == {"policy", "limits", "capabilities"}
    assert set(payload["policy"]) == {
        "revision",
        "new_write_storage_target",
        "session_file_limit_bytes",
        "session_image_limit_bytes",
        "knowledge_file_limit_bytes",
        "transcription_audio_limit_bytes",
        "moves_paused",
        "updated_by_actor",
        "created_at",
        "updated_at",
    }
    assert all(
        set(limit)
        == {
            "use_case",
            "configured_bytes",
            "effective_bytes",
            "storage_target",
            "operator_ceiling_bytes",
            "constraining_source",
        }
        for limit in payload["limits"]
    )
    assert all(
        set(capability) == {"target", "configured", "selectable", "readiness_code"}
        for capability in payload["capabilities"]
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_global_inventory_requires_platform_admin_authority(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
) -> None:
    await _seed_policy()
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)

    headers = {"Authorization": f"Bearer {token}"}
    policy = await client.get(
        "/api/v1/admin/object-content-policy",
        headers=headers,
    )
    tenant_inventory = await client.get(
        "/api/v1/admin/object-content-inventory",
        headers=headers,
    )

    assert policy.status_code == 200, policy.text
    assert "inventory" not in policy.json()
    assert tenant_inventory.status_code == 403, tenant_inventory.text

    async with db_container() as container:
        stored_user = await container.session().get(Users, admin_user.id)
        assert stored_user is not None
        stored_user.is_platform_admin = True

    platform_inventory = await client.get(
        "/api/v1/admin/object-content-inventory",
        headers=headers,
    )

    assert platform_inventory.status_code == 200, platform_inventory.text
    inventory = platform_inventory.json()["inventory"]
    assert len(inventory) <= 12
    assert all(
        set(fact) == {"target", "state", "count", "bytes", "oldest_created_at"}
        for fact in inventory
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_privileged_policy_routes_reject_user_api_keys(
    client,
    admin_user_api_key,
) -> None:
    headers = {"X-API-Key": admin_user_api_key.key}
    inventory = await client.get(
        "/api/v1/admin/object-content-inventory",
        headers=headers,
    )
    replacement = await client.put(
        "/api/v1/admin/object-content-policy",
        headers=headers,
        json={
            "expected_revision": 1,
            "new_write_storage_target": "postgres_inline",
            "session_file_limit_bytes": 101,
            "session_image_limit_bytes": 102,
            "knowledge_file_limit_bytes": 103,
            "transcription_audio_limit_bytes": 104,
        },
    )
    moves = await client.get(
        "/api/v1/admin/object-content-moves",
        headers=headers,
    )
    queue = await client.post(
        "/api/v1/admin/object-content-moves",
        headers=headers,
        json={"target": "object_store", "limit": 1},
    )
    pause = await client.put(
        "/api/v1/admin/object-content-moves/pause",
        headers=headers,
        json={"expected_revision": 1, "moves_paused": True},
    )

    for response in (inventory, replacement, moves, queue, pause):
        assert response.status_code == 403, response.text
        assert "session token" in response.text.lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_independent_api_and_worker_containers_observe_committed_revision(
    admin_user,
    db_container,
) -> None:
    await _seed_policy()

    async with db_container() as api_container:
        api_snapshot = await load_container_upload_admission(api_container)

        async with sessionmanager.session() as session, session.begin():
            await DeploymentPolicyRepository(session).replace(
                DeploymentPolicyUpdate(
                    expected_revision=1,
                    new_write_storage_target=StorageKind.POSTGRES_INLINE,
                    session_file_limit_bytes=101,
                    session_image_limit_bytes=102,
                    knowledge_file_limit_bytes=103,
                    transcription_audio_limit_bytes=104,
                ),
                actor_user_id=admin_user.id,
            )

        worker_container = Container(
            session=providers.Object(SessionProxy()),
        )
        async with Container.session_scope():
            worker_snapshot = await load_container_upload_admission(worker_container)

    assert api_snapshot.policy_revision == 1
    assert api_snapshot.session_file_maximum_bytes == 10
    assert worker_snapshot.policy_revision == 2
    assert worker_snapshot.session_file_maximum_bytes == 101
