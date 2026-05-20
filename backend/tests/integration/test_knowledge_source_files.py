"""Phase 3 tests for the file-upload proxy flow on knowledge sources.

What this file owns:
- Happy-path upload + list + delete proxy through the eneo-knowledge HTTP
  surface (with the upstream client stubbed).
- Tenant + space gating on file ops: a knowledge source owned by space A
  cannot be acted on through space B's URL, nor by users in other tenants.

Reuses the same configure_knowledge_proxy + stub_eneo_knowledge_client
+ stub_mcp_connection_probe fixtures pattern as ``test_knowledge_sources.py``,
but extends the upstream stub with file methods.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.spaces_table import Spaces, SpacesUsers
from intric.eneo_knowledge.client import (
    CreatedCollection,
    EneoKnowledgeClient,
    KnowledgeCollection,
    PairedMcpServer,
    UploadedFileInfo,
)
from intric.eneo_knowledge.table import KnowledgeSources
from intric.main.config import get_settings, set_settings
from intric.mcp_servers.application.mcp_server_service import (
    ConnectionResult,
    MCPServerService,
)
from intric.spaces.api.space_models import SpaceRoleValue


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
    """Stub all upstream HTTP — collection create/delete + file methods.

    File state lives in ``files_by_slug`` so list/delete reflect prior uploads
    deterministically. Tests can inspect ``calls`` for assertion.
    """
    calls: dict[str, list] = {
        "create_collection": [],
        "delete_collection": [],
        "upload_file": [],
        "list_files": [],
        "delete_file": [],
    }
    files_by_slug: dict[str, list[UploadedFileInfo]] = {}

    async def fake_create_collection(self, *, slug, name):
        calls["create_collection"].append({"slug": slug, "name": name})
        files_by_slug.setdefault(slug, [])
        return CreatedCollection(
            collection=KnowledgeCollection(
                id=str(uuid4()), slug=slug, name=name, embedding_model_id=str(uuid4())
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
        calls["delete_collection"].append({"slug": slug})
        files_by_slug.pop(slug, None)

    async def fake_upload_file(self, *, slug, filename, content, content_type):
        calls["upload_file"].append(
            {
                "slug": slug,
                "filename": filename,
                "size": len(content),
                "content_type": content_type,
            }
        )
        info = UploadedFileInfo(
            id=str(uuid4()),
            name=filename,
            mime_type=content_type,
            size_bytes=len(content),
            status="queued",
            error=None,
            page_count=None,
            created_at="2026-05-19T00:00:00Z",
            processed_at=None,
        )
        files_by_slug.setdefault(slug, []).append(info)
        return info

    async def fake_list_files(self, *, slug):
        calls["list_files"].append({"slug": slug})
        return list(files_by_slug.get(slug, []))

    async def fake_delete_file(self, *, slug, file_id):
        calls["delete_file"].append({"slug": slug, "file_id": file_id})
        files_by_slug[slug] = [
            f for f in files_by_slug.get(slug, []) if f.id != file_id
        ]

    monkeypatch.setattr(
        EneoKnowledgeClient, "create_collection", fake_create_collection
    )
    monkeypatch.setattr(
        EneoKnowledgeClient, "delete_collection", fake_delete_collection
    )
    monkeypatch.setattr(EneoKnowledgeClient, "upload_file", fake_upload_file)
    monkeypatch.setattr(EneoKnowledgeClient, "list_files", fake_list_files)
    monkeypatch.setattr(EneoKnowledgeClient, "delete_file", fake_delete_file)
    return calls


@pytest.fixture
def stub_mcp_connection_probe(monkeypatch):
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
        json={"name": f"phase3-files-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_knowledge_source(
    client, token: str, space_id: str, name: str
) -> dict:
    response = await client.post(
        f"/api/v1/spaces/{space_id}/knowledge-sources/",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upload_list_delete_roundtrip(
    client,
    default_user_token,
    configure_knowledge_proxy,
    stub_eneo_knowledge_client,
    stub_mcp_connection_probe,
):
    """Upload then list returns the file; delete then list returns empty."""
    space_id = await _create_space(client, default_user_token)
    ks = await _create_knowledge_source(
        client, default_user_token, space_id, "Handboken"
    )
    ks_id = ks["knowledge_source_id"]

    upload = await client.post(
        f"/api/v1/spaces/{space_id}/knowledge-sources/{ks_id}/files/",
        files={"file": ("handbok.pdf", b"%PDF-1.4 fake content", "application/pdf")},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert upload.status_code == 202, upload.text
    uploaded = upload.json()
    assert uploaded["name"] == "handbok.pdf"
    assert uploaded["status"] == "queued"

    listed = await client.get(
        f"/api/v1/spaces/{space_id}/knowledge-sources/{ks_id}/files/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()
    assert len(items) == 1
    assert items[0]["id"] == uploaded["id"]

    deleted = await client.delete(
        f"/api/v1/spaces/{space_id}/knowledge-sources/{ks_id}/files/{uploaded['id']}/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert deleted.status_code == 204, deleted.text

    listed_again = await client.get(
        f"/api/v1/spaces/{space_id}/knowledge-sources/{ks_id}/files/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert listed_again.status_code == 200
    assert listed_again.json() == []

    # Upstream was called with the matching slug at every step.
    upstream_slug = stub_eneo_knowledge_client["create_collection"][0]["slug"]
    assert stub_eneo_knowledge_client["upload_file"][0]["slug"] == upstream_slug
    assert stub_eneo_knowledge_client["delete_file"][0]["slug"] == upstream_slug


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cross_space_file_op_rejected(
    client,
    default_user_token,
    configure_knowledge_proxy,
    stub_eneo_knowledge_client,
    stub_mcp_connection_probe,
):
    """A knowledge source owned by space A cannot be addressed via space B's URL."""
    space_a = await _create_space(client, default_user_token)
    space_b = await _create_space(client, default_user_token)
    ks = await _create_knowledge_source(client, default_user_token, space_a, "A-only")
    ks_id = ks["knowledge_source_id"]

    cross_upload = await client.post(
        f"/api/v1/spaces/{space_b}/knowledge-sources/{ks_id}/files/",
        files={"file": ("x.pdf", b"x", "application/pdf")},
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert cross_upload.status_code == 404, cross_upload.text

    cross_list = await client.get(
        f"/api/v1/spaces/{space_b}/knowledge-sources/{ks_id}/files/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert cross_list.status_code == 404, cross_list.text

    # And the upstream upload was never called (gate fires before HTTP).
    assert stub_eneo_knowledge_client["upload_file"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cross_tenant_file_op_rejected(
    client,
    db_container,
    default_user,
    default_user_token,
    configure_knowledge_proxy,
    stub_eneo_knowledge_client,
    stub_mcp_connection_probe,
    tenant_factory,
    user_factory,
    patch_auth_service_jwt,
):
    """A row owned by tenant A is invisible to tenant B even with knowledge_source_id."""
    space_a = await _create_space(client, default_user_token)
    ks = await _create_knowledge_source(
        client, default_user_token, space_a, "Tenant-A only"
    )
    ks_id = ks["knowledge_source_id"]

    async with db_container() as container:
        session = container.session()
        other_tenant = await tenant_factory(session)
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        other_space = Spaces(
            name=f"tenantB-{uuid4().hex[:8]}",
            tenant_id=other_tenant.id,
            user_id=None,
            tenant_space_id=None,
        )
        session.add(other_space)
        await session.flush()
        await session.execute(
            sa.insert(SpacesUsers).values(
                space_id=other_space.id,
                user_id=other_user.id,
                role=SpaceRoleValue.ADMIN.value,
            )
        )
        await session.commit()
        other_space_id = str(other_space.id)
        auth_service = container.auth_service()
        other_user_token = auth_service.create_access_token_for_user(other_user)

    # Probing tenant A's space directly: rejected by space-membership gate.
    direct = await client.get(
        f"/api/v1/spaces/{space_a}/knowledge-sources/{ks_id}/files/",
        headers={"Authorization": f"Bearer {other_user_token}"},
    )
    assert direct.status_code in (401, 403, 404), direct.text

    # Even using their OWN space's URL with tenant A's knowledge_source_id: 404.
    spoof = await client.get(
        f"/api/v1/spaces/{other_space_id}/knowledge-sources/{ks_id}/files/",
        headers={"Authorization": f"Bearer {other_user_token}"},
    )
    assert spoof.status_code == 404, spoof.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_returns_knowledge_sources_for_space(
    client,
    default_user_token,
    configure_knowledge_proxy,
    stub_eneo_knowledge_client,
    stub_mcp_connection_probe,
    db_container,
    default_user,
):
    """GET /knowledge-sources/ returns the rows owned by this space, scoped."""
    space_id = await _create_space(client, default_user_token)
    ks1 = await _create_knowledge_source(client, default_user_token, space_id, "First")
    ks2 = await _create_knowledge_source(client, default_user_token, space_id, "Second")

    response = await client.get(
        f"/api/v1/spaces/{space_id}/knowledge-sources/",
        headers={"Authorization": f"Bearer {default_user_token}"},
    )
    assert response.status_code == 200, response.text
    ids = {row["id"] for row in response.json()}
    assert ks1["knowledge_source_id"] in ids
    assert ks2["knowledge_source_id"] in ids

    # Each row points at its MCP server. The mapping must round-trip cleanly.
    async with db_container() as container:
        session = container.session()
        rows = (
            await session.execute(
                sa.select(KnowledgeSources.id, KnowledgeSources.mcp_server_id).where(
                    KnowledgeSources.space_id == space_id
                )
            )
        ).all()
        db_pairs = {(str(r.id), str(r.mcp_server_id)) for r in rows}
        api_pairs = {(r["id"], r["mcp_server_id"]) for r in response.json()}
        assert db_pairs == api_pairs
