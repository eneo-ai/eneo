import asyncio

import pytest
from sqlalchemy import delete, insert

from eneo.database.database import sessionmanager
from eneo.database.tables.object_content_policy_table import (
    ObjectContentDeploymentPolicy,
)
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import (
    DeploymentPolicy,
    DeploymentPolicyConflict,
    DeploymentPolicyRepository,
    DeploymentPolicyUpdate,
)
from eneo.object_content.deployment_policy_router import _read_projection


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
    async with db_container() as container:
        session = container.session()
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

        projection = await _read_projection(session)

    assert len(projection.capabilities) == 2
    assert len(projection.limits) == 5
    assert len(projection.inventory) <= 12
    payload = projection.model_dump(mode="json")
    assert set(payload) == {"policy", "limits", "capabilities", "inventory"}
    assert set(payload["policy"]) == {
        "revision",
        "new_write_storage_target",
        "session_file_limit_bytes",
        "session_image_limit_bytes",
        "knowledge_file_limit_bytes",
        "transcription_audio_limit_bytes",
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
    assert all(
        set(fact) == {"target", "state", "count", "bytes", "oldest_created_at"}
        for fact in payload["inventory"]
    )
