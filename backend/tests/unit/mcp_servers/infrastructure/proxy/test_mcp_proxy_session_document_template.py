"""The proxy hands the organisation's document template to the file-creation
provider's create_document, and only where a template belongs: a Word or PDF
rendering that names no template of its own and revises nothing."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.document_templates.domain import BUILTIN_REFERENCE, DocumentTemplateReference
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from eneo.mcp_servers.infrastructure.proxy import mcp_proxy_session as proxy_module
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session import MCPProxySession

REFERENCE = DocumentTemplateReference(
    name="Rapportmall",
    source="tenant",
    template_id=uuid4(),
    url="https://eneo.example/api/v1/document-templates/x/original/download/?token=t",
    filename="rapportmall.docx",
)
WITH_TEMPLATE = {
    "type": "object",
    "properties": {"content": {"type": "string"}, "template": {"type": "object"}},
}


def _server(
    purpose: str = "file_creation", schema: dict | None = WITH_TEMPLATE
) -> MCPServer:
    server = MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="files",
        http_url="http://runtime/mcp/file-creation",
        purpose=purpose,
    )
    server.tools = [
        MCPServerTool(
            id=uuid4(),
            mcp_server_id=server.id,
            name="create_document",
            description="Create a document",
            input_schema=schema,
        )
    ]
    return server


def _proxy(monkeypatch, server: MCPServer) -> MCPProxySession:
    monkeypatch.setattr(
        proxy_module, "get_settings", lambda: SimpleNamespace(mcp_apps_enabled=False)
    )
    return MCPProxySession([server], identity_headers={})


@pytest.mark.parametrize(
    "arguments,injected",
    [
        ({"content": "x", "format": "docx"}, True),
        ({"content": "x", "format": "pdf"}, True),
        ({"content": "x"}, False),
        ({"content": "x", "format": "md"}, False),
        (
            {
                "content": "x",
                "format": "docx",
                "template": {"url": "u", "filename": "a.docx"},
            },
            False,
        ),
        (
            {
                "content": "x",
                "format": "docx",
                "revises": {"url": "u", "filename": "a.docx"},
            },
            False,
        ),
    ],
)
def test_template_is_added_only_to_word_and_pdf_renders_without_one(
    monkeypatch, arguments, injected
):
    server = _server()
    proxy = _proxy(monkeypatch, server)
    proxy.set_document_template(REFERENCE)
    result = proxy._with_document_template(server, "create_document", dict(arguments))
    if injected:
        assert result == {**arguments, "template": REFERENCE.argument}
    else:
        assert result == arguments


def test_other_tools_servers_schemas_and_the_builtin_template_change_nothing(
    monkeypatch,
):
    arguments = {"content": "x", "format": "docx"}
    server = _server()
    proxy = _proxy(monkeypatch, server)
    assert (
        proxy._with_document_template(server, "create_document", arguments) == arguments
    )
    proxy.set_document_template(BUILTIN_REFERENCE)
    assert (
        proxy._with_document_template(server, "create_document", arguments) == arguments
    )
    proxy.set_document_template(REFERENCE)
    assert (
        proxy._with_document_template(server, "fill_template", arguments) == arguments
    )
    general = _server(purpose="general")
    assert (
        proxy._with_document_template(general, "create_document", arguments)
        == arguments
    )
    without = _server(schema={"type": "object", "properties": {"content": {}}})
    assert (
        proxy._with_document_template(without, "create_document", arguments)
        == arguments
    )
