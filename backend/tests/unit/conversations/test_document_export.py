"""A Markdown document of a conversation is exported by the provider of the
assistant's file-creation capability, found by purpose. The file comes back
only when the provider returned the format asked for and it passes the checks
every generated document passes; nothing is stored."""

import base64
import io
import zipfile
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from eneo.conversations.document_export import (
    DocumentExportFailed,
    DocumentExportUnavailable,
    document_export_availability,
    export_compatibility,
    export_document,
)
from eneo.main.exceptions import NotFoundException
from eneo.mcp_servers.domain.entities.mcp_server import (
    DOCX_MIME_TYPE,
    MARKDOWN_MIME_TYPE,
    PDF_MIME_TYPE,
)

SCHEMA = {
    "type": "object",
    "properties": {
        **{name: {"type": "string"} for name in ("title", "content", "filename")},
        "format": {"type": "string", "enum": ["docx", "pdf"]},
    },
    "required": ["title", "content"],
}
ASSISTANT_ID = uuid4()
SERVER_ID = uuid4()
FILE_ID = uuid4()
MARKDOWN = "# Plan\n\nFas ett startar i maj.\n"
PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def _docx() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


def _conversation(*, mimetype: str = MARKDOWN_MIME_TYPE, file_id: UUID = FILE_ID):
    document = SimpleNamespace(id=file_id, name="Införandeplan.md", mimetype=mimetype)
    return SimpleNamespace(
        assistant=SimpleNamespace(id=ASSISTANT_ID),
        questions=[
            SimpleNamespace(assistant_id=ASSISTANT_ID, generated_files=[document])
        ],
    )


class _Assistants:
    def __init__(self, server):
        self.server = server
        self.asked: list[dict] = []

    async def capability_server(self, **kwargs):
        self.asked.append(kwargs)
        return self.server


class _Files:
    def __init__(self):
        self.read: list[UUID] = []

    async def get_file_content(self, file_id: UUID):
        self.read.append(file_id)
        return SimpleNamespace(text=MARKDOWN)


class _Proxy:
    def __init__(self, result: dict, tool: str | None = "files__create_document"):
        self.result = result
        self.tool = tool
        self.called: list[tuple[str, dict]] = []
        self.closed = False

    def prefixed_tool_name(self, mcp_server_id: UUID, tool_name: str) -> str | None:
        return self.tool if tool_name == "create_document" else None

    async def prepare_tools_for_context(self):
        pass

    async def call_tools_parallel(self, calls):
        self.called.extend(calls)
        return [self.result]

    async def close(self):
        self.closed = True


def _file_result(data: bytes, mime_type: str) -> dict:
    return {
        "content": [
            {"type": "text", "text": "{}"},
            {
                "type": "file",
                "data": base64.b64encode(data).decode(),
                "mime_type": mime_type,
                "filename": "x",
            },
        ]
    }


async def _export(proxy: _Proxy, *, format="docx", conversation=None, server=True):
    assistants = _Assistants(
        SimpleNamespace(
            id=SERVER_ID,
            name="Create files",
            tools=[SimpleNamespace(name="create_document", input_schema=SCHEMA)],
        )
        if server
        else None
    )
    files = _Files()
    exported = await export_document(
        conversation=conversation or _conversation(),
        file_id=FILE_ID,
        format=format,
        assistant_service=assistants,  # type: ignore[arg-type]
        file_service=files,  # type: ignore[arg-type]
        proxy_factory=SimpleNamespace(create=lambda servers, **kwargs: proxy),  # type: ignore[arg-type]
        identity_headers={},
    )
    return exported, assistants, files


async def test_document_is_rendered_by_the_file_creation_provider():
    proxy = _Proxy(_file_result(_docx(), DOCX_MIME_TYPE))

    exported, assistants, files = await _export(proxy)

    assert assistants.asked == [
        {"assistant_id": ASSISTANT_ID, "purpose": "file_creation"}
    ]
    assert proxy.called == [
        (
            "files__create_document",
            {
                "title": "Införandeplan",
                "content": MARKDOWN,
                "format": "docx",
                "filename": "Införandeplan",
            },
        )
    ]
    assert exported.filename == "Införandeplan.docx"
    assert exported.mime_type == DOCX_MIME_TYPE
    assert exported.data == _docx()
    assert exported.mcp_server_id == SERVER_ID
    assert files.read == [FILE_ID]
    assert proxy.closed


async def test_pdf_is_exported_the_same_way():
    exported, _, _ = await _export(
        _Proxy(_file_result(PDF, PDF_MIME_TYPE)), format="pdf"
    )

    assert (exported.filename, exported.mime_type) == (
        "Införandeplan.pdf",
        PDF_MIME_TYPE,
    )


async def test_assistant_without_a_provider_cannot_export():
    with pytest.raises(DocumentExportUnavailable):
        await _export(_Proxy({}), server=False)


async def test_provider_without_the_document_tool_cannot_export():
    proxy = _Proxy({}, tool=None)

    with pytest.raises(DocumentExportUnavailable):
        await _export(proxy)

    assert proxy.called == []
    assert proxy.closed


@pytest.mark.parametrize(
    "result",
    [
        # Another format than the one asked for.
        _file_result(PDF, PDF_MIME_TYPE),
        # The right type on the label, other bytes inside.
        _file_result(b"not a word file", DOCX_MIME_TYPE),
        # No file at all, or a failed call.
        {"content": [{"type": "text", "text": "TIMEOUT"}], "is_error": True},
        {"content": []},
    ],
)
async def test_anything_but_the_format_asked_for_is_refused(result):
    proxy = _Proxy(result)

    with pytest.raises(DocumentExportFailed):
        await _export(proxy)

    assert proxy.closed


@pytest.mark.parametrize(
    "conversation",
    [
        # A Word file is already what an export would give.
        _conversation(mimetype=DOCX_MIME_TYPE),
        # A file of another conversation.
        _conversation(file_id=uuid4()),
    ],
)
async def test_only_a_markdown_document_of_the_conversation_is_exported(conversation):
    proxy = _Proxy(_file_result(_docx(), DOCX_MIME_TYPE))

    with pytest.raises(NotFoundException):
        await _export(proxy, conversation=conversation)

    assert proxy.called == []


@pytest.mark.parametrize("format", ["docx", "pdf"])
def test_native_contract_validates_exact_document(format):
    args = {"title": "Plan", "filename": "Plan", "content": "# Text", "format": format}
    assert export_compatibility(SCHEMA, args).available
    import copy

    limited = copy.deepcopy(SCHEMA)
    limited["properties"]["content"]["maxLength"] = 2
    assert export_compatibility(limited, args).reason == "document_unsupported"


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"required": ["title", "content", "template"]}, "incompatible_tool"),
        ({"required": [{}]}, "incompatible_tool"),
        ({"$ref": "https://untrusted.invalid/schema"}, "incompatible_tool"),
        ({"type": "array"}, "incompatible_tool"),
        ({"properties": {}}, "incompatible_tool"),
        ({"allOf": []}, "incompatible_tool"),
    ],
)
def test_unsupported_contracts_fail_closed(change, reason):
    args = {"title": "Plan", "filename": "Plan", "content": "Text", "format": "pdf"}
    assert export_compatibility({**SCHEMA, **change}, args).reason == reason


async def test_discovery_is_format_specific_and_never_calls_renderer():
    import copy

    schema = copy.deepcopy(SCHEMA)
    schema["properties"]["format"]["enum"] = ["docx"]
    server = SimpleNamespace(
        id=SERVER_ID,
        tools=[SimpleNamespace(name="create_document", input_schema=schema)],
    )
    proxy = _Proxy({})
    kwargs = dict(
        conversation=_conversation(),
        file_id=FILE_ID,
        assistant_service=_Assistants(server),
        file_service=_Files(),
        proxy_factory=SimpleNamespace(create=lambda *a, **k: proxy),
        identity_headers={},
    )
    state = await document_export_availability(**kwargs)
    assert state.docx.available
    assert state.pdf.reason == "format_unsupported"
    assert proxy.called == []
    assert proxy.closed
    # Re-resolve rather than trusting the earlier successful discovery.
    kwargs["assistant_service"].server = None
    with pytest.raises(DocumentExportUnavailable):
        await export_document(**kwargs, format="docx")
    assert proxy.called == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_enabled_by_default": False},
        {"removed_from_remote": True},
        {"requires_approval": True, "description": None, "input_schema": None},
    ],
)
async def test_real_proxy_catalogue_excludes_non_callable_export_tools(overrides):
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
    from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
        MCPProxySessionFactory,
    )

    definition = dict(
        mcp_server_id=SERVER_ID,
        name="create_document",
        description="Render a document",
        input_schema=SCHEMA,
    )
    server = MCPServer(
        tenant_id=uuid4(),
        id=SERVER_ID,
        name="Provider",
        http_url="http://unused.invalid/mcp",
        purpose="file_creation",
        tools=[MCPServerTool(**{**definition, **overrides})],
    )
    state = await document_export_availability(
        conversation=_conversation(),
        file_id=FILE_ID,
        assistant_service=_Assistants(server),
        file_service=_Files(),
        proxy_factory=MCPProxySessionFactory(),
        identity_headers={},
    )
    assert state.docx.reason == "tool_unavailable"
    assert state.pdf.reason == "tool_unavailable"


async def test_identity_catalogue_controls_native_export_discovery():
    from unittest.mock import AsyncMock, patch

    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
    from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
        MCPProxySessionFactory,
    )
    from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_session import MCPProxySession

    server = MCPServer(
        tenant_id=uuid4(),
        id=SERVER_ID,
        name="Provider",
        http_url="http://unused.invalid/mcp",
        purpose="file_creation",
        forward_identity=True,
        tools=[
            MCPServerTool(
                mcp_server_id=SERVER_ID,
                name="create_document",
                description="Render",
                input_schema=SCHEMA,
            )
        ],
    )
    with patch.object(
        MCPProxySession, "_discover_identity_scoped_tools", AsyncMock(return_value=[])
    ):
        state = await document_export_availability(
            conversation=_conversation(),
            file_id=FILE_ID,
            assistant_service=_Assistants(server),
            file_service=_Files(),
            proxy_factory=MCPProxySessionFactory(),
            identity_headers={"X-Eneo-User-Id": str(uuid4())},
        )
    assert state.docx.reason == "tool_unavailable"
