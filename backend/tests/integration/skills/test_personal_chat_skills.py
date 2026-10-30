"""People choose their own Skills for their personal chat.

The personal chat's default Assistant holds the person's own personal-space
Skills next to the organisation's (docs/adr/personal-chat-skill-layers.md,
sections 2, 4 and 5). These tests drive the real HTTP API with custom roles
that do not hold `assistants`, which is how the feature is meant to be used.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.roles_table import Roles
from eneo.database.tables.skill_table import SkillRuntimePolicies
from eneo.database.tables.users_table import users_roles_table
from eneo.main.exceptions import ErrorCodes
from eneo.roles.permissions import Permission
from eneo.skills.domain.skill import (
    MAX_SKILL_ATTACHMENT_LIMIT,
    SkillBindingIntent,
    SkillBindingReference,
)

PERSONAL = [Permission.PERSONAL_CHAT, Permission.PERSONAL_SKILLS]


async def _person(db_container, user_factory, tenant_id, permissions):
    async with db_container() as container:
        session = container.session()
        user = await user_factory(session, tenant_id=tenant_id)
        role = Roles(
            name=f"Personal chat {uuid4().hex[:8]}",
            permissions=[permission.value for permission in permissions],
            tenant_id=tenant_id,
        )
        session.add(role)
        await session.flush()
        await session.execute(
            users_roles_table.insert().values(user_id=user.id, role_id=role.id)
        )
        token = container.auth_service().create_access_token_for_user(user)
        role_id = role.id
    return role_id, {"Authorization": f"Bearer {token}"}


async def _personal_chat(client, headers) -> tuple[str, str, str]:
    response = await client.get("/api/v1/spaces/type/personal/", headers=headers)
    assert response.status_code == 200, response.text
    space = response.json()
    default = space["default_assistant"]
    return space["id"], default["id"], default["completion_model"]["id"]


async def _own_skill(client, headers, space_id, name="Mina svarspreferenser"):
    response = await client.post(
        f"/api/v1/spaces/{space_id}/skills/",
        json={
            "slug": f"egen-{uuid4().hex[:8]}",
            "display_name": name,
            "description": "Hur jag vill ha mina svar.",
            "instructions": "Svara kort, i punktlistor och med du-tilltal.",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _tool_model(db_container, completion_model_factory) -> str:
    """A model that can call tools, so Skills can be offered on demand."""
    async with db_container() as container:
        model = await completion_model_factory(
            container.session(),
            f"gpt-4o-tools-{uuid4().hex[:6]}",
            litellm_model_name="gpt-4o",
            max_input_tokens=128_000,
        )
        # The factory does not take this flag; set it on the row.
        model.supports_tool_calling = True
        await container.session().flush()
        return str(model.id)


def _binding(skill, mode="always"):
    return {
        "skill_id": skill["id"],
        "skill_revision_id": skill["current_revision"]["id"],
        "activation_mode": mode,
    }


async def _save(client, headers, default_id, payload):
    return await client.post(
        f"/api/v1/assistants/{default_id}/", json=payload, headers=headers
    )


async def _bound_ids(client, headers, space_id, default_id) -> list[str]:
    response = await client.get(
        f"/api/v1/spaces/{space_id}/assistants/{default_id}/skills/", headers=headers
    )
    assert response.status_code == 200, response.text
    return [binding["skill_id"] for binding in response.json()]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_person_chooses_and_switches_off_own_skills(
    client, db_container, patch_auth_service_jwt, admin_user, user_factory
):
    _, headers = await _person(
        db_container, user_factory, admin_user.tenant_id, PERSONAL
    )
    space_id, default_id, _ = await _personal_chat(client, headers)
    first = await _own_skill(client, headers, space_id)
    second = await _own_skill(client, headers, space_id, name="Mötesanteckningar")

    saved = await _save(
        client,
        headers,
        default_id,
        {"skill_bindings": [_binding(first), _binding(second)]},
    )
    assert saved.status_code == 200, saved.text
    assert await _bound_ids(client, headers, space_id, default_id) == [
        first["id"],
        second["id"],
    ]

    cleared = await _save(client, headers, default_id, {"skill_bindings": []})
    assert cleared.status_code == 200, cleared.text
    assert await _bound_ids(client, headers, space_id, default_id) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_on_demand_that_the_model_cannot_offer_is_refused_with_its_reason(
    client, db_container, patch_auth_service_jwt, admin_user, user_factory
):
    _, headers = await _person(
        db_container, user_factory, admin_user.tenant_id, PERSONAL
    )
    space_id, default_id, _ = await _personal_chat(client, headers)
    skill = await _own_skill(client, headers, space_id)

    refused = await _save(
        client,
        headers,
        default_id,
        {"skill_bindings": [_binding(skill, mode="on_demand")]},
    )

    assert refused.status_code == 400, refused.text
    body = refused.json()
    assert body["eneo_error_code"] == ErrorCodes.PERSONAL_SKILLS_REJECTED.value
    assert body["details"] == {
        "reason": "on_demand_unavailable",
        "detail": "model_lacks_tool_calling",
    }
    assert await _bound_ids(client, headers, space_id, default_id) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_personal_chat_takes_only_skills_from_your_personal_space(
    client, db_container, patch_auth_service_jwt, admin_user, user_factory
):
    _, headers = await _person(
        db_container,
        user_factory,
        admin_user.tenant_id,
        [*PERSONAL, Permission.SKILLS],
    )
    _, other_headers = await _person(
        db_container, user_factory, admin_user.tenant_id, PERSONAL
    )
    space_id, default_id, _ = await _personal_chat(client, headers)
    other_space_id, _, _ = await _personal_chat(client, other_headers)
    someone_elses = await _own_skill(client, other_headers, other_space_id)
    async with db_container() as container:
        skills = container.organization_skill_service()
        organisation = await skills.create_organization_skill(
            slug=f"org-{uuid4().hex[:8]}",
            display_name="Klarspråk",
            description="Organisationens skrivregler.",
            instructions="Skriv klarspråk.",
        )
        organisation = (
            await skills.publish(
                skill_id=organisation.id,
                expected_revision_id=organisation.current_revision.id,
            )
        ).skill
    organisation_binding = {
        "skill_id": str(organisation.id),
        "skill_revision_id": str(organisation.current_revision.id),
    }

    from_organisation = await _save(
        client, headers, default_id, {"skill_bindings": [organisation_binding]}
    )
    assert from_organisation.status_code == 400, from_organisation.text
    assert "personal space" in from_organisation.json()["message"]

    from_someone_else = await _save(
        client, headers, default_id, {"skill_bindings": [_binding(someone_elses)]}
    )
    assert from_someone_else.status_code in {400, 404}, from_someone_else.text
    assert await _bound_ids(client, headers, space_id, default_id) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_assistant_rights_do_not_open_personal_chat_skills(
    client, db_container, patch_auth_service_jwt, admin_user, user_factory
):
    _, headers = await _person(
        db_container,
        user_factory,
        admin_user.tenant_id,
        [
            Permission.PERSONAL_CHAT,
            Permission.ASSISTANTS,
            Permission.SKILLS,
            Permission.SKILLS_MANAGEMENT,
        ],
    )
    space_id, default_id, _ = await _personal_chat(client, headers)
    skill = await _own_skill(client, headers, space_id)

    refused = await _save(
        client, headers, default_id, {"skill_bindings": [_binding(skill)]}
    )

    assert refused.status_code == 403, refused.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_nobody_else_can_change_your_personal_chat_skills(
    client, db_container, patch_auth_service_jwt, admin_user, user_factory
):
    _, headers = await _person(
        db_container, user_factory, admin_user.tenant_id, PERSONAL
    )
    _, intruder = await _person(
        db_container, user_factory, admin_user.tenant_id, PERSONAL
    )
    _, default_id, _ = await _personal_chat(client, headers)

    attempt = await _save(client, intruder, default_id, {"skill_bindings": []})

    assert attempt.status_code in {403, 404}, attempt.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_revoked_person_keeps_choices_and_can_still_switch_model(
    client,
    db_container,
    patch_auth_service_jwt,
    admin_user,
    user_factory,
    completion_model_factory,
):
    role_id, headers = await _person(
        db_container, user_factory, admin_user.tenant_id, PERSONAL
    )
    space_id, default_id, model_id = await _personal_chat(client, headers)
    skill = await _own_skill(client, headers, space_id)
    saved = await _save(
        client, headers, default_id, {"skill_bindings": [_binding(skill)]}
    )
    assert saved.status_code == 200, saved.text

    async with db_container() as container:
        await container.session().execute(
            sa.update(Roles)
            .where(Roles.id == role_id)
            .values(permissions=[Permission.PERSONAL_CHAT.value])
        )

    other_model_id = await _tool_model(db_container, completion_model_factory)
    switched = await _save(
        client, headers, default_id, {"completion_model": {"id": other_model_id}}
    )
    assert switched.status_code == 200, switched.text
    assert other_model_id != model_id
    assert await _bound_ids(client, headers, space_id, default_id) == [skill["id"]]

    edited = await _save(client, headers, default_id, {"skill_bindings": []})
    assert edited.status_code == 403, edited.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_after_a_lowered_limit_removals_save_and_additions_do_not(
    client, db_container, patch_auth_service_jwt, admin_user, user_factory
):
    _, headers = await _person(
        db_container, user_factory, admin_user.tenant_id, PERSONAL
    )
    space_id, default_id, _ = await _personal_chat(client, headers)
    skills = [
        await _own_skill(client, headers, space_id, name=f"Mall {number}")
        for number in range(3)
    ]
    saved = await _save(
        client, headers, default_id, {"skill_bindings": [_binding(s) for s in skills]}
    )
    assert saved.status_code == 200, saved.text

    async with db_container() as container:
        await container.session().execute(
            sa.update(SkillRuntimePolicies)
            .where(SkillRuntimePolicies.tenant_id == admin_user.tenant_id)
            .values(max_attached_skills=1)
        )

    still_over = await _save(
        client,
        headers,
        default_id,
        {"skill_bindings": [_binding(s) for s in skills[:2]]},
    )
    assert still_over.status_code == 200, still_over.text

    added_back = await _save(
        client, headers, default_id, {"skill_bindings": [_binding(s) for s in skills]}
    )
    assert added_back.status_code == 400, added_back.text
    assert added_back.json()["details"]["reason"] == "attachment_limit_exceeded"

    within = await _save(
        client, headers, default_id, {"skill_bindings": [_binding(skills[0])]}
    )
    assert within.status_code == 200, within.text
    assert await _bound_ids(client, headers, space_id, default_id) == [skills[0]["id"]]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_choosing_own_skills_is_audited_without_their_text(
    client, db_container, patch_auth_service_jwt, admin_user, user_factory
):
    _, headers = await _person(
        db_container, user_factory, admin_user.tenant_id, PERSONAL
    )
    space_id, default_id, _ = await _personal_chat(client, headers)
    skill = await _own_skill(client, headers, space_id)

    with patch(
        "eneo.audit.application.audit_service.job_manager.enqueue",
        new_callable=AsyncMock,
    ) as enqueue_audit:
        saved = await _save(
            client, headers, default_id, {"skill_bindings": [_binding(skill)]}
        )
        assert saved.status_code == 200, saved.text

    updates = [
        call.args[2]
        for call in enqueue_audit.await_args_list
        if call.args[2]["action"] == "assistant_updated"
    ]
    assert len(updates) == 1
    assert updates[0]["entity_id"] == default_id
    skills = updates[0]["metadata"]["changes"]["skills"]
    assert skills["old"] == []
    assert [str(entry["skill_id"]) for entry in skills["new"]] == [skill["id"]]
    assert "Svara kort" not in str(updates[0]["metadata"])


async def _pin_organisation_skill(db_container) -> str:
    async with db_container() as container:
        skills = container.organization_skill_service()
        skill = await skills.create_organization_skill(
            slug=f"org-{uuid4().hex[:8]}",
            display_name="Klarspråk",
            description="Organisationens skrivregler.",
            instructions="Skriv klarspråk.",
        )
        skill = (
            await skills.publish(
                skill_id=skill.id, expected_revision_id=skill.current_revision.id
            )
        ).skill
        policies = container.governance_policy_service()
        await policies.get_policy_for_update()
        await policies.update_policy(
            skill_intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=skill.id,
                        skill_revision_id=skill.current_revision.id,
                    )
                )
            ]
        )
        return str(skill.id)


async def _configuration(client, headers, space_id, default_id) -> dict:
    response = await client.get(
        f"/api/v1/spaces/{space_id}/assistants/{default_id}/skills/configuration/",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_configuration_shows_both_layers_and_why_own_skills_pause(
    client, db_container, patch_auth_service_jwt, admin_user, user_factory
):
    organisation_id = await _pin_organisation_skill(db_container)
    role_id, headers = await _person(
        db_container, user_factory, admin_user.tenant_id, PERSONAL
    )
    space_id, default_id, _ = await _personal_chat(client, headers)
    skill = await _own_skill(client, headers, space_id)
    saved = await _save(
        client, headers, default_id, {"skill_bindings": [_binding(skill)]}
    )
    assert saved.status_code == 200, saved.text

    applied = await _configuration(client, headers, space_id, default_id)
    assert [b["skill_id"] for b in applied["organisation_bindings"]] == [
        organisation_id
    ]
    assert [b["skill_id"] for b in applied["bindings"]] == [skill["id"]]
    assert applied["personal_layer"] == {
        "status": "applied",
        "reason": None,
        "detail": None,
    }
    assert applied["runtime"] is not None

    async with db_container() as container:
        await container.session().execute(
            sa.update(Roles)
            .where(Roles.id == role_id)
            .values(permissions=[Permission.PERSONAL_CHAT.value])
        )
    paused = await _configuration(client, headers, space_id, default_id)
    assert paused["personal_layer"]["status"] == "suspended"
    assert paused["personal_layer"]["reason"] == "permission_missing"
    assert [b["skill_id"] for b in paused["bindings"]] == [skill["id"]]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_chat_only_person_sees_the_organisation_skills(
    client, db_container, patch_auth_service_jwt, admin_user, user_factory
):
    organisation_id = await _pin_organisation_skill(db_container)
    _, headers = await _person(
        db_container, user_factory, admin_user.tenant_id, [Permission.PERSONAL_CHAT]
    )
    space_id, default_id, _ = await _personal_chat(client, headers)

    configuration = await _configuration(client, headers, space_id, default_id)

    assert [b["skill_id"] for b in configuration["organisation_bindings"]] == [
        organisation_id
    ]
    assert configuration["bindings"] == []
    assert configuration["personal_layer"]["status"] == "empty"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_model_switch_that_would_pause_running_skills_is_refused(
    client,
    db_container,
    patch_auth_service_jwt,
    admin_user,
    user_factory,
    completion_model_factory,
):
    _, headers = await _person(
        db_container, user_factory, admin_user.tenant_id, PERSONAL
    )
    space_id, default_id, plain_model_id = await _personal_chat(client, headers)
    tools_model_id = await _tool_model(db_container, completion_model_factory)
    moved = await _save(
        client, headers, default_id, {"completion_model": {"id": tools_model_id}}
    )
    assert moved.status_code == 200, moved.text
    after_move = await _configuration(client, headers, space_id, default_id)
    assert after_move["runtime"]["effective_model_id"] == tools_model_id, after_move
    skill = await _own_skill(client, headers, space_id)
    on_demand = _binding(skill, mode="on_demand")
    saved = await _save(client, headers, default_id, {"skill_bindings": [on_demand]})
    assert saved.status_code == 200, saved.text

    # The plain model cannot call tools, so on-demand Skills would stop working.
    for payload in (
        {"completion_model": {"id": plain_model_id}},
        {"completion_model": {"id": plain_model_id}, "skill_bindings": [on_demand]},
    ):
        refused = await _save(client, headers, default_id, payload)
        assert refused.status_code == 400, refused.text
        assert refused.json()["details"]["reason"] == "on_demand_unavailable"

    configuration = await _configuration(client, headers, space_id, default_id)
    assert configuration["personal_layer"]["status"] == "applied"
    assert configuration["runtime"]["effective_model_id"] == tools_model_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_own_skills_are_refused_cleanly(
    client, db_container, patch_auth_service_jwt, admin_user, user_factory
):
    _, headers = await _person(
        db_container, user_factory, admin_user.tenant_id, PERSONAL
    )
    space_id, default_id, _ = await _personal_chat(client, headers)
    skill = await _own_skill(client, headers, space_id)

    duplicated = await _save(
        client,
        headers,
        default_id,
        {"skill_bindings": [_binding(skill), _binding(skill, mode="on_demand")]},
    )

    assert duplicated.status_code == 400, duplicated.text
    assert await _bound_ids(client, headers, space_id, default_id) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_oversized_skill_list_is_refused_before_any_lookup(
    client, db_container, patch_auth_service_jwt, admin_user, user_factory
):
    _, headers = await _person(
        db_container, user_factory, admin_user.tenant_id, PERSONAL
    )
    space_id, default_id, _ = await _personal_chat(client, headers)
    oversized = [
        {"skill_id": str(uuid4()), "skill_revision_id": str(uuid4())}
        for _ in range(MAX_SKILL_ATTACHMENT_LIMIT + 1)
    ]

    response = await _save(client, headers, default_id, {"skill_bindings": oversized})

    assert response.status_code == 422, response.text
    assert await _bound_ids(client, headers, space_id, default_id) == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_without_a_model_own_skills_can_be_removed_but_not_added(
    client, db_container, patch_auth_service_jwt, admin_user, user_factory
):
    _, headers = await _person(
        db_container, user_factory, admin_user.tenant_id, PERSONAL
    )
    space_id, default_id, _ = await _personal_chat(client, headers)
    first = await _own_skill(client, headers, space_id)
    second = await _own_skill(client, headers, space_id, name="Mötesanteckningar")
    saved = await _save(
        client, headers, default_id, {"skill_bindings": [_binding(first)]}
    )
    assert saved.status_code == 200, saved.text

    async with db_container() as container:
        await container.session().execute(
            sa.update(Assistants)
            .where(Assistants.id == default_id)
            .values(completion_model_id=None)
        )

    added = await _save(
        client,
        headers,
        default_id,
        {"skill_bindings": [_binding(first), _binding(second)]},
    )
    assert added.status_code == 400, added.text
    assert "completion model" in added.json()["message"]

    removed = await _save(client, headers, default_id, {"skill_bindings": []})
    assert removed.status_code == 200, removed.text
    assert await _bound_ids(client, headers, space_id, default_id) == []
