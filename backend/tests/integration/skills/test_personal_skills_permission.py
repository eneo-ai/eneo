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
from eneo.skills.domain.skill import SkillBindingReference

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


async def _published_organisation_skill(container):
    skills = container.organization_skill_service()
    skill = await skills.create_organization_skill(
        slug=f"org-{uuid4().hex[:8]}",
        display_name="Klarspråk",
        description="Organisationens skrivregler.",
        instructions="Skriv klarspråk.",
    )
    return (
        await skills.publish(
            skill_id=skill.id, expected_revision_id=skill.current_revision.id
        )
    ).skill


@pytest.mark.integration
@pytest.mark.asyncio
async def test_personal_skills_does_not_let_assistants_or_apps_use_organisation_skills(
    client,
    db_container,
    patch_auth_service_jwt,
    admin_user,
    user_factory,
    assistant_factory,
    app_factory,
):
    """Attaching an organisation Skill still needs Use Skills. personal_skills
    opens the user's own personal space, so the binding boundary must check the
    Skill's source, not only whether the destination space's Skills are
    readable."""
    async with db_container() as container:
        _, token = await _user_with(
            container.session(),
            user_factory,
            admin_user.tenant_id,
            [
                Permission.PERSONAL_CHAT,
                Permission.PERSONAL_SKILLS,
                Permission.ASSISTANTS,
                Permission.APPS,
            ],
            container,
        )
        organisation_skill = await _published_organisation_skill(container)
    headers = {"Authorization": f"Bearer {token}"}
    personal = await client.get("/api/v1/spaces/type/personal/", headers=headers)
    assert personal.status_code == 200, personal.text
    space_id = personal.json()["id"]
    model_id = personal.json()["default_assistant"]["completion_model"]["id"]

    async with db_container() as container:
        session = container.session()
        assistant = await assistant_factory(
            session, "Min assistent", model_id, space_id=space_id
        )
        app = await app_factory(session, "Min app", model_id, space_id=space_id)
        assistant_id, app_id = assistant.id, app.id

    binding = {
        "skill_id": str(organisation_skill.id),
        "skill_revision_id": str(organisation_skill.current_revision.id),
    }
    assistant_update = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"skill_bindings": [binding]},
        headers=headers,
    )
    assert assistant_update.status_code == 403, assistant_update.text

    app_update = await client.patch(
        f"/api/v1/apps/{app_id}/",
        json={"skill_bindings": [binding]},
        headers=headers,
    )
    assert app_update.status_code == 403, app_update.text

    for path in (
        f"/api/v1/spaces/{space_id}/assistants/{assistant_id}/skills/",
        f"/api/v1/spaces/{space_id}/apps/{app_id}/skills/",
    ):
        bindings = await client.get(path, headers=headers)
        assert bindings.status_code == 200, bindings.text
        assert bindings.json() in ({"items": []}, [])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_personal_skills_cannot_resubmit_a_retained_organisation_binding(
    client,
    db_container,
    patch_auth_service_jwt,
    admin_user,
    user_factory,
    assistant_factory,
):
    """An organisation binding that is already attached still needs Use Skills
    to be submitted again, as it did before personal_skills existed."""
    async with db_container() as container:
        user, token = await _user_with(
            container.session(),
            user_factory,
            admin_user.tenant_id,
            [
                Permission.PERSONAL_CHAT,
                Permission.PERSONAL_SKILLS,
                Permission.ASSISTANTS,
            ],
            container,
        )
        organisation_skill = await _published_organisation_skill(container)
    headers = {"Authorization": f"Bearer {token}"}
    personal = await client.get("/api/v1/spaces/type/personal/", headers=headers)
    assert personal.status_code == 200, personal.text
    space_id = personal.json()["id"]
    model_id = personal.json()["default_assistant"]["completion_model"]["id"]
    reference = SkillBindingReference(
        skill_id=organisation_skill.id,
        skill_revision_id=organisation_skill.current_revision.id,
    )

    async with db_container() as container:
        assistant = await assistant_factory(
            container.session(), "Min assistent", model_id, space_id=space_id
        )
        repo = container.skill_repo()
        resolved = await repo.resolve_published_references_for_binding_update(
            tenant_id=admin_user.tenant_id, references=[reference]
        )
        await repo.replace_assistant_bindings(
            assistant_id=assistant.id,
            tenant_id=admin_user.tenant_id,
            space_id=space_id,
            bindings=resolved,
        )
        assistant_id = assistant.id

    resubmitted = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={
            "skill_bindings": [
                {
                    "skill_id": str(reference.skill_id),
                    "skill_revision_id": str(reference.skill_revision_id),
                    "activation_mode": "on_demand",
                }
            ]
        },
        headers=headers,
    )
    assert resubmitted.status_code == 403, resubmitted.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_personal_skills_does_not_attach_own_skills_to_assistants_or_apps(
    client,
    db_container,
    patch_auth_service_jwt,
    admin_user,
    user_factory,
    assistant_factory,
    app_factory,
):
    """Attaching Skills to Assistants and Apps is Use Skills. personal_skills
    covers the personal-space library and the personal chat, not other
    Assistants and Apps in the same space."""
    async with db_container() as container:
        _, token = await _user_with(
            container.session(),
            user_factory,
            admin_user.tenant_id,
            [
                Permission.PERSONAL_CHAT,
                Permission.PERSONAL_SKILLS,
                Permission.ASSISTANTS,
                Permission.APPS,
            ],
            container,
        )
    headers = {"Authorization": f"Bearer {token}"}
    personal = await client.get("/api/v1/spaces/type/personal/", headers=headers)
    assert personal.status_code == 200, personal.text
    space_id = personal.json()["id"]
    model_id = personal.json()["default_assistant"]["completion_model"]["id"]
    created = await client.post(
        f"/api/v1/spaces/{space_id}/skills/",
        json={"slug": f"svar-{uuid4().hex[:8]}", **_SKILL},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    binding = {
        "skill_id": created.json()["id"],
        "skill_revision_id": created.json()["current_revision"]["id"],
    }

    async with db_container() as container:
        session = container.session()
        assistant = await assistant_factory(
            session, "Min assistent", model_id, space_id=space_id
        )
        app = await app_factory(session, "Min app", model_id, space_id=space_id)
        assistant_id, app_id = assistant.id, app.id

    assistant_update = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"skill_bindings": [binding]},
        headers=headers,
    )
    assert assistant_update.status_code == 403, assistant_update.text

    app_update = await client.patch(
        f"/api/v1/apps/{app_id}/",
        json={"skill_bindings": [binding]},
        headers=headers,
    )
    assert app_update.status_code == 403, app_update.text

    for path in (
        f"/api/v1/spaces/{space_id}/assistants/{assistant_id}/skills/",
        f"/api/v1/spaces/{space_id}/apps/{app_id}/skills/",
    ):
        bindings = await client.get(path, headers=headers)
        assert bindings.status_code == 200, bindings.text
        assert bindings.json() in ({"items": []}, [])
