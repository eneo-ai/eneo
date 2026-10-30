"""The transcription-service read of a space decides which services it may use
as a full load of the space does, without reading its applications."""

from __future__ import annotations

from uuid import UUID

import pytest

from eneo.database.database import sessionmanager
from eneo.spaces.space import Space
from tests.integration.flows.speaker_service_support import (
    classify_below,
    grant,
    personal_space,
    shared_space,
    speaker_service,
    switch_off,
)
from tests.integration.flows.statement_capture_support import capture_queries
from tests.integration.spaces.space_applications_support import (
    add_assistants,
    space_mcp_servers,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def headers(db_container, admin_user, patch_auth_service_jwt) -> dict[str, str]:
    _ = patch_auth_service_jwt
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
    return {"Authorization": f"Bearer {token}"}


def _services(space: Space) -> tuple[list[UUID], ...]:
    return (
        [service.id for service in space.usable_transcription_services],
        [service.id for service in space.linked_transcription_services],
        [service.id for service in space.transcription_services_below_classification],
    )


@pytest.mark.parametrize("personal", [False, True], ids=["shared", "personal"])
async def test_the_space_may_use_the_services_a_full_load_says_it_may(
    client, db_container, admin_user, headers, personal: bool
):
    usable, switched_off, below, ungranted = [
        await speaker_service(client, headers) for _ in range(4)
    ]
    granted = await shared_space(client, headers)
    if personal:
        space_id = await personal_space(
            db_container, admin_user.id, admin_user.tenant_id
        )
    else:
        space_id = granted
    await grant(client, headers, granted, usable, switched_off, below)
    await switch_off(client, headers, switched_off)
    await classify_below(
        db_container,
        tenant_id=admin_user.tenant_id,
        space_id=space_id,
        service_id=below,
        kept=[usable, switched_off, ungranted],
    )

    async with db_container() as container:
        repo = container.space_repo()
        lean = await repo.get_transcription_space(UUID(space_id))
        full = await repo.one(UUID(space_id))
        execution = await repo.get_execution_space(UUID(space_id))

    assert _services(lean) == _services(full)
    expected_usable = {UUID(usable)} | ({UUID(ungranted)} if personal else set())
    assert set(_services(lean)[0]) == expected_usable
    assert UUID(below) in _services(lean)[2]
    # The plain classification read links no service.
    assert _services(execution) == ([], [], [])
    assert lean.security_classification == full.security_classification
    assert (lean.id, lean.user_id, lean.tenant_space_id) == (
        full.id,
        full.user_id,
        full.tenant_space_id,
    )


async def test_the_read_costs_the_same_whatever_the_spaces_assistants(
    client, db_container, admin_user, headers
):
    space_id = UUID(await shared_space(client, headers))
    await grant(client, headers, str(space_id), await speaker_service(client, headers))
    servers = await space_mcp_servers(
        db_container, tenant_id=admin_user.tenant_id, space_id=space_id, tools=[("a",)]
    )
    engine = sessionmanager._engine
    assert engine is not None
    counts: list[int] = []
    for grown in (0, 3):
        await add_assistants(
            client,
            headers,
            db_container,
            space_id=space_id,
            servers=servers,
            count=grown,
        )
        async with db_container() as container:
            with capture_queries(engine.sync_engine) as statements:
                space = await container.space_repo().get_transcription_space(space_id)
        assert len(space.usable_transcription_services) == 1
        counts.append(len(statements))

    assert counts[0] == counts[1], counts
    assert counts[0] <= 2, counts
