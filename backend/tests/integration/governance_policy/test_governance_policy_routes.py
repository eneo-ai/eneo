"""Integration tests for the personal-assistant governance admin endpoints."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import (
    AssistantMCPServers,
    AssistantMCPServerTools,
)
from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    SpacesMCPServers,
)
from eneo.skills.domain.skill import SkillRuntimePolicy
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_skill_policy_counts_personal_assistant_mcp_schema_and_rolls_back(
    client, admin_token, db_container, admin_user
):
    async with db_container() as container:
        space = await container.space_init_service().get_personal_space()
        assistant = space.default_assistant
        assert assistant is not None
        assert assistant.id is not None
        assert assistant.completion_model is not None
        skill = await container.organization_skill_service().create_organization_skill(
            slug=f"mcp-schema-{uuid4().hex[:8]}",
            display_name="Warehouse guidance",
            description="Use for warehouse questions",
            instructions="Use the approved warehouse tool.",
        )
        skill = (
            await container.organization_skill_service().publish(
                skill_id=skill.id,
                expected_revision_id=skill.current_revision.id,
            )
        ).skill
        await container.skill_repo().update_runtime_policy(
            tenant_id=admin_user.tenant_id,
            policy=SkillRuntimePolicy(
                selective_activation_enabled=True,
                max_attached_skills=100,
                context_share_percent=100,
                max_activations_per_turn=10,
            ),
        )
        assistant_id = assistant.id
        space_id = space.id
        model_id = assistant.completion_model.id
        assert model_id is not None
        completion_model = await container.session().get(CompletionModels, model_id)
        assert completion_model is not None
        completion_model.supports_tool_calling = True

    binding = {
        "skill_id": str(skill.id),
        "skill_revision_id": str(skill.current_revision.id),
        "activation_mode": "on_demand",
    }
    fitting = await client.put(
        "/api/v1/admin/governance-policy/",
        json={
            "models_restriction": {
                "enabled": True,
                "models": [{"completion_model_id": str(model_id), "is_default": True}],
            },
            "skills": {"bindings": [binding]},
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert fitting.status_code == 200, fitting.text

    cleared = await client.put(
        "/api/v1/admin/governance-policy/",
        json={"skills": {"bindings": []}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert cleared.status_code == 200, cleared.text

    async with db_container() as container:
        session = container.session()
        mcp_server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"Large schema {uuid4().hex[:8]}",
            description="Warehouse contract",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=False,
            tool_definition_max_bytes=4 * 1024 * 1024,
        )
        session.add(mcp_server)
        await session.flush()
        mcp_tool = MCPServerTools(
            mcp_server_id=mcp_server.id,
            name="warehouse_query",
            title="Warehouse query",
            description="Query the approved warehouse",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "warehouse field " * 100_000,
                    }
                },
                "required": ["query"],
            },
            is_enabled_by_default=True,
            requires_approval=False,
            removed_from_remote=False,
        )
        session.add(mcp_tool)
        await session.flush()
        session.add_all(
            [
                SpacesMCPServers(
                    space_id=space_id,
                    mcp_server_id=mcp_server.id,
                ),
                AssistantMCPServers(
                    assistant_id=assistant_id,
                    mcp_server_id=mcp_server.id,
                ),
                AssistantMCPServerTools(
                    assistant_id=assistant_id,
                    mcp_server_tool_id=mcp_tool.id,
                    is_enabled=True,
                ),
            ]
        )

    rejected = await client.put(
        "/api/v1/admin/governance-policy/",
        json={"skills": {"bindings": [binding]}},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert rejected.status_code == 400, rejected.text
    assert "selected completion model context" in rejected.json()["message"]

    persisted = await client.get(
        "/api/v1/admin/governance-policy/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert persisted.status_code == 200, persisted.text
    assert persisted.json()["skills"]["bindings"] == []
