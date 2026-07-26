from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.roles_table import Roles
from eneo.database.tables.skill_table import AssistantSkillBindings
from eneo.database.tables.spaces_table import SpacesUsers
from eneo.database.tables.users_table import users_roles_table
from eneo.roles.permissions import Permission
from eneo.skills.domain.skill import (
    SkillActivationMode,
    SkillBindingIntent,
    SkillBindingReference,
    SkillRuntimePolicy,
)


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


async def _persisted_assistant_state(db_container, *, assistant_id):
    async with db_container() as container:
        session = container.session()
        name = await session.scalar(
            sa.select(Assistants.name).where(Assistants.id == assistant_id)
        )
        bindings = (
            (
                await session.execute(
                    sa.select(
                        AssistantSkillBindings.skill_id,
                        AssistantSkillBindings.skill_revision_id,
                        AssistantSkillBindings.position,
                        AssistantSkillBindings.activation_mode,
                        AssistantSkillBindings.tenant_id,
                        AssistantSkillBindings.space_id,
                        AssistantSkillBindings.skill_space_id,
                    )
                    .where(AssistantSkillBindings.assistant_id == assistant_id)
                    .order_by(AssistantSkillBindings.position)
                )
            )
            .tuples()
            .all()
        )
    return name, tuple(bindings)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_assistant_mode_rejection_rolls_back_parent_and_bindings(
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session,
            f"assistant-save-contract-{uuid4().hex[:8]}",
        )
        space = await space_factory(
            session,
            "Assistant Skill save contract",
            [model.id],
        )
        session.add(
            SpacesUsers(
                space_id=space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        assistant = await assistant_factory(
            session,
            "Original Assistant name",
            model.id,
            space_id=space.id,
        )

        repo = container.skill_repo()
        first_skill = await repo.create(
            space_id=space.id,
            slug=f"first-{uuid4().hex[:8]}",
            display_name="First Skill",
            description="First on-demand candidate",
            instructions="Use the first Skill when it is relevant.",
            content_digest="a" * 64,
            created_by_user_id=admin_user.id,
        )
        second_skill = await repo.create(
            space_id=space.id,
            slug=f"second-{uuid4().hex[:8]}",
            display_name="Second Skill",
            description="Second on-demand candidate",
            instructions="Use the second Skill when it is relevant.",
            content_digest="b" * 64,
            created_by_user_id=admin_user.id,
        )
        references = [
            SkillBindingReference(
                skill_id=first_skill.id,
                skill_revision_id=first_skill.current_revision.id,
            ),
            SkillBindingReference(
                skill_id=second_skill.id,
                skill_revision_id=second_skill.current_revision.id,
            ),
        ]
        await container.skill_service().replace_assistant_bindings(
            space_id=space.id,
            assistant_id=assistant.id,
            intents=[SkillBindingIntent(reference=value) for value in references],
        )
        assistant_id = assistant.id
        first_skill_id = first_skill.id
        first_revision_id = first_skill.current_revision.id
        second_skill_id = second_skill.id
        second_revision_id = second_skill.current_revision.id

    original_name, original_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    assert original_name == "Original Assistant name"
    assert len(original_bindings) == 2

    response = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={
            "name": "Rejected Assistant name",
            "skill_bindings": [
                {
                    "skill_id": str(second_skill_id),
                    "skill_revision_id": str(second_revision_id),
                },
                {
                    "skill_id": str(first_skill_id),
                    "skill_revision_id": str(first_revision_id),
                    "activation_mode": "on_demand",
                },
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400, response.text

    persisted_name, persisted_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    assert persisted_name == original_name
    assert persisted_bindings == original_bindings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_on_demand_revision_upgrade_rejection_rolls_back_parent_and_binding(
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session,
            "gpt-4o",
            max_input_tokens=2_000,
        )
        model.supports_tool_calling = True
        space = await space_factory(
            session,
            "Assistant Skill revision fit contract",
            [model.id],
        )
        session.add(
            SpacesUsers(
                space_id=space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        assistant = await assistant_factory(
            session,
            "Original revision-fit Assistant",
            model.id,
            space_id=space.id,
        )
        repo = container.skill_repo()
        await repo.update_runtime_policy(
            tenant_id=admin_user.tenant_id,
            policy=SkillRuntimePolicy(
                selective_activation_enabled=True,
                max_attached_skills=100,
                context_share_percent=10,
                max_activations_per_turn=10,
            ),
        )
        skill = await repo.create(
            space_id=space.id,
            slug=f"revision-fit-{uuid4().hex[:8]}",
            display_name="Revision fit Skill",
            description="Use for revision-fit questions",
            instructions="The initial body fits.",
            content_digest="c" * 64,
            created_by_user_id=admin_user.id,
        )
        original_revision_id = skill.current_revision.id
        await container.skill_service().replace_assistant_bindings(
            space_id=space.id,
            assistant_id=assistant.id,
            intents=[
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=skill.id,
                        skill_revision_id=original_revision_id,
                    ),
                    activation_mode=SkillActivationMode.ON_DEMAND,
                )
            ],
        )
        revision_change = await repo.create_revision(
            skill_id=skill.id,
            display_name="Revision fit Skill",
            description="Use for revision-fit questions",
            instructions="oversized " * 20_000,
            content_digest="d" * 64,
            created_by_user_id=admin_user.id,
        )
        assert revision_change is not None
        oversized_revision_id = revision_change.revision.id
        assistant_id = assistant.id
        skill_id = skill.id

    original_name, original_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    assert original_name == "Original revision-fit Assistant"
    assert len(original_bindings) == 1
    assert original_bindings[0].skill_revision_id == original_revision_id
    assert original_bindings[0].activation_mode == SkillActivationMode.ON_DEMAND.value

    response = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={
            "name": "Rejected revision-fit Assistant",
            "skill_bindings": [
                {
                    "skill_id": str(skill_id),
                    "skill_revision_id": str(oversized_revision_id),
                }
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400, response.text
    persisted_name, persisted_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    assert persisted_name == original_name
    assert persisted_bindings == original_bindings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_on_demand_candidate_and_persistent_attachment_overflow_rolls_back(
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    monkeypatch,
):
    monkeypatch.setattr(
        "eneo.files.attachment_budget.get_settings",
        lambda: SimpleNamespace(attachment_context_reserve_tokens=0),
    )
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_tokens",
        lambda text, *_args, **_kwargs: (
            6_500 if "candidate-persistent-overflow" in text else 100
        ),
    )
    monkeypatch.setattr(
        "eneo.files.attachment_budget.count_attachment_tokens",
        lambda *, text_files, image_files, model_name: (2_000 if text_files else 0),
    )

    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session,
            "gpt-4o",
            max_input_tokens=8_000,
        )
        model.supports_tool_calling = True
        space = await space_factory(
            session,
            "Assistant candidate attachment contract",
            [model.id],
        )
        session.add(
            SpacesUsers(
                space_id=space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        assistant = await assistant_factory(
            session,
            "Original attachment-fit Assistant",
            model.id,
            space_id=space.id,
        )
        repo = container.skill_repo()
        await repo.update_runtime_policy(
            tenant_id=admin_user.tenant_id,
            policy=SkillRuntimePolicy(
                selective_activation_enabled=True,
                max_attached_skills=100,
                context_share_percent=100,
                max_activations_per_turn=10,
            ),
        )
        skill = await repo.create(
            space_id=space.id,
            slug=f"candidate-attachment-{uuid4().hex[:8]}",
            display_name="Candidate attachment Skill",
            description="Use for candidate attachment questions",
            instructions="candidate-persistent-overflow",
            content_digest="e" * 64,
            created_by_user_id=admin_user.id,
        )
        assistant_id = assistant.id
        skill_id = skill.id
        revision_id = skill.current_revision.id

    headers = {"Authorization": f"Bearer {admin_token}"}
    upload = await client.post(
        "/api/v1/files/",
        files={
            "upload_file": (
                "persistent.txt",
                b"persistent attachment",
                "text/plain",
            )
        },
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    attachment_id = upload.json()["id"]
    attach_response = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"attachments": [{"id": attachment_id}]},
        headers=headers,
    )
    assert attach_response.status_code == 200, attach_response.text

    original_name, original_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    response = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={
            "name": "Rejected attachment-fit Assistant",
            "skill_bindings": [
                {
                    "skill_id": str(skill_id),
                    "skill_revision_id": str(revision_id),
                    "activation_mode": "on_demand",
                }
            ],
        },
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert 'on-demand Skill "Candidate attachment Skill"' in response.json()["message"]
    persisted_name, persisted_bindings = await _persisted_assistant_state(
        db_container,
        assistant_id=assistant_id,
    )
    assert persisted_name == original_name
    assert persisted_bindings == original_bindings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_assistant_skill_configuration_requires_skill_read_access(
    client,
    db_container,
    patch_auth_service_jwt,
    admin_user,
    user_factory,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        session = container.session()
        user = await user_factory(session, tenant_id=admin_user.tenant_id)
        assistant_reader_role = Roles(
            name=f"Assistant reader {uuid4().hex[:8]}",
            permissions=[Permission.ASSISTANTS.value],
            tenant_id=admin_user.tenant_id,
        )
        session.add(assistant_reader_role)
        await session.flush()
        await session.execute(
            users_roles_table.insert().values(
                user_id=user.id,
                role_id=assistant_reader_role.id,
            )
        )
        model = await completion_model_factory(
            session,
            f"assistant-skill-read-{uuid4().hex[:8]}",
        )
        space = await space_factory(
            session,
            "Assistant Skill read contract",
            [model.id],
        )
        session.add(
            SpacesUsers(
                space_id=space.id,
                user_id=user.id,
                role="viewer",
            )
        )
        assistant = await assistant_factory(
            session,
            "Readable Assistant",
            model.id,
            space_id=space.id,
        )
        token = container.auth_service().create_access_token_for_user(user)
        space_id = space.id
        assistant_id = assistant.id

    headers = {"Authorization": f"Bearer {token}"}
    assistant_response = await client.get(
        f"/api/v1/assistants/{assistant_id}/",
        headers=headers,
    )
    assert assistant_response.status_code == 200, assistant_response.text

    configuration_response = await client.get(
        f"/api/v1/spaces/{space_id}/assistants/{assistant_id}/skills/configuration/",
        headers=headers,
    )

    assert configuration_response.status_code == 403, configuration_response.text
