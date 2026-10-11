"""Spaces grant transcription services under their security classification."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassifications,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.transcription_services_table import (
    SpacesTranscriptionServiceConnections,
)
from eneo.flows.transcription_config import (
    parse_transcription_config,
    resolve_speaker_service,
)
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.transcription_services.repository import (
    TranscriptionServiceConnectionRepository,
)
from eneo.users.user import UserUpdate
from tests.integration.transcription_services.conftest import BASE

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def headers(db_container, admin_user, patch_auth_service_jwt):
    """An administrator who may also edit shared spaces."""
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"service-admin-{uuid4().hex[:8]}",
                permissions=[Permission.ADMIN, Permission.SHARED_SPACES],
                tenant_id=admin_user.tenant_id,
            )
        )
    async with db_container() as container:
        admin = await container.user_repo().update(
            UserUpdate(id=admin_user.id, roles=[ModelId(id=role.id)])
        )
        assert admin is not None
        token = container.auth_service().create_access_token_for_user(admin)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def levels(db_container, admin_user) -> dict[str, UUID]:
    async with db_container() as container:
        session = container.session()
        low = SecurityClassifications(
            tenant_id=admin_user.tenant_id,
            name=f"low-{uuid4().hex[:6]}",
            security_level=1,
        )
        high = SecurityClassifications(
            tenant_id=admin_user.tenant_id,
            name=f"high-{uuid4().hex[:6]}",
            security_level=20,
        )
        session.add_all([low, high])
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == admin_user.tenant_id)
            .values(security_enabled=True)
        )
        await session.flush()
        return {"low": low.id, "high": high.id}


async def _connection(client, headers, **overrides) -> dict:
    response = await client.post(
        BASE,
        json={
            "name": f"vemsa-{uuid4().hex[:8]}",
            "endpoint_url": "https://vemsa.example.se",
            "api_key": "secret",
            **overrides,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _space(client, headers) -> str:
    response = await client.post(
        "/api/v1/spaces/", json={"name": f"grants-{uuid4().hex[:8]}"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _grant(client, headers, space_id: str, *connection_ids: str):
    return await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={"transcription_services": [{"id": id} for id in connection_ids]},
        headers=headers,
    )


async def _grants(db_container, space_id: str) -> set[UUID]:
    async with db_container() as container:
        rows = await container.session().scalars(
            sa.select(SpacesTranscriptionServiceConnections.connection_id).where(
                SpacesTranscriptionServiceConnections.space_id == UUID(space_id)
            )
        )
        return set(rows.all())


async def _available(db_container, space_id: str, connection_id: str) -> bool:
    async with db_container() as container:
        space = await container.space_repo().one(UUID(space_id))
        return space.usable_transcription_service(UUID(connection_id)) is not None


_NO_CHOICE = parse_transcription_config({"wizard": {"transcription_enabled": True}})


async def _standard(client, db_container, headers, space_id: str) -> str | None:
    """The service a flow that chose none uses in the space: the one it
    resolves to, which is the one link the space marks as its standard."""
    async with db_container() as container:
        space = await container.space_repo().one(UUID(space_id))
        resolved = resolve_speaker_service(_NO_CHOICE, space).connection
    read = await client.get(f"/api/v1/spaces/{space_id}/", headers=headers)
    assert read.status_code == 200, read.text
    marked = [
        link["id"]
        for link in read.json()["transcription_services"]
        if link["is_standard"]
    ]
    assert marked == ([] if resolved is None else [str(resolved.id)])
    return marked[0] if marked else None


async def _named(client, headers, prefix: str) -> str:
    """A service whose name sorts by ``prefix``, so name order is the test's."""
    return (await _connection(client, headers, name=f"{prefix}-{uuid4().hex[:8]}"))[
        "id"
    ]


async def _switch(client, headers, connection_id: str, *, on: bool) -> None:
    response = await client.patch(
        f"{BASE}{connection_id}/", json={"is_enabled": on}, headers=headers
    )
    assert response.status_code == 200, response.text


async def test_a_granted_service_is_listed_and_usable_in_the_space(
    client, db_container, headers
):
    connection = await _connection(client, headers)
    space_id = await _space(client, headers)

    response = await _grant(client, headers, space_id, connection["id"])

    assert response.status_code == 200, response.text
    assert response.json()["transcription_services"] == [
        {
            "id": connection["id"],
            "name": connection["name"],
            "meets_security_classification": True,
            "available": True,
            "is_standard": True,
        }
    ]
    assert await _grants(db_container, space_id) == {UUID(connection["id"])}
    assert await _available(db_container, space_id, connection["id"])


async def test_the_service_counts_the_spaces_granted_it(client, headers):
    connection = await _connection(client, headers)
    for _ in range(2):
        await _grant(client, headers, await _space(client, headers), connection["id"])

    listed = await client.get(BASE, headers=headers)

    [service] = [
        item for item in listed.json()["items"] if item["id"] == connection["id"]
    ]
    assert connection["space_count"] == 0
    assert service["space_count"] == 2


async def test_an_unrelated_save_keeps_the_grants(client, db_container, headers):
    connection = await _connection(client, headers)
    space_id = await _space(client, headers)
    await _grant(client, headers, space_id, connection["id"])

    response = await client.patch(
        f"/api/v1/spaces/{space_id}/", json={"name": "renamed"}, headers=headers
    )

    assert response.status_code == 200, response.text
    assert await _grants(db_container, space_id) == {UUID(connection["id"])}


async def test_disabling_a_service_blocks_new_work_but_keeps_the_grant(
    client, db_container, headers
):
    connection = await _connection(client, headers)
    space_id = await _space(client, headers)
    await _grant(client, headers, space_id, connection["id"])

    response = await client.patch(
        f"{BASE}{connection['id']}/", json={"is_enabled": False}, headers=headers
    )
    space = await client.get(f"/api/v1/spaces/{space_id}/", headers=headers)

    assert response.status_code == 200, response.text
    [link] = space.json()["transcription_services"]
    assert link["available"] is False
    assert not await _available(db_container, space_id, connection["id"])
    assert await _grants(db_container, space_id) == {UUID(connection["id"])}


@pytest.mark.parametrize(
    "overrides, status",
    [({"is_enabled": False}, 403), ({"classification": "low"}, 400)],
    ids=["disabled", "below-classification"],
)
async def test_a_new_grant_must_be_enabled_and_meet_the_classification(
    client, db_container, headers, levels, overrides, status
):
    space_id = await _space(client, headers)
    response = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={"security_classification": {"id": str(levels["high"])}},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    fields = dict(overrides)
    level = fields.pop("classification", "high")
    connection = await _connection(
        client,
        headers,
        security_classification={"id": str(levels[level])},
        **fields,
    )

    response = await _grant(client, headers, space_id, connection["id"])

    assert response.status_code == status, response.text
    assert await _grants(db_container, space_id) == set()


async def test_raising_the_space_classification_previews_and_removes_lower_grants(
    client, db_container, headers, levels
):
    low = await _connection(
        client, headers, security_classification={"id": str(levels["low"])}
    )
    high = await _connection(
        client, headers, security_classification={"id": str(levels["high"])}
    )
    space_id = await _space(client, headers)
    await _grant(client, headers, space_id, low["id"], high["id"])

    preview = await client.get(
        f"/api/v1/spaces/{space_id}/security_classification/{levels['high']}"
        "/impact-analysis/",
        headers=headers,
    )
    response = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        json={"security_classification": {"id": str(levels["high"])}},
        headers=headers,
    )

    assert preview.status_code == 200, preview.text
    assert [item["id"] for item in preview.json()["transcription_services"]] == [
        low["id"]
    ]
    assert response.status_code == 200, response.text
    assert await _grants(db_container, space_id) == {UUID(high["id"])}


async def test_removing_a_service_removes_its_grants(client, db_container, headers):
    connection = await _connection(client, headers)
    space_id = await _space(client, headers)
    await _grant(client, headers, space_id, connection["id"])

    response = await client.delete(f"{BASE}{connection['id']}/", headers=headers)
    space = await client.get(f"/api/v1/spaces/{space_id}/", headers=headers)

    assert response.status_code == 204, response.text
    assert await _grants(db_container, space_id) == set()
    assert space.json()["transcription_services"] == []


async def test_an_unknown_service_cannot_be_granted(client, db_container, headers):
    space_id = await _space(client, headers)

    response = await _grant(client, headers, space_id, str(uuid4()))

    assert response.status_code == 404, response.text
    assert await _grants(db_container, space_id) == set()


async def test_the_first_service_a_space_was_given_stays_its_standard(
    client, db_container, headers
):
    # The standard is the newer service with the later name: only the order
    # of the grants says so.
    older = await _named(client, headers, "z")
    newer = await _named(client, headers, "m")
    space_id = await _space(client, headers)
    assert (await _grant(client, headers, space_id, newer)).status_code == 200

    added = await _grant(client, headers, space_id, older, newer)

    assert added.status_code == 200, added.text
    assert await _standard(client, db_container, headers, space_id) == newer

    renamed = await client.patch(
        f"{BASE}{older}/", json={"name": f"a-{uuid4().hex[:8]}"}, headers=headers
    )
    assert renamed.status_code == 200, renamed.text
    assert await _standard(client, db_container, headers, space_id) == newer

    saved_again = await _grant(client, headers, space_id, older, newer)
    assert saved_again.status_code == 200, saved_again.text
    assert await _standard(client, db_container, headers, space_id) == newer


async def test_a_revoked_standard_hands_over_and_comes_back_last(
    client, db_container, headers
):
    first = await _named(client, headers, "a")
    second = await _named(client, headers, "b")
    space_id = await _space(client, headers)
    await _grant(client, headers, space_id, first)
    await _grant(client, headers, space_id, first, second)
    assert await _standard(client, db_container, headers, space_id) == first

    await _grant(client, headers, space_id, second)
    assert await _standard(client, db_container, headers, space_id) == second

    # Granted again, the older service is the space's latest: flows that moved
    # to the other one stay on it.
    await _grant(client, headers, space_id, first, second)
    assert await _standard(client, db_container, headers, space_id) == second


async def test_a_switched_off_standard_hands_over_until_it_is_switched_on_again(
    client, db_container, headers
):
    first = await _named(client, headers, "a")
    second = await _named(client, headers, "b")
    space_id = await _space(client, headers)
    await _grant(client, headers, space_id, first)
    await _grant(client, headers, space_id, first, second)

    await _switch(client, headers, first, on=False)
    assert await _standard(client, db_container, headers, space_id) == second

    await _switch(client, headers, second, on=False)
    assert await _standard(client, db_container, headers, space_id) is None

    await _switch(client, headers, first, on=True)
    assert await _standard(client, db_container, headers, space_id) == first


async def test_services_granted_together_rank_by_their_age_then_their_id(
    client, db_container, headers, admin_user
):
    older = await _named(client, headers, "z")
    newer = await _named(client, headers, "a")
    by_age = await _space(client, headers)

    await _grant(client, headers, by_age, newer, older)

    assert await _standard(client, db_container, headers, by_age) == older

    # Two services of one age: connected in one transaction.
    async with db_container() as container:
        connections = TranscriptionServiceConnectionRepository(
            container.session(), admin_user.tenant_id
        )
        twins = [
            await connections.create(
                name=f"twin-{uuid4().hex[:8]}",
                endpoint_url="https://vemsa.example.se",
                api_key_encrypted="ciphertext",
                is_enabled=True,
                security_classification_id=None,
            )
            for _ in range(2)
        ]
    assert twins[0].created_at == twins[1].created_at
    lower, higher = sorted(twin.id for twin in twins)
    by_id = await _space(client, headers)

    await _grant(client, headers, by_id, str(higher), str(lower))

    assert await _standard(client, db_container, headers, by_id) == str(lower)


async def test_a_personal_space_uses_the_organisations_oldest_usable_service(
    client, db_container, headers
):
    # A personal space is granted nothing: it may use every service.
    oldest = await _named(client, headers, "z")
    newer = await _named(client, headers, "a")
    async with db_container() as container:
        personal = await container.space_init_service().get_personal_space()
    space_id = str(personal.id)

    assert await _standard(client, db_container, headers, space_id) == oldest

    await _switch(client, headers, oldest, on=False)
    assert await _standard(client, db_container, headers, space_id) == newer
