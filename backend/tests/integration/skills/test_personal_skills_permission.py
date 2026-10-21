"""The personal_skills permission: Skills in your own personal space, nothing else.

A role with only personal_chat and personal_skills can keep its own Skills
without the broader skills and skills_management permissions, which also grant
authoring in shared spaces and access to the organisation catalogue
(docs/adr/personal-chat-skill-layers.md, section 3).
"""

from uuid import uuid4

import pytest

from eneo.database.tables.roles_table import Roles
from eneo.database.tables.spaces_table import SpacesUsers
from eneo.database.tables.users_table import users_roles_table
from eneo.roles.permissions import Permission

_SKILL = {
    "display_name": "Mina svarspreferenser",
    "description": "Korta svar i punktlistor.",
    "instructions": "Svara kort, i punktlistor och med du-tilltal.",
}


async def _user_with(session, user_factory, tenant_id, permissions, container):
    user = await user_factory(session, tenant_id=tenant_id)
    role = Roles(
        name=f"Personal skills {uuid4().hex[:8]}",
        permissions=[permission.value for permission in permissions],
        tenant_id=tenant_id,
    )
    session.add(role)
    await session.flush()
    await session.execute(
        users_roles_table.insert().values(user_id=user.id, role_id=role.id)
    )
    return user, container.auth_service().create_access_token_for_user(user)


async def _personal_space_id(client, headers) -> str:
    response = await client.get("/api/v1/spaces/type/personal/", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_personal_skills_alone_manages_skills_in_own_personal_space(
    client, db_container, patch_auth_service_jwt, admin_user, user_factory
):
    async with db_container() as container:
        _, token = await _user_with(
            container.session(),
            user_factory,
            admin_user.tenant_id,
            [Permission.PERSONAL_CHAT, Permission.PERSONAL_SKILLS],
            container,
        )
    headers = {"Authorization": f"Bearer {token}"}
    space_id = await _personal_space_id(client, headers)

    space = await client.get(f"/api/v1/spaces/{space_id}/", headers=headers)
    assert space.status_code == 200, space.text
    assert set(space.json()["skill_permissions"]) == {
        "read",
        "create",
        "edit",
        "delete",
    }

    created = await client.post(
        f"/api/v1/spaces/{space_id}/skills/",
        json={"slug": f"svar-{uuid4().hex[:8]}", **_SKILL},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    skill_id = created.json()["id"]

    listed = await client.get(f"/api/v1/spaces/{space_id}/skills/", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["items"]] == [skill_id]

    revised = await client.post(
        f"/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/",
        json={**_SKILL, "instructions": "Svara kort och sakligt."},
        headers=headers,
    )
    assert revised.status_code == 201, revised.text

    deleted = await client.delete(
        f"/api/v1/spaces/{space_id}/skills/{skill_id}/", headers=headers
    )
    assert deleted.status_code == 204, deleted.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_personal_skills_grants_no_skill_access_anywhere_else(
    client,
    db_container,
    patch_auth_service_jwt,
    admin_user,
    user_factory,
    space_factory,
    completion_model_factory,
):
    async with db_container() as container:
        session = container.session()
        permissions = [Permission.PERSONAL_CHAT, Permission.PERSONAL_SKILLS]
        user, token = await _user_with(
            session, user_factory, admin_user.tenant_id, permissions, container
        )
        _, other_token = await _user_with(
            session, user_factory, admin_user.tenant_id, permissions, container
        )
        model = await completion_model_factory(
            session, f"personal-skills-{uuid4().hex[:8]}"
        )
        shared = await space_factory(session, "Delad yta", [model.id])
        session.add(SpacesUsers(space_id=shared.id, user_id=user.id, role="editor"))
        await session.flush()
        shared_id = shared.id
    headers = {"Authorization": f"Bearer {token}"}
    other_space_id = await _personal_space_id(
        client, {"Authorization": f"Bearer {other_token}"}
    )

    in_shared = await client.post(
        f"/api/v1/spaces/{shared_id}/skills/",
        json={"slug": f"delad-{uuid4().hex[:8]}", **_SKILL},
        headers=headers,
    )
    assert in_shared.status_code == 403, in_shared.text

    in_other_personal = await client.get(
        f"/api/v1/spaces/{other_space_id}/skills/", headers=headers
    )
    assert in_other_personal.status_code in {403, 404}, in_other_personal.text

    catalogue = await client.get("/api/v1/skills/catalogue/", headers=headers)
    assert catalogue.status_code == 403, catalogue.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_personal_space_skills_stay_closed_without_personal_skills(
    client, db_container, patch_auth_service_jwt, admin_user, user_factory
):
    async with db_container() as container:
        _, token = await _user_with(
            container.session(),
            user_factory,
            admin_user.tenant_id,
            [Permission.PERSONAL_CHAT],
            container,
        )
    headers = {"Authorization": f"Bearer {token}"}
    space_id = await _personal_space_id(client, headers)

    created = await client.post(
        f"/api/v1/spaces/{space_id}/skills/",
        json={"slug": f"svar-{uuid4().hex[:8]}", **_SKILL},
        headers=headers,
    )
    assert created.status_code == 403, created.text
