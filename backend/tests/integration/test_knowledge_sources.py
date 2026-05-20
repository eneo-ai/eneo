"""Phase 2 tests for the proxied knowledge-source flow.

What this file owns:
- The happy-path proxy-create wires together: eneo-knowledge admin call,
  Phase 1 space-scoped MCP registration (with connection-probe shortcircuited),
  and the `knowledge_sources` ownership row insert.
- Deleting through the existing space-MCP DELETE endpoint must also call
  eneo-knowledge to drop the upstream collection.

Cross-tenant and cross-space MCP visibility is already covered by
``test_space_scoped_mcp_servers.py`` — the proxy flow reuses that surface,
so we don't re-test the same invariant here.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.mcp_server_table import MCPServers
from intric.eneo_knowledge.client import (
    CreatedCollection,
    EneoKnowledgeClient,
    KnowledgeCollection,
    PairedMcpServer,
)
from intric.eneo_knowledge.table import KnowledgeSources
from intric.main.config import get_settings, set_settings
from intric.mcp_servers.application.mcp_server_service import (
    ConnectionResult,
    MCPServerService,
)


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        user_repo = container.user_repo()
        return await user_repo.get_user_by_email("test@example.com")


@pytest.fixture
async def default_user_token(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        return auth_service.create_access_token_for_user(default_user)


@pytest.fixture
def configure_knowledge_proxy(monkeypatch):
    """Set the knowledge-* settings so the proxy flow is enabled in tests."""

    original = get_settings()
    overrides = original.model_copy(
        update={
            "knowledge_url": "http://eneo-knowledge.test",
            "knowledge_api_key": "test-api-key",
        }
    )
    set_settings(overrides)
    yield overrides
    set_settings(original)


@pytest.fixture
def stub_eneo_knowledge_client(monkeypatch):
    """Replace the HTTP calls in EneoKnowledgeClient with in-process stubs.

    Returns a dict that grows with each call so tests can assert on what was
    sent (slug, name). The embedding model is picked server-side by
    eneo-knowledge, so eneo no longer supplies it.
    """

    calls: dict[str, list] = {"create": [], "delete": []}

    async def fake_create_collection(self, *, slug, name):
        calls["create"].append({"slug": slug, "name": name})
        return CreatedCollection(
            collection=KnowledgeCollection(
                id=str(uuid4()),
                slug=slug,
                name=name,
                embedding_model_id=str(uuid4()),
            ),
            mcp_server=PairedMcpServer(
                id=str(uuid4()),
                slug=slug,
                name=name,
                endpoint=f"http://eneo-knowledge.test/mcp/{slug}",
                bearer="upstream-bearer",
                template_id="knowledge",
            ),
        )

    async def fake_delete_collection(self, *, slug):
        calls["delete"].append({"slug": slug})

    monkeypatch.setattr(
        EneoKnowledgeClient, "create_collection", fake_create_collection
    )
    monkeypatch.setattr(
        EneoKnowledgeClient, "delete_collection", fake_delete_collection
    )
    return calls


@pytest.fixture
def stub_mcp_connection_probe(monkeypatch):
    """Skip the live tools/list call when registering an MCP server in eneo.

    We stub at the service layer (a single point) rather than at the HTTP
    layer to keep the test orthogonal to the MCP client wire shape.
    """

    async def fake_probe(self, mcp_server, auth_credentials=None, timeout=10):
        return (
            [
                {
                    "name": "search_knowledge",
                    "description": "fake tool from test stub",
                    "input_schema": {"type": "object"},
                }
            ],
            ConnectionResult(success=True, tools_discovered=1),
        )

    monkeypatch.setattr(
        MCPServerService, "_test_connection_and_discover_tools", fake_probe
    )


async def _create_space(client, token: str) -> str:
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"phase2-knowledge-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_knowledge_source_proxies_to_eneo_knowledge(
    client,
    db_container,
    default_user,
    default_user_token,
    configure_knowledge_proxy,
    stub_eneo_knowledge_client,
    stub_mcp_connection_probe,
):
    """POST /knowledge-sources/ creates upstream collection + paired space MCP."""
    space_id = await _create_space(client, default_user_token)

    response = await client.post(
        f"/api/v1/spaces/{space_id}/knowledge-sources/",
        json={"name": "Handboken"},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()

    # Upstream call happened with the user-supplied name + a derived slug.
    # The embedding model is picked by eneo-knowledge server-side; eneo
    # does not send it.
    assert len(stub_eneo_knowledge_client["create"]) == 1
    upstream_call = stub_eneo_knowledge_client["create"][0]
    assert upstream_call["name"] == "Handboken"
    assert upstream_call["slug"].startswith("handboken-")
    assert "embedding_model_id" not in upstream_call

    # Ownership row exists and points at a space-scoped MCP server row.
    knowledge_source_id = payload["knowledge_source_id"]
    async with db_container() as container:
        session = container.session()
        ownership = (
            await session.execute(
                sa.select(
                    KnowledgeSources.tenant_id,
                    KnowledgeSources.space_id,
                    KnowledgeSources.eneo_knowledge_slug,
                    KnowledgeSources.mcp_server_id,
                ).where(KnowledgeSources.id == knowledge_source_id)
            )
        ).one()
        assert ownership.tenant_id == default_user.tenant_id
        assert str(ownership.space_id) == space_id
        assert ownership.eneo_knowledge_slug == upstream_call["slug"]

        mcp_row = (
            await session.execute(
                sa.select(MCPServers.space_id, MCPServers.tenant_id).where(
                    MCPServers.id == ownership.mcp_server_id
                )
            )
        ).one()
        assert str(mcp_row.space_id) == space_id
        assert mcp_row.tenant_id == default_user.tenant_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_space_mcp_also_drops_upstream_collection(
    client,
    db_container,
    default_user,
    default_user_token,
    configure_knowledge_proxy,
    stub_eneo_knowledge_client,
    stub_mcp_connection_probe,
):
    """The existing DELETE endpoint must cascade to eneo-knowledge."""
    space_id = await _create_space(client, default_user_token)

    create_response = await client.post(
        f"/api/v1/spaces/{space_id}/knowledge-sources/",
        json={"name": "Att radera"},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert create_response.status_code == 201, create_response.text
    mcp_server_id = create_response.json()["mcp_server"]["id"]
    upstream_slug = stub_eneo_knowledge_client["create"][0]["slug"]

    delete_response = await client.delete(
        f"/api/v1/spaces/{space_id}/mcp-servers/{mcp_server_id}/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert delete_response.status_code == 204, delete_response.text

    # Upstream was called with the exact slug we created.
    assert len(stub_eneo_knowledge_client["delete"]) == 1
    assert stub_eneo_knowledge_client["delete"][0]["slug"] == upstream_slug

    async with db_container() as container:
        session = container.session()
        # Both rows are gone (FK cascade deletes the knowledge_sources row).
        mcp_left = (
            await session.execute(
                sa.select(MCPServers.id).where(MCPServers.id == UUID(mcp_server_id))
            )
        ).scalar_one_or_none()
        assert mcp_left is None
        ks_left = (
            await session.execute(
                sa.select(KnowledgeSources.id).where(
                    KnowledgeSources.mcp_server_id == UUID(mcp_server_id)
                )
            )
        ).scalar_one_or_none()
        assert ks_left is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_returns_400_when_not_configured(client, default_user_token):
    """Without KNOWLEDGE_ADMIN_* configured the endpoint must fail cleanly."""
    space_id = await _create_space(client, default_user_token)

    response = await client.post(
        f"/api/v1/spaces/{space_id}/knowledge-sources/",
        json={"name": "Should fail"},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 400, response.text
    assert "not configured" in response.text.lower()
