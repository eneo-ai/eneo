"""Unit tests for the edit-mode config persona + the is_knowledge_source field."""

from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from intric.assistant_config_mcp import build_config_persona
from intric.main.config import Settings
from intric.mcp_servers.domain.entities.mcp_server import MCPServer
from intric.mcp_servers.presentation.assemblers.mcp_server_assembler import (
    MCPServerAssembler,
    MCPServerSettingsAssembler,
)


def _settings(*, url, key, required) -> Settings:
    # build_config_persona only reads these three fields.
    return cast(
        Settings,
        SimpleNamespace(
            external_knowledge_provider_url=url,
            external_knowledge_provider_api_key=key,
            collections_require_external_provider=required,
        ),
    )


def test_persona_external_only_forbids_native_collection():
    persona = build_config_persona(
        "en", _settings(url="https://p", key="k", required=True)
    )
    assert "knowledge_source_create" in persona
    assert "Never use" in persona
    # naming + two-step clauses are present when external is configured
    assert "is_knowledge_source" in persona
    assert "assistant_set_mcp_server" in persona


def test_persona_prefer_external_when_both_available():
    persona = build_config_persona(
        "en", _settings(url="https://p", key="k", required=False)
    )
    assert "Prefer the external knowledge source" in persona
    assert "knowledge_source_create" in persona


def test_persona_native_only_omits_knowledge_source():
    persona = build_config_persona("en", _settings(url=None, key=None, required=False))
    assert "collection_create" in persona
    # no external provider -> no knowledge-source routing / naming / two-step
    assert "knowledge_source_create" not in persona
    assert "assistant_set_mcp_server" not in persona


def test_persona_swedish_uses_kunskapskalla():
    persona = build_config_persona(
        "sv", _settings(url="https://p", key="k", required=True)
    )
    assert "kunskapskälla" in persona
    assert "knowledge_source_create" in persona


def _server(*, knowledge_source: bool) -> MCPServer:
    return MCPServer(
        tenant_id=uuid4(),
        name="Handbook" if knowledge_source else "Search",
        http_url="https://provider.example/mcp/handbook",
        external_collection_slug="handbook" if knowledge_source else None,
    )


def test_assembler_exposes_is_knowledge_source():
    ks = _server(knowledge_source=True)
    tool = _server(knowledge_source=False)

    assert MCPServerAssembler().from_domain_to_model(ks).is_knowledge_source is True
    assert MCPServerAssembler().from_domain_to_model(tool).is_knowledge_source is False

    assert MCPServerAssembler.to_dict_with_tools(ks)["is_knowledge_source"] is True
    assert MCPServerAssembler.to_dict_with_tools(tool)["is_knowledge_source"] is False

    settings_dto = MCPServerSettingsAssembler().from_domain_to_model(ks)
    assert settings_dto.is_knowledge_source is True
