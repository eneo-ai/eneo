from uuid import UUID, uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.skills.domain.skill import SkillBindingReference, compose_skill_instructions


@pytest.fixture
async def reference_headers(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
    return {"Authorization": f"Bearer {token}"}


async def create_space(client, headers):
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"references-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def content(instructions="Write clear text."):
    return {
        "slug": f"reference-{uuid4().hex[:8]}",
        "display_name": "Communication guidance",
        "description": "Helps write understandable communication.",
        "instructions": instructions,
    }


async def create_skill(client, headers, space_id, instructions="Write clear text."):
    response = await client.post(
        f"/api/v1/spaces/{space_id}/skills/",
        json=content(instructions),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def link(skill):
    return f"[Klartext](eneo-skill:{skill['id']}@{skill['current_revision_id']})"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reference_cannot_cross_spaces_or_leave_a_partial_skill(
    client, reference_headers
):
    source_space = await create_space(client, reference_headers)
    other_space = await create_space(client, reference_headers)
    private_helper = await create_skill(client, reference_headers, other_space)
    response = await client.post(
        f"/api/v1/spaces/{source_space}/skills/",
        json=content(f"Use {link(private_helper)}."),
        headers=reference_headers,
    )
    assert response.status_code == 400, response.text
    listed = await client.get(
        f"/api/v1/spaces/{source_space}/skills/", headers=reference_headers
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retained_revisions_protect_helpers_after_parent_is_revised(
    client, reference_headers
):
    space = await create_space(client, reference_headers)
    helper = await create_skill(client, reference_headers, space)
    parent = await create_skill(
        client, reference_headers, space, f"Use {link(helper)}."
    )
    revised = await client.post(
        f"/api/v1/spaces/{space}/skills/{parent['id']}/revisions/",
        json={key: value for key, value in content().items() if key != "slug"},
        headers=reference_headers,
    )
    assert revised.status_code == 201, revised.text
    removed_helper = await client.delete(
        f"/api/v1/spaces/{space}/skills/{helper['id']}/", headers=reference_headers
    )
    assert removed_helper.status_code == 409, removed_helper.text
    removed_parent = await client.delete(
        f"/api/v1/spaces/{space}/skills/{parent['id']}/", headers=reference_headers
    )
    assert removed_parent.status_code == 204, removed_parent.text
    removed_helper = await client.delete(
        f"/api/v1/spaces/{space}/skills/{helper['id']}/", headers=reference_headers
    )
    assert removed_helper.status_code == 204, removed_helper.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_new_revision_cannot_introduce_a_cycle_through_an_older_revision(
    client, reference_headers
):
    space = await create_space(client, reference_headers)
    first = await create_skill(client, reference_headers, space)
    second = await create_skill(client, reference_headers, space, f"Use {link(first)}.")
    response = await client.post(
        f"/api/v1/spaces/{space}/skills/{first['id']}/revisions/",
        json={
            "display_name": first["display_name"],
            "description": first["description"],
            "instructions": f"Use {link(second)}.",
        },
        headers=reference_headers,
    )
    assert response.status_code == 400, response.text
    history = await client.get(
        f"/api/v1/spaces/{space}/skills/{first['id']}/revisions/",
        headers=reference_headers,
    )
    assert history.status_code == 200, history.text
    assert history.json()["total_count"] == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approved_transitive_closure_is_frozen_and_resolves_in_one_batch(
    client, reference_headers, db_container, admin_user
):
    space = await create_space(client, reference_headers)
    leaf = await create_skill(client, reference_headers, space, "Use plain language.")
    helper = await create_skill(client, reference_headers, space, f"Use {link(leaf)}.")
    root = await create_skill(client, reference_headers, space, f"Use {link(helper)}.")
    revised = await client.post(
        f"/api/v1/spaces/{space}/skills/{leaf['id']}/revisions/",
        json={
            key: value
            for key, value in content("New leaf instructions.").items()
            if key != "slug"
        },
        headers=reference_headers,
    )
    assert revised.status_code == 201, revised.text

    async with db_container() as container:
        bindings = (
            await container.skill_repo().resolve_references_for_execution_snapshot(
                tenant_id=admin_user.tenant_id,
                parent_space_id=UUID(space),
                references=[
                    SkillBindingReference(
                        UUID(root["id"]), UUID(root["current_revision_id"])
                    )
                ],
            )
        )
        composition = compose_skill_instructions(
            base_instructions="Base", bindings=bindings
        )

    assert len(bindings) == 1
    assert len(bindings[0].dependencies) == 2
    assert "Use plain language." in composition.prompt
    assert "New leaf instructions." not in composition.prompt
    assert {str(item.skill_revision_id) for item in composition.provenance} == {
        item["current_revision_id"] for item in (root, helper, leaf)
    }


async def test_unpublishing_a_helper_preserves_approved_roots_and_restoration(
    db_container, admin_user
):
    async with db_container() as container:
        container.user.override(admin_user)
        service = container.organization_skill_service()
        helper = await service.create_organization_skill(**content())
        await service.publish(
            skill_id=helper.id, expected_revision_id=helper.current_revision.id
        )
        instructions = (
            f"Use [Klartext](eneo-skill:{helper.id}@{helper.current_revision.id})."
        )
        root = await service.create_organization_skill(**content(instructions))
        await service.publish(
            skill_id=root.id, expected_revision_id=root.current_revision.id
        )
        await service.unpublish(skill_id=helper.id)

        resolved = await container.skill_repo().resolve_published_references_for_binding_update(
            tenant_id=admin_user.tenant_id,
            references=[SkillBindingReference(root.id, root.current_revision.id)],
        )
        assert len(resolved) == 1
        assert (
            resolved[0].dependencies[0].skill_revision_id == helper.current_revision.id
        )
        with pytest.raises(BadRequestException, match="published revision"):
            await service.create_organization_skill(**content(instructions))

        changed = await service.create_revision(
            skill_id=root.id,
            **{
                key: value
                for key, value in content("No helpers.").items()
                if key != "slug"
            },
        )
        restored = await service.restore_revision(
            skill_id=root.id,
            source_revision_id=root.current_revision.id,
            reviewed_current_revision_id=changed.revision.id,
        )
        assert restored.change.revision.instructions == instructions
        assert restored.change.revision.id != root.current_revision.id


@pytest.mark.parametrize("scheme", ["eneo-mcp", "eneo-tool"])
async def test_new_mcp_references_require_a_known_local_target(
    client, reference_headers, scheme
):
    space = await create_space(client, reference_headers)
    target = str(uuid4()) + ("/today" if scheme == "eneo-tool" else "")
    response = await client.post(
        f"/api/v1/spaces/{space}/skills/",
        json=content(f"Use [Time]({scheme}:{target})."),
        headers=reference_headers,
    )
    assert response.status_code == 400, response.text


async def test_reference_group_counts_unique_helpers_and_its_root(
    client, reference_headers, monkeypatch
):
    from eneo.skills.infrastructure import skill_revision_references

    monkeypatch.setattr(skill_revision_references, "MAX_SKILL_ATTACHMENT_LIMIT", 3)
    space = await create_space(client, reference_headers)
    leaf = await create_skill(client, reference_headers, space)
    helper = await create_skill(client, reference_headers, space, link(leaf))
    # The direct leaf and the helper's leaf are the same Skill. Repeating a
    # mention in the prose must not spend another attachment slot.
    root = await create_skill(
        client,
        reference_headers,
        space,
        f"Use {link(helper)} and {link(leaf)}. Then check {link(leaf)} again.",
    )
    response = await client.post(
        f"/api/v1/spaces/{space}/skills/",
        json=content(link(root)),
        headers=reference_headers,
    )
    assert response.status_code == 400, response.text
    assert "3 unique Skills" in response.text


@pytest.fixture
async def published_reference_update(db_container, admin_user):
    async with db_container() as container:
        container.user.override(admin_user)
        service = container.organization_skill_service()
        helper = await service.create_organization_skill(**content())
        root = await service.create_organization_skill(**content())
        for skill in (helper, root):
            await service.publish(
                skill_id=skill.id, expected_revision_id=skill.current_revision.id
            )
        revision = await service.create_revision(
            skill_id=root.id,
            **{
                key: value
                for key, value in content(
                    f"Use [Helper](eneo-skill:{helper.id}@{helper.current_revision.id})."
                ).items()
                if key != "slug"
            },
        )
        await service.publish(
            skill_id=root.id, expected_revision_id=revision.revision.id
        )
        await container.skill_repo().get_or_seed_runtime_policy(
            tenant_id=admin_user.tenant_id
        )
    return root, helper, revision.revision


@pytest.mark.parametrize("surface", ["assistant", "app", "personal_chat"])
async def test_pin_confirmation_refuses_a_blocked_helper(
    db_container, admin_user, published_reference_update, surface
):
    from eneo.database.tables.governance_policy_table import GovernancePolicies
    from eneo.governance_policy.domain.governance_policy import PolicyScope
    from eneo.skills.domain.skill import (
        PersonalChatPinConfirmOutcome,
        SkillBlockedForBindingError,
    )

    root, helper, revision = published_reference_update
    async with db_container() as container:
        repo = container.skill_repo()
        policy = GovernancePolicies(
            tenant_id=admin_user.tenant_id,
            scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT.value,
        )
        if surface == "personal_chat":
            container.session().add(policy)
            await container.session().flush()
            bindings = await repo.resolve_references_for_execution_snapshot(
                tenant_id=admin_user.tenant_id,
                parent_space_id=root.space_id,
                references=[SkillBindingReference(root.id, root.current_revision.id)],
            )
            await repo.replace_policy_bindings(
                policy_id=policy.id,
                tenant_id=admin_user.tenant_id,
                skill_space_id=root.space_id,
                bindings=bindings,
            )
            stage = await repo.stage_personal_chat_skill_pin_advance(
                tenant_id=admin_user.tenant_id,
                skill_id=root.id,
                expected_pinned_revision_id=root.current_revision.id,
                expected_published_revision_id=revision.id,
            )
            assert stage is not None
        await repo.block_organization_skill(
            tenant_id=admin_user.tenant_id,
            skill_id=helper.id,
            blocked_by_user_id=admin_user.id,
            reason="Helper revoked after review",
        )
        if surface == "personal_chat":
            outcome = await repo.confirm_personal_chat_skill_pin_advance(
                tenant_id=admin_user.tenant_id,
                skill_id=root.id,
                policy_id=stage.policy_id,
                policy_version=stage.policy_version,
                personal_defaults_snapshot=stage.personal_defaults_snapshot,
                expected_pinned_revision_id=root.current_revision.id,
                expected_published_revision_id=revision.id,
            )
            assert outcome is PersonalChatPinConfirmOutcome.BLOCKED
        else:
            snapshot = await repo.get_runtime_policy_snapshot(
                tenant_id=admin_user.tenant_id
            )
            apply = (
                repo.advance_assistant_skill_pins
                if surface == "assistant"
                else repo.advance_app_skill_pins
            )
            with pytest.raises(SkillBlockedForBindingError):
                await apply(
                    tenant_id=admin_user.tenant_id,
                    skill_id=root.id,
                    expected_published_revision_id=revision.id,
                    expected_runtime_policy_version=snapshot.row_version,
                    targets=[],
                )


async def test_app_pin_confirmation_holds_helper_lock_and_checks_policy_version(
    db_container, admin_user, published_reference_update
):
    import sqlalchemy as sa
    from sqlalchemy.exc import DBAPIError

    from eneo.database.tables.skill_table import Skills
    from eneo.skills.domain.skill import SkillRuntimePolicyChangedError
    from eneo.skills.infrastructure.skill_db_errors import is_lock_not_available

    root, helper, revision = published_reference_update
    async with db_container() as writer:
        repo = writer.skill_repo()
        snapshot = await repo.get_runtime_policy_snapshot(
            tenant_id=admin_user.tenant_id
        )
        with pytest.raises(SkillRuntimePolicyChangedError):
            await repo.advance_app_skill_pins(
                tenant_id=admin_user.tenant_id,
                skill_id=root.id,
                expected_published_revision_id=revision.id,
                expected_runtime_policy_version="outdated",
                targets=[],
            )
        assert (
            await repo.advance_app_skill_pins(
                tenant_id=admin_user.tenant_id,
                skill_id=root.id,
                expected_published_revision_id=revision.id,
                expected_runtime_policy_version=snapshot.row_version,
                targets=[],
            )
            == []
        )
        async with db_container() as blocker:
            with pytest.raises(DBAPIError) as caught:
                async with blocker.session().begin_nested():
                    await blocker.session().execute(
                        sa.select(Skills.id)
                        .where(Skills.id == helper.id)
                        .with_for_update(nowait=True)
                    )
            assert is_lock_not_available(caught.value)
