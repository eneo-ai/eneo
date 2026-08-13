import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.app_table import AppRuns
from eneo.database.tables.roles_table import Roles
from eneo.database.tables.skill_table import SkillExecutionBlocks
from eneo.database.tables.spaces_table import (
    Spaces,
    SpacesTranscriptionModels,
    SpacesUsers,
)
from eneo.database.tables.users_table import users_roles_table
from eneo.main.exceptions import BadRequestException
from eneo.roles.permissions import Permission
from eneo.skills.domain.skill import (
    SkillActivationMode,
    SkillBindingIntent,
    SkillBindingReference,
    SkillExecutionBlockConflictError,
    SkillExecutionBlockedException,
)


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def regular_token(
    db_container,
    patch_auth_service_jwt,
    user_factory,
    admin_user,
):
    async with db_container() as container:
        regular_user = await user_factory(
            container.session(),
            tenant_id=admin_user.tenant_id,
        )
        return container.auth_service().create_access_token_for_user(regular_user)


async def _organization_space(session, *, tenant_id):
    return await session.scalar(
        sa.select(Spaces).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )


async def _create_published_organization_skill(client, *, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    create_response = await client.post(
        "/api/v1/skills/organization/",
        json={
            "slug": f"emergency-{uuid4().hex[:8]}",
            "display_name": "Emergency guidance",
            "description": "Approved organisation guidance",
            "instructions": "Use the approved organisation guidance.",
        },
        headers=headers,
    )
    assert create_response.status_code == 201, create_response.text
    skill = create_response.json()
    publish_response = await client.post(
        f"/api/v1/skills/organization/{skill['id']}/publish/",
        json={"expected_revision_id": skill["current_revision"]["id"]},
        headers=headers,
    )
    assert publish_response.status_code == 200, publish_response.text
    return skill


async def test_execution_block_lifecycle_retains_history_and_rejects_stale_unblock(
    db_container,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        assert organization is not None
        repo = container.skill_repo()
        skill = await repo.create(
            space_id=organization.id,
            slug=f"incident-{uuid4().hex[:8]}",
            display_name="Incident response",
            description="Approved incident guidance",
            instructions="Use the approved incident guidance.",
            content_digest="1" * 64,
            created_by_user_id=admin_user.id,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=skill.current_revision.id,
        )

        first = await repo.block_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            blocked_by_user_id=admin_user.id,
            reason="Confirmed unsafe instructions",
        )

        assert first is not None
        assert first.changed is True
        assert first.block.skill_id == skill.id
        assert first.block.reason == "Confirmed unsafe instructions"
        assert first.block.unblocked_at is None
        assert (
            await repo.get_active_execution_block(
                tenant_id=admin_user.tenant_id,
                skill_id=skill.id,
            )
            == first.block
        )

        released = await repo.unblock_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_block_id=first.block.id,
            unblocked_by_user_id=admin_user.id,
            reason="Revision removed from affected resources",
        )

        assert released is not None
        assert released.changed is True
        assert released.block.unblocked_by_user_id == admin_user.id
        assert released.block.unblock_reason == (
            "Revision removed from affected resources"
        )
        assert released.block.unblocked_at is not None
        assert (
            await repo.get_active_execution_block(
                tenant_id=admin_user.tenant_id,
                skill_id=skill.id,
            )
            is None
        )

        second = await repo.block_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            blocked_by_user_id=admin_user.id,
            reason="A second incident",
        )
        assert second is not None
        assert second.block.id != first.block.id

        with pytest.raises(SkillExecutionBlockConflictError):
            await repo.unblock_organization_skill(
                tenant_id=admin_user.tenant_id,
                skill_id=skill.id,
                expected_block_id=first.block.id,
                unblocked_by_user_id=admin_user.id,
                reason="Stale browser request",
            )

        history = (
            await session.scalars(
                sa.select(SkillExecutionBlocks)
                .where(SkillExecutionBlocks.skill_id == skill.id)
                .order_by(SkillExecutionBlocks.created_at)
            )
        ).all()
        assert [row.id for row in history] == [first.block.id, second.block.id]
        assert history[0].unblocked_at is not None
        assert history[1].unblocked_at is None


async def test_execution_blocks_are_tenant_scoped_and_require_prior_publication(
    db_container,
    admin_user,
    tenant_factory,
    user_factory,
):
    async with db_container() as container:
        session = container.session()
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        assert organization is not None
        repo = container.skill_repo()
        draft = await repo.create(
            space_id=organization.id,
            slug=f"draft-{uuid4().hex[:8]}",
            display_name="Draft guidance",
            description="Not published yet",
            instructions="Draft instructions.",
            content_digest="2" * 64,
            created_by_user_id=admin_user.id,
        )
        other_tenant = await tenant_factory(
            session,
            name=f"Execution block tenant {uuid4()}",
        )
        other_user = await user_factory(session, tenant_id=other_tenant.id)

        assert (
            await repo.block_organization_skill(
                tenant_id=admin_user.tenant_id,
                skill_id=draft.id,
                blocked_by_user_id=admin_user.id,
                reason="Drafts do not need emergency revocation",
            )
            is None
        )

        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=draft.id,
            expected_revision_id=draft.current_revision.id,
        )
        assert (
            await repo.block_organization_skill(
                tenant_id=other_tenant.id,
                skill_id=draft.id,
                blocked_by_user_id=other_user.id,
                reason="Foreign tenant attempt",
            )
            is None
        )
        assert (
            await repo.get_active_execution_block(
                tenant_id=other_tenant.id,
                skill_id=draft.id,
            )
            is None
        )


async def test_concurrent_block_requests_create_one_active_incident(
    db_container,
    admin_user,
):
    async with db_container() as container:
        organization = await _organization_space(
            container.session(),
            tenant_id=admin_user.tenant_id,
        )
        assert organization is not None
        repo = container.skill_repo()
        skill = await repo.create(
            space_id=organization.id,
            slug=f"concurrent-block-{uuid4().hex[:8]}",
            display_name="Concurrent incident",
            description="Approved incident guidance",
            instructions="Use the approved incident guidance.",
            content_digest="3" * 64,
            created_by_user_id=admin_user.id,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=skill.current_revision.id,
        )

    async def block(reason: str):
        async with db_container() as container:
            result = await container.skill_repo().block_organization_skill(
                tenant_id=admin_user.tenant_id,
                skill_id=skill.id,
                blocked_by_user_id=admin_user.id,
                reason=reason,
            )
            assert result is not None
            return result

    first, second = await asyncio.gather(
        block("First concurrent incident"),
        block("Second concurrent incident"),
    )

    assert sorted([first.changed, second.changed]) == [False, True]
    assert first.block.id == second.block.id
    async with db_container() as container:
        active_count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(SkillExecutionBlocks)
            .where(
                SkillExecutionBlocks.skill_id == skill.id,
                SkillExecutionBlocks.unblocked_at.is_(None),
            )
        )
        assert active_count == 1


async def test_queued_snapshot_predating_block_fails_at_live_runtime_resolution(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    app_factory,
):
    async with db_container() as container:
        session = container.session()
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        assert organization is not None
        model = await completion_model_factory(session, "blocked-app-model")
        target_space = await space_factory(
            session,
            "Blocked App target",
            [model.id],
        )
        target_space_id = target_space.id
        session.add(
            SpacesUsers(
                space_id=target_space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        app = await app_factory(
            session,
            "Blocked App",
            model.id,
            space_id=target_space.id,
        )
        repo = container.skill_repo()
        skill = await repo.create(
            space_id=organization.id,
            slug=f"queued-block-{uuid4().hex[:8]}",
            display_name="Queued incident",
            description="Approved App guidance",
            instructions="Use the approved App guidance.",
            content_digest="4" * 64,
            created_by_user_id=admin_user.id,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=skill.current_revision.id,
        )
        await container.skill_service().replace_app_bindings(
            space_id=target_space.id,
            app_id=app.id,
            references=[
                SkillBindingReference(
                    skill_id=skill.id,
                    skill_revision_id=skill.current_revision.id,
                )
            ],
        )
        queued = await container.skill_service().compose_for_app(
            app_id=app.id,
            base_instructions="Base",
        )

    async with db_container() as container:
        blocked = await container.skill_repo().block_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            blocked_by_user_id=admin_user.id,
            reason="Confirmed unsafe instructions",
        )
        assert blocked is not None

    async with db_container() as container:
        with pytest.raises(SkillExecutionBlockedException) as exc_info:
            await container.skill_service().compose_for_execution_snapshot(
                tenant_id=admin_user.tenant_id,
                space_id=target_space_id,
                provenance=queued.provenance,
                base_instructions="Base",
            )

    assert blocked.block.reason not in str(exc_info.value)
    assert exc_info.value.reason == blocked.block.reason


async def test_blocked_skill_rejects_new_and_changed_bindings_but_retains_exact_pins(
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    incident_reason = "Confirmed unsafe instructions"
    async with db_container() as container:
        session = container.session()
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        assert organization is not None
        model = await completion_model_factory(
            session,
            "blocked-binding-integrity-model",
        )
        target_space = await space_factory(
            session,
            "Blocked binding integrity target",
            [model.id],
        )
        session.add(
            SpacesUsers(
                space_id=target_space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        existing_assistant = await assistant_factory(
            session,
            "Existing blocked binding",
            model.id,
            space_id=target_space.id,
        )
        new_assistant = await assistant_factory(
            session,
            "New blocked binding",
            model.id,
            space_id=target_space.id,
        )
        repo = container.skill_repo()
        blocked_skill = await repo.create(
            space_id=organization.id,
            slug=f"blocked-binding-{uuid4().hex[:8]}",
            display_name="Blocked binding guidance",
            description="Approved guidance with multiple revisions",
            instructions="Use revision one.",
            content_digest="6" * 64,
            created_by_user_id=admin_user.id,
        )
        revision_one = blocked_skill.current_revision
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=blocked_skill.id,
            expected_revision_id=revision_one.id,
        )
        companion_skill = await repo.create(
            space_id=organization.id,
            slug=f"companion-binding-{uuid4().hex[:8]}",
            display_name="Companion guidance",
            description="A second approved Skill for ordering",
            instructions="Use the companion guidance.",
            content_digest="8" * 64,
            created_by_user_id=admin_user.id,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=companion_skill.id,
            expected_revision_id=companion_skill.current_revision.id,
        )
        blocked_reference = SkillBindingReference(
            skill_id=blocked_skill.id,
            skill_revision_id=revision_one.id,
        )
        companion_reference = SkillBindingReference(
            skill_id=companion_skill.id,
            skill_revision_id=companion_skill.current_revision.id,
        )
        service = container.skill_service()
        await service.replace_assistant_bindings(
            space_id=target_space.id,
            assistant_id=existing_assistant.id,
            intents=[
                SkillBindingIntent(reference=blocked_reference),
                SkillBindingIntent(reference=companion_reference),
            ],
        )
        revision_two_change = await repo.create_revision(
            skill_id=blocked_skill.id,
            display_name="Blocked binding guidance",
            description="Approved guidance with multiple revisions",
            instructions="Use revision two.",
            content_digest="7" * 64,
            created_by_user_id=admin_user.id,
        )
        assert revision_two_change is not None
        revision_two = revision_two_change.revision
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=blocked_skill.id,
            expected_revision_id=revision_two.id,
        )
        blocked = await repo.block_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=blocked_skill.id,
            blocked_by_user_id=admin_user.id,
            reason=incident_reason,
        )
        assert blocked is not None

        retained = await service.replace_assistant_bindings(
            space_id=target_space.id,
            assistant_id=existing_assistant.id,
            intents=[
                SkillBindingIntent(reference=companion_reference),
                SkillBindingIntent(reference=blocked_reference),
            ],
        )
        assert [binding.skill_id for binding in retained.bindings] == [
            companion_skill.id,
            blocked_skill.id,
        ]

        with pytest.raises(BadRequestException) as new_binding:
            await service.replace_assistant_bindings(
                space_id=target_space.id,
                assistant_id=new_assistant.id,
                intents=[
                    SkillBindingIntent(
                        reference=SkillBindingReference(
                            skill_id=blocked_skill.id,
                            skill_revision_id=revision_two.id,
                        )
                    )
                ],
            )
        with pytest.raises(BadRequestException) as revision_change:
            await service.replace_assistant_bindings(
                space_id=target_space.id,
                assistant_id=existing_assistant.id,
                intents=[
                    SkillBindingIntent(reference=companion_reference),
                    SkillBindingIntent(
                        reference=SkillBindingReference(
                            skill_id=blocked_skill.id,
                            skill_revision_id=revision_two.id,
                        )
                    ),
                ],
            )

        assert incident_reason not in str(new_binding.value)
        assert incident_reason not in str(revision_change.value)

        released = await repo.unblock_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=blocked_skill.id,
            expected_block_id=blocked.block.id,
            unblocked_by_user_id=admin_user.id,
            reason="The approved revision is safe again",
        )
        assert released is not None
        updated = await service.replace_assistant_bindings(
            space_id=target_space.id,
            assistant_id=existing_assistant.id,
            intents=[
                SkillBindingIntent(reference=companion_reference),
                SkillBindingIntent(
                    reference=SkillBindingReference(
                        skill_id=blocked_skill.id,
                        skill_revision_id=revision_two.id,
                    )
                ),
            ],
        )
        assert updated.bindings[1].skill_revision_id == revision_two.id


@pytest.mark.parametrize(
    ("initial_mode", "requested_mode"),
    [
        (SkillActivationMode.ALWAYS, SkillActivationMode.ON_DEMAND),
        (SkillActivationMode.ON_DEMAND, SkillActivationMode.ALWAYS),
    ],
)
async def test_blocked_skill_rejects_retained_assistant_mode_change_until_unblocked(
    initial_mode: SkillActivationMode,
    requested_mode: SkillActivationMode,
    db_container,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container() as container:
        session = container.session()
        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        assert organization is not None
        model = await completion_model_factory(
            session,
            f"blocked-mode-change-{initial_mode.value}",
        )
        target_space = await space_factory(
            session,
            f"Blocked {initial_mode.value} mode target",
            [model.id],
        )
        session.add(
            SpacesUsers(
                space_id=target_space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        assistant = await assistant_factory(
            session,
            f"Blocked {initial_mode.value} mode Assistant",
            model.id,
            space_id=target_space.id,
        )
        repo = container.skill_repo()
        skill = await repo.create(
            space_id=organization.id,
            slug=f"blocked-mode-{initial_mode.value}-{uuid4().hex[:8]}",
            display_name="Blocked mode guidance",
            description="Approved guidance with a retained binding",
            instructions="Use the approved guidance.",
            content_digest="9" * 64,
            created_by_user_id=admin_user.id,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=skill.current_revision.id,
        )
        reference = SkillBindingReference(
            skill_id=skill.id,
            skill_revision_id=skill.current_revision.id,
        )
        service = container.skill_service()
        await service.replace_assistant_bindings(
            space_id=target_space.id,
            assistant_id=assistant.id,
            intents=[
                SkillBindingIntent(
                    reference=reference,
                    activation_mode=initial_mode,
                )
            ],
        )
        blocked = await repo.block_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            blocked_by_user_id=admin_user.id,
            reason="Confirmed mode-change incident",
        )
        assert blocked is not None

        unchanged = await service.replace_assistant_bindings(
            space_id=target_space.id,
            assistant_id=assistant.id,
            intents=[
                SkillBindingIntent(
                    reference=reference,
                    activation_mode=initial_mode,
                )
            ],
        )
        assert unchanged.bindings[0].activation_mode is initial_mode

        with pytest.raises(BadRequestException, match="Blocked organisation Skills"):
            await service.replace_assistant_bindings(
                space_id=target_space.id,
                assistant_id=assistant.id,
                intents=[
                    SkillBindingIntent(
                        reference=reference,
                        activation_mode=requested_mode,
                    )
                ],
            )
        persisted = await repo.list_assistant_bindings(assistant_id=assistant.id)
        assert persisted[0].activation_mode is initial_mode

        released = await repo.unblock_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_block_id=blocked.block.id,
            unblocked_by_user_id=admin_user.id,
            reason="Mode change reviewed and approved",
        )
        assert released is not None
        changed = await service.replace_assistant_bindings(
            space_id=target_space.id,
            assistant_id=assistant.id,
            intents=[
                SkillBindingIntent(
                    reference=reference,
                    activation_mode=requested_mode,
                )
            ],
        )
        assert changed.bindings[0].activation_mode is requested_mode


async def test_blocked_app_run_hides_incident_reason_from_non_admin_runner(
    client,
    admin_token,
    db_container,
    admin_user,
    user_factory,
    completion_model_factory,
    transcription_model_factory,
    space_factory,
    app_factory,
):
    incident_reason = "Potential personal data exposure in payroll instructions"
    async with db_container() as container:
        session = container.session()
        runner = await user_factory(
            session,
            tenant_id=admin_user.tenant_id,
        )
        app_role = Roles(
            name=f"App runner {uuid4().hex[:8]}",
            permissions=[Permission.APPS.value, Permission.SKILLS.value],
            tenant_id=admin_user.tenant_id,
        )
        session.add(app_role)
        await session.flush()
        await session.execute(
            users_roles_table.insert().values(
                user_id=runner.id,
                role_id=app_role.id,
            )
        )
        runner_token = container.auth_service().create_access_token_for_user(runner)

        organization = await _organization_space(
            session,
            tenant_id=admin_user.tenant_id,
        )
        assert organization is not None
        completion_model = await completion_model_factory(
            session,
            "blocked-app-http-model",
        )
        transcription_model = await transcription_model_factory(
            session,
            "blocked-app-http-transcription-model",
        )
        target_space = await space_factory(
            session,
            "Blocked App HTTP target",
            [completion_model.id],
        )
        session.add_all(
            [
                SpacesTranscriptionModels(
                    space_id=target_space.id,
                    transcription_model_id=transcription_model.id,
                ),
                SpacesUsers(
                    space_id=target_space.id,
                    user_id=admin_user.id,
                    role="admin",
                ),
                SpacesUsers(
                    space_id=target_space.id,
                    user_id=runner.id,
                    role="viewer",
                ),
            ]
        )
        app = await app_factory(
            session,
            "Blocked App HTTP",
            completion_model.id,
            space_id=target_space.id,
            transcription_model_id=transcription_model.id,
            published=True,
        )
        repo = container.skill_repo()
        skill = await repo.create(
            space_id=organization.id,
            slug=f"blocked-app-http-{uuid4().hex[:8]}",
            display_name="Payroll incident guidance",
            description="Approved App guidance",
            instructions="Use the approved App guidance.",
            content_digest="5" * 64,
            created_by_user_id=admin_user.id,
        )
        await repo.publish_organization(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            expected_revision_id=skill.current_revision.id,
        )
        await container.skill_service().replace_app_bindings(
            space_id=target_space.id,
            app_id=app.id,
            references=[
                SkillBindingReference(
                    skill_id=skill.id,
                    skill_revision_id=skill.current_revision.id,
                )
            ],
        )
        blocked = await repo.block_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=skill.id,
            blocked_by_user_id=admin_user.id,
            reason=incident_reason,
        )
        assert blocked is not None
        app_id = app.id
        skill_id = skill.id
        target_space_id = target_space.id

    binding_response = await client.get(
        f"/api/v1/spaces/{target_space_id}/apps/{app_id}/skills/",
        headers={"Authorization": f"Bearer {runner_token}"},
    )
    assert binding_response.status_code == 200, binding_response.text
    assert binding_response.json()[0]["execution_blocked"] is True
    assert incident_reason not in binding_response.text

    detail_response = await client.get(
        f"/api/v1/skills/organization/{skill_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert detail_response.status_code == 200, detail_response.text
    assert detail_response.json()["execution_blocked"] is True
    assert incident_reason not in detail_response.text

    list_response = await client.get(
        "/api/v1/skills/organization/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert list_response.status_code == 200, list_response.text
    listed_skill = next(
        item for item in list_response.json()["items"] if item["id"] == str(skill_id)
    )
    assert listed_skill["execution_blocked"] is True
    assert incident_reason not in list_response.text

    catalogue_response = await client.get(
        "/api/v1/skills/catalogue/",
        headers={"Authorization": f"Bearer {runner_token}"},
    )
    assert catalogue_response.status_code == 200, catalogue_response.text
    catalogue_skill = next(
        item
        for item in catalogue_response.json()["items"]
        if item["id"] == str(skill_id)
    )
    assert catalogue_skill["execution_blocked"] is True
    assert incident_reason not in catalogue_response.text

    catalogue_detail_response = await client.get(
        f"/api/v1/skills/catalogue/{skill_id}/",
        headers={"Authorization": f"Bearer {runner_token}"},
    )
    assert catalogue_detail_response.status_code == 200, catalogue_detail_response.text
    assert catalogue_detail_response.json()["execution_blocked"] is True
    assert incident_reason not in catalogue_detail_response.text

    run_response = await client.post(
        f"/api/v1/apps/{app_id}/runs/",
        json={"files": [], "text": "Run the published App"},
        headers={"Authorization": f"Bearer {runner_token}"},
    )

    assert run_response.status_code == 400, run_response.text
    assert run_response.json()["message"] == (
        "An organisation Skill is blocked from execution. Contact an administrator."
    )
    assert incident_reason not in run_response.text

    admin_response = await client.get(
        f"/api/v1/settings/skills/{skill_id}/execution-block",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_response.status_code == 200, admin_response.text
    assert admin_response.json()["block"]["reason"] == incident_reason

    async with db_container() as container:
        run_count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(AppRuns)
            .where(AppRuns.app_id == app_id)
        )
        assert run_count == 0


async def test_execution_block_http_contract_preserves_state_on_stale_unblock(
    client,
    admin_token,
    regular_token,
    db_container,
):
    headers = {"Authorization": f"Bearer {admin_token}"}
    skill = await _create_published_organization_skill(client, token=admin_token)
    skill_id = skill["id"]

    forbidden_response = await client.get(
        f"/api/v1/settings/skills/{skill_id}/execution-block",
        headers={"Authorization": f"Bearer {regular_token}"},
    )
    assert forbidden_response.status_code == 403, forbidden_response.text

    empty_response = await client.get(
        f"/api/v1/settings/skills/{skill_id}/execution-block",
        headers=headers,
    )
    assert empty_response.status_code == 200, empty_response.text
    assert empty_response.json() == {"skill_id": skill_id, "block": None}

    block_response = await client.post(
        f"/api/v1/settings/skills/{skill_id}/execution-block",
        json={"reason": "Confirmed unsafe instructions"},
        headers=headers,
    )
    assert block_response.status_code == 200, block_response.text
    block = block_response.json()["block"]
    assert block["reason"] == "Confirmed unsafe instructions"

    stale_response = await client.post(
        f"/api/v1/settings/skills/{skill_id}/execution-block/unblock",
        json={
            "expected_block_id": str(uuid4()),
            "reason": "Stale browser request",
        },
        headers=headers,
    )
    assert stale_response.status_code == 409, stale_response.text

    still_blocked = await client.get(
        f"/api/v1/settings/skills/{skill_id}/execution-block",
        headers=headers,
    )
    assert still_blocked.status_code == 200, still_blocked.text
    assert still_blocked.json()["block"]["id"] == block["id"]

    unblock_response = await client.post(
        f"/api/v1/settings/skills/{skill_id}/execution-block/unblock",
        json={
            "expected_block_id": block["id"],
            "reason": "Removed the harmful revision",
        },
        headers=headers,
    )
    assert unblock_response.status_code == 200, unblock_response.text
    assert unblock_response.json() == {"skill_id": skill_id, "block": None}

    async with db_container() as container:
        history = (
            await container.session().scalars(
                sa.select(SkillExecutionBlocks).where(
                    SkillExecutionBlocks.skill_id == skill_id
                )
            )
        ).all()
        assert len(history) == 1
        assert history[0].reason == "Confirmed unsafe instructions"
        assert history[0].unblock_reason == "Removed the harmful revision"
        assert history[0].unblocked_at is not None


async def test_execution_block_controls_require_a_real_tenant_admin(
    client,
    admin_token,
    admin_user_api_key,
    db_container,
):
    skill = await _create_published_organization_skill(client, token=admin_token)
    skill_id = skill["id"]
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    service_key_response = await client.post(
        "/api/v1/api-keys",
        json={
            "name": f"skill-incident-{uuid4().hex[:8]}",
            "key_type": "sk_",
            "permission": "admin",
            "scope_type": "tenant",
            "ownership": "service",
            "expires_at": expires_at,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert service_key_response.status_code == 201, service_key_response.text
    service_headers = {"X-API-Key": service_key_response.json()["secret"]}
    block_path = f"/api/v1/settings/skills/{skill_id}/execution-block"

    rejected_requests = [
        await client.get(block_path, headers=service_headers),
        await client.post(
            block_path,
            json={"reason": "Service principal incident"},
            headers=service_headers,
        ),
        await client.post(
            f"{block_path}/unblock",
            json={
                "expected_block_id": str(uuid4()),
                "reason": "Service principal recovery",
            },
            headers=service_headers,
        ),
    ]
    for response in rejected_requests:
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "user_identity_required"

    async with db_container() as container:
        incident_count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(SkillExecutionBlocks)
            .where(SkillExecutionBlocks.skill_id == skill_id)
        )
        assert incident_count == 0

    user_key_headers = {"X-API-Key": admin_user_api_key.key}
    empty_response = await client.get(block_path, headers=user_key_headers)
    assert empty_response.status_code == 200, empty_response.text

    block_response = await client.post(
        block_path,
        json={"reason": "Human-reviewed incident"},
        headers=user_key_headers,
    )
    assert block_response.status_code == 200, block_response.text
    block_id = block_response.json()["block"]["id"]

    unblock_response = await client.post(
        f"{block_path}/unblock",
        json={
            "expected_block_id": block_id,
            "reason": "Human-reviewed recovery",
        },
        headers=user_key_headers,
    )
    assert unblock_response.status_code == 200, unblock_response.text


async def test_scoped_api_keys_cannot_manage_execution_blocks(
    client,
    admin_token,
    admin_user,
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    app_factory,
):
    skill = await _create_published_organization_skill(client, token=admin_token)
    skill_id = skill["id"]
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "skill-scope-model")
        space = await space_factory(session, "Skill scope", [model.id])
        session.add(
            SpacesUsers(
                space_id=space.id,
                user_id=admin_user.id,
                role="admin",
            )
        )
        assistant = await assistant_factory(
            session,
            "Skill scope Assistant",
            model.id,
            space_id=space.id,
        )
        app = await app_factory(
            session,
            "Skill scope App",
            model.id,
            space_id=space.id,
        )
        assert space.tenant_id == admin_user.tenant_id
        scope_targets = (
            ("space", space.id),
            ("assistant", assistant.id),
            ("app", app.id),
        )

    block_path = f"/api/v1/settings/skills/{skill_id}/execution-block"
    for scope_type, scope_id in scope_targets:
        key_response = await client.post(
            "/api/v1/api-keys",
            json={
                "name": f"skill-{scope_type}-{uuid4().hex[:8]}",
                "key_type": "sk_",
                "permission": "admin",
                "scope_type": scope_type,
                "scope_id": str(scope_id),
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert key_response.status_code == 201, key_response.text
        scoped_headers = {"X-API-Key": key_response.json()["secret"]}

        rejected_requests = [
            await client.get(block_path, headers=scoped_headers),
            await client.post(
                block_path,
                json={"reason": "Scoped key incident"},
                headers=scoped_headers,
            ),
            await client.post(
                f"{block_path}/unblock",
                json={
                    "expected_block_id": str(uuid4()),
                    "reason": "Scoped key recovery",
                },
                headers=scoped_headers,
            ),
        ]
        for response in rejected_requests:
            assert response.status_code == 403, response.text
            assert response.json()["code"] == "insufficient_scope"

    async with db_container() as container:
        incident_count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(SkillExecutionBlocks)
            .where(SkillExecutionBlocks.skill_id == skill_id)
        )
        assert incident_count == 0
