"""Integration tests for the personal-assistant governance admin endpoints."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.users.user import UserAdd, UserState


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt):
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_email("test@example.com")
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(user)


@pytest.fixture
async def regular_user_token(db_container, patch_auth_service_jwt):
    async with db_container() as container:
        user_repo = container.user_repo()
        admin = await user_repo.get_user_by_email("test@example.com")
        user = await user_repo.add(
            UserAdd(
                email=f"regular-policy-{uuid4().hex[:8]}@example.com",
                username=f"reg_policy_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin.tenant_id,
            )
        )
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(user)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_admin_get_auto_creates_empty_policy(client, admin_token):
    resp = await client.get(
        "/api/v1/admin/governance-policy/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["models_restriction"] == {
        "enabled": False,
        "models": [],
        "provider_ids": [],
    }
    assert payload["mcp_restriction"] == {
        "enabled": False,
        "servers": [],
        "disabled_tool_ids": [],
    }
    assert payload["prompt_enforcement"] == {
        "enabled": False,
        "prompt_library_id": None,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_non_admin_gets_403(client, regular_user_token):
    resp = await client.get(
        "/api/v1/admin/governance-policy/",
        headers={"Authorization": f"Bearer {regular_user_token}"},
    )

    assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_model_restriction_requires_at_least_one_model(client, admin_token):
    resp = await client.put(
        "/api/v1/admin/governance-policy/",
        json={"models_restriction": {"enabled": True, "models": []}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_restriction_rejects_empty_enabled_grant(client, admin_token):
    resp = await client.put(
        "/api/v1/admin/governance-policy/",
        json={
            "mcp_restriction": {
                "enabled": True,
                "servers": [],
                "disabled_tool_ids": [],
            }
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert resp.status_code == 400, resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_skill_policy_rejects_unusable_personal_assistant_baseline(
    client, admin_token, db_container
):
    async with db_container() as container:
        await container.space_init_service().get_personal_space()
        skill = await container.organization_skill_service().create_organization_skill(
            slug=f"oversized-{uuid4().hex[:8]}",
            display_name="Oversized instructions",
            description="Regression fixture for governance context fit",
            instructions="overflow " * 10_000,
        )
        skill = (
            await container.organization_skill_service().publish(
                skill_id=skill.id,
                expected_revision_id=skill.current_revision.id,
            )
        ).skill

    response = await client.put(
        "/api/v1/admin/governance-policy/",
        json={
            "skills": {
                "bindings": [
                    {
                        "skill_id": str(skill.id),
                        "skill_revision_id": str(skill.current_revision.id),
                    }
                ]
            }
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 400, response.text
    assert "context window" in response.json()["message"]

    persisted = await client.get(
        "/api/v1/admin/governance-policy/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert persisted.status_code == 200, persisted.text
    assert persisted.json()["skills"]["bindings"] == []
