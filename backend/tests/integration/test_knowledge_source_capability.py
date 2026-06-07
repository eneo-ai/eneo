"""Integration tests for the knowledge_source.create config capability (Phase 3).

Exercises the real capability runner, ExternalKnowledgeService, MCP-server
provisioning, and space attachment against a live database. Only the two genuine
external boundaries are stubbed: the provider's HTTP API and the MCP
connection-test that would otherwise reach the provider's endpoint.

Run with:
    uv run pytest tests/integration/test_knowledge_source_capability.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.config_capabilities.capabilities.knowledge_source import (
    CreateKnowledgeSourceInput,
    IngestFilesInput,
)
from intric.config_capabilities.capability import CapabilityContext
from intric.config_capabilities.context import run_capability
from intric.config_capabilities.registry import get_capability
from intric.external_knowledge.client import ProviderCollection
from intric.files.file_models import FileCreate, FileType
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.mcp_servers.application.mcp_server_service import (
    ConnectionResult,
    MCPServerService,
)
from intric.users.user import UserAdd, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _FakeProvider:
    """Stands in for the external provider's HTTP client."""

    def __init__(self, collection: ProviderCollection):
        self._collection = collection
        self.calls = 0

    async def create_collection(self, *, name: str) -> ProviderCollection:
        self.calls += 1
        return self._collection


def _ctx(container, user, space) -> CapabilityContext:
    # assistant_id is unused by knowledge_source.create (it operates on the
    # space); a placeholder keeps the context shape honest.
    return CapabilityContext(
        container=container,
        user=user,
        space=space,
        assistant_id=uuid4(),
        lang="en",
    )


def _stub_connection_test(monkeypatch) -> None:
    """Skip the real MCP handshake; provisioning treats the endpoint as live."""
    monkeypatch.setattr(
        MCPServerService,
        "_test_connection_and_discover_tools",
        AsyncMock(return_value=([], ConnectionResult(success=True))),
    )


async def test_create_provisions_server_and_enables_it_in_the_space(
    db_container, admin_user, monkeypatch
):
    collection = ProviderCollection(
        external_id="ext-1",
        slug="handbook",
        mcp_endpoint="https://provider.example/api/collections/handbook/mcp",
        mcp_token="tok-123",
        tools=[],
    )
    fake = _FakeProvider(collection)
    monkeypatch.setattr(
        "intric.external_knowledge.service.provider_client_from_settings",
        lambda: fake,
    )
    _stub_connection_test(monkeypatch)

    async with db_container(user=admin_user) as container:
        space = await container.space_service().create_space(name="ks-space")
        cap = get_capability("knowledge_source.create")

        result = await run_capability(
            cap,
            _ctx(container, admin_user, space),
            CreateKnowledgeSourceInput(name="Handbook"),
        )

        assert fake.calls == 1

        server = await container.mcp_server_service().get_mcp_server(result.entity_id)
        assert server.is_knowledge_source
        assert server.external_collection_slug == "handbook"
        assert server.external_collection_id == "ext-1"
        assert server.http_url.endswith("/handbook/mcp")

        # The id is surfaced in the summary so the model can chain set_knowledge.
        assert str(result.entity_id) in result.summary

        refreshed = await container.space_repo().one(space.id)
        assert result.entity_id in [s.id for s in refreshed.mcp_servers]


async def test_create_is_denied_for_a_non_space_admin(
    db_container, admin_user, monkeypatch
):
    fake = _FakeProvider(
        ProviderCollection(
            external_id="x",
            slug="x",
            mcp_endpoint="https://provider.example/mcp",
            mcp_token=None,
            tools=[],
        )
    )
    monkeypatch.setattr(
        "intric.external_knowledge.service.provider_client_from_settings",
        lambda: fake,
    )
    _stub_connection_test(monkeypatch)

    async with db_container(user=admin_user) as container:
        space = await container.space_service().create_space(name="locked-space")
        space_id = space.id

    async with db_container(user=admin_user) as container:
        outsider = await container.user_repo().add(
            UserAdd(
                email=f"outsider-{uuid4().hex[:8]}@example.com",
                username=f"outsider_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[],
            )
        )

    async with db_container(user=outsider) as container:
        space = await container.space_repo().one(space_id)
        cap = get_capability("knowledge_source.create")
        with pytest.raises(UnauthorizedException):
            await run_capability(
                cap,
                _ctx(container, outsider, space),
                CreateKnowledgeSourceInput(name="Nope"),
            )

    # The provider must never be contacted for an unauthorized actor.
    assert fake.calls == 0


async def test_create_errors_when_no_provider_is_configured(
    db_container, admin_user, monkeypatch
):
    monkeypatch.setattr(
        "intric.external_knowledge.service.provider_client_from_settings",
        lambda: None,
    )

    async with db_container(user=admin_user) as container:
        space = await container.space_service().create_space(name="inert-space")
        cap = get_capability("knowledge_source.create")
        with pytest.raises(BadRequestException):
            await run_capability(
                cap,
                _ctx(container, admin_user, space),
                CreateKnowledgeSourceInput(name="Handbook"),
            )


class _FakeMCPClient:
    """Captures the deterministic ingest_documents call Eneo makes."""

    calls: list[tuple[str, dict]] = []

    def __init__(self, *, mcp_server, auth_credentials=None):
        self.mcp_server = mcp_server
        self.auth_credentials = auth_credentials

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def call_tool(self, name, arguments):
        _FakeMCPClient.calls.append((name, arguments))
        return {"content": [], "is_error": False}


async def test_ingest_calls_provider_ingest_documents_with_signed_urls(
    db_container, admin_user, monkeypatch
):
    collection = ProviderCollection(
        external_id="ext-1",
        slug="handbook",
        mcp_endpoint="https://provider.example/api/collections/handbook/mcp",
        mcp_token="tok-123",
        tools=[],
    )
    monkeypatch.setattr(
        "intric.external_knowledge.service.provider_client_from_settings",
        lambda: _FakeProvider(collection),
    )
    _stub_connection_test(monkeypatch)
    _FakeMCPClient.calls = []
    monkeypatch.setattr(
        "intric.mcp_servers.infrastructure.client.mcp_client.MCPClient",
        _FakeMCPClient,
    )
    # A tool-facing base URL so signed URLs can be minted.
    from intric.main.config import get_settings

    monkeypatch.setattr(
        get_settings(), "file_reference_base_url", "http://localhost:8123"
    )

    async with db_container(user=admin_user) as container:
        space = await container.space_service().create_space(name="ingest-space")
        ks = await container.external_knowledge_service().create_knowledge_source(
            space=space, name="Handbook"
        )

        repo = container.file_repo()
        files = [
            await repo.add(
                FileCreate(
                    name=name,
                    checksum=uuid4().hex,
                    size=len(text),
                    mimetype="text/plain",
                    file_type=FileType.TEXT,
                    text=text,
                    storage_key=f"s3/{name}",  # original retained -> signed URL exists
                    user_id=admin_user.id,
                    tenant_id=admin_user.tenant_id,
                )
            )
            for name, text in (("a.txt", "alpha"), ("b.txt", "beta"))
        ]

        refreshed = await container.space_repo().one(space.id)
        cap = get_capability("knowledge_source.ingest_files")
        result = await run_capability(
            cap,
            _ctx(container, admin_user, refreshed),
            IngestFilesInput(knowledge_source_id=ks.id, file_ids=[f.id for f in files]),
        )

    assert result.data == {"ingested": 2}
    assert len(_FakeMCPClient.calls) == 1
    name, args = _FakeMCPClient.calls[0]
    assert name == "ingest_documents"
    assert len(args["urls"]) == 2
    assert all("/download/?token=" in u for u in args["urls"])
