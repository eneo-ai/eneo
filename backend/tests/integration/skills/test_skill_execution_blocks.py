import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.skill_table import SkillExecutionBlocks
from eneo.database.tables.spaces_table import Spaces, SpacesUsers
from eneo.skills.domain.skill import (
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
        with pytest.raises(
            SkillExecutionBlockedException,
            match="Confirmed unsafe instructions",
        ):
            await container.skill_service().compose_for_execution_snapshot(
                tenant_id=admin_user.tenant_id,
                space_id=target_space_id,
                provenance=queued.provenance,
                base_instructions="Base",
            )


async def test_execution_block_http_contract_preserves_state_on_stale_unblock(
    client,
    admin_token,
    regular_token,
    db_container,
):
    headers = {"Authorization": f"Bearer {admin_token}"}
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
    skill_id = skill["id"]
    publish_response = await client.post(
        f"/api/v1/skills/organization/{skill_id}/publish/",
        json={"expected_revision_id": skill["current_revision"]["id"]},
        headers=headers,
    )
    assert publish_response.status_code == 200, publish_response.text

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
