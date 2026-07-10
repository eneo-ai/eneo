"""Unit tests for the loopback files-MCP server.

Covers the ephemeral-server builder, the signed-URL reference parsing and
authorization checks of read_file (the signed token is the sole authorizer,
double-checked against the caller's tenant), and the paging of extracted text.
"""

import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.authentication.signed_urls import (
    build_signed_download_url,
    generate_signed_token,
)
from eneo.files.file_models import ContentDisposition, FileType
from eneo.internal_mcp.files import (
    FILES_SERVER_NAME,
    INVALID_LINK_MESSAGE,
    NOT_A_REFERENCE_MESSAGE,
    NOT_FOUND_MESSAGE,
    _file_content,
    _parse_reference_url,
    build_files_mcp_server,
    mcp,
    read_file,
)
from eneo.internal_mcp.registry import internal_mcp_mounts
from eneo.main.exceptions import NotFoundException


def _signed_url(file_id, tenant_id, base_url="https://eneo.example"):
    return build_signed_download_url(
        file_id=file_id,
        base_url=base_url,
        expires_in=3600,
        tenant_id=tenant_id,
        variant="original",
    )


def _file(**overrides):
    defaults = dict(
        id=uuid4(),
        name="policy.pdf",
        mimetype="application/pdf",
        file_type=FileType.TEXT,
        text="Waste is collected every other week.",
        tenant_id=uuid4(),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _patch_tool_context(
    monkeypatch, *, file=None, user_tenant_id=None, repo_error=None
):
    """Replace the container bootstrap with an in-memory file lookup."""

    @asynccontextmanager
    async def fake_context(_ctx):
        async def get_by_id(file_id):
            if repo_error is not None:
                raise repo_error
            if file is None:
                raise NotFoundException()
            return file

        container = SimpleNamespace(
            file_repo=lambda: SimpleNamespace(get_by_id=get_by_id)
        )
        user = SimpleNamespace(tenant_id=user_tenant_id)
        yield SimpleNamespace(container=container, user=user, assistant_id=uuid4())

    monkeypatch.setattr("eneo.internal_mcp.files.internal_tool_context", fake_context)


class TestBuildFilesMcpServer:
    @pytest.mark.asyncio
    async def test_tool_entities_mirror_live_tool_list(self):
        server = await build_files_mcp_server(token="tok", tenant_id=uuid4())

        live_tools = await mcp.list_tools()
        assert [t.name for t in server.tools] == [t.name for t in live_tools]
        assert [t.description for t in server.tools] == [
            t.description for t in live_tools
        ]
        assert [t.input_schema for t in server.tools] == [
            t.inputSchema for t in live_tools
        ]
        assert "read_file" in {t.name for t in server.tools}

    @pytest.mark.asyncio
    async def test_server_is_bearer_authenticated_loopback(self):
        server = await build_files_mcp_server(token="tok", tenant_id=uuid4())

        assert server.name == FILES_SERVER_NAME
        assert server.http_auth_type == "bearer"
        assert server.http_auth_config_schema == {"token": "tok"}
        assert server.http_url.endswith("/internal-mcp/files/mcp")
        assert server.is_enabled


class TestInternalMcpMounts:
    def test_every_internal_server_is_mounted(self):
        paths = [path for path, _app in internal_mcp_mounts()]
        assert "/internal-mcp/knowledge" in paths
        assert "/internal-mcp/files" in paths


class TestParseReferenceUrl:
    def test_extracts_file_id_and_token_from_signed_url(self):
        file_id = uuid4()
        url = _signed_url(file_id, tenant_id=uuid4())

        parsed = _parse_reference_url(url)

        assert parsed is not None
        parsed_id, token = parsed
        assert parsed_id == file_id
        assert token == url.split("token=")[1]

    def test_host_is_irrelevant(self):
        # The signed token authorizes, not the host, so links minted against
        # the public origin and the tool-facing base URL both resolve.
        file_id = uuid4()
        url = _signed_url(file_id, tenant_id=uuid4(), base_url="http://internal:8123")

        parsed = _parse_reference_url(url)
        assert parsed is not None
        assert parsed[0] == file_id

    def test_accepts_path_without_trailing_slash(self):
        file_id = uuid4()
        url = f"https://eneo.example/api/v1/files/{file_id}/download?token=tok"

        parsed = _parse_reference_url(url)
        assert parsed == (file_id, "tok")

    def test_rejects_url_without_token(self):
        file_id = uuid4()
        assert (
            _parse_reference_url(
                f"https://eneo.example/api/v1/files/{file_id}/download/"
            )
            is None
        )

    def test_rejects_non_download_urls(self):
        assert _parse_reference_url("https://example.com/some/other/path") is None
        assert _parse_reference_url("not a url at all") is None


class TestReadFileAuthorization:
    @pytest.mark.asyncio
    async def test_non_reference_url_is_named_as_such(self):
        content = await read_file("https://example.com/file.pdf", ctx=None)
        assert content[0].text == NOT_A_REFERENCE_MESSAGE

    @pytest.mark.asyncio
    async def test_tampered_payload_reads_as_invalid_link(self):
        file_id = uuid4()
        url = _signed_url(file_id, tenant_id=uuid4())
        base, token = url.split("token=")
        message, signature = token.split(".")
        flipped = ("A" if message[0] != "A" else "B") + message[1:]

        content = await read_file(f"{base}token={flipped}.{signature}", ctx=None)
        assert content[0].text == INVALID_LINK_MESSAGE

    @pytest.mark.asyncio
    async def test_expired_token_reads_as_invalid_link(self):
        file_id = uuid4()
        token = generate_signed_token(
            file_id=file_id,
            expires_at=int(time.time()) - 10,
            content_disposition=ContentDisposition.ATTACHMENT,
            tenant_id=uuid4(),
            variant="original",
        )
        url = f"https://eneo.example/api/v1/files/{file_id}/download/?token={token}"

        content = await read_file(url, ctx=None)
        assert content[0].text == INVALID_LINK_MESSAGE

    @pytest.mark.asyncio
    async def test_token_for_another_file_reads_as_invalid_link(self):
        # A valid token spliced onto another file's URL must not resolve.
        other_url = _signed_url(uuid4(), tenant_id=uuid4())
        token = other_url.split("token=")[1]
        url = f"https://eneo.example/api/v1/files/{uuid4()}/download/?token={token}"

        content = await read_file(url, ctx=None)
        assert content[0].text == INVALID_LINK_MESSAGE

    @pytest.mark.asyncio
    async def test_missing_file_and_tenant_mismatch_are_indistinguishable(
        self, monkeypatch
    ):
        tenant_id = uuid4()
        file = _file(tenant_id=tenant_id)
        url = _signed_url(file.id, tenant_id=tenant_id)

        _patch_tool_context(monkeypatch, file=None, user_tenant_id=tenant_id)
        missing = await read_file(url, ctx=None)

        _patch_tool_context(monkeypatch, file=file, user_tenant_id=uuid4())
        foreign_caller = await read_file(url, ctx=None)

        token_tenant_url = _signed_url(file.id, tenant_id=uuid4())
        _patch_tool_context(monkeypatch, file=file, user_tenant_id=tenant_id)
        foreign_token = await read_file(token_tenant_url, ctx=None)

        assert missing[0].text == NOT_FOUND_MESSAGE
        assert foreign_caller[0].text == NOT_FOUND_MESSAGE
        assert foreign_token[0].text == NOT_FOUND_MESSAGE

    @pytest.mark.asyncio
    async def test_authorized_read_returns_the_text(self, monkeypatch):
        tenant_id = uuid4()
        file = _file(tenant_id=tenant_id)
        url = _signed_url(file.id, tenant_id=tenant_id)
        _patch_tool_context(monkeypatch, file=file, user_tenant_id=tenant_id)

        content = await read_file(url, ctx=None)

        assert content[0].text == (
            "File: policy.pdf (application/pdf)\n\nWaste is collected every other week."
        )

    @pytest.mark.asyncio
    async def test_unexpected_repository_error_propagates(self, monkeypatch):
        tenant_id = uuid4()
        file_id = uuid4()
        url = _signed_url(file_id, tenant_id=tenant_id)
        _patch_tool_context(
            monkeypatch,
            user_tenant_id=tenant_id,
            repo_error=RuntimeError("database unavailable"),
        )

        with pytest.raises(RuntimeError, match="database unavailable"):
            await read_file(url, ctx=None)


class TestFileContent:
    def test_short_file_fits_without_notice(self):
        content = _file_content(_file(text="Short."), offset=0, page_cap=100)

        assert len(content) == 1
        assert content[0].text == "File: policy.pdf (application/pdf)\n\nShort."

    def test_long_file_truncates_with_resume_offset(self):
        content = _file_content(_file(text="a" * 250), offset=0, page_cap=100)

        assert len(content) == 2
        assert content[0].text.endswith("a" * 100)
        assert "character 100 of 250" in content[1].text
        assert "offset=100" in content[1].text

    def test_offset_pages_through_the_file(self):
        content = _file_content(
            _file(text="a" * 150 + "b" * 50), offset=150, page_cap=100
        )

        assert len(content) == 1
        assert content[0].text.endswith("b" * 50)

    def test_offset_past_end_reports_file_length(self):
        content = _file_content(_file(text="abc"), offset=10, page_cap=100)

        assert len(content) == 1
        assert "past the end" in content[0].text

    def test_image_points_at_vision(self):
        content = _file_content(
            _file(file_type=FileType.IMAGE, mimetype="image/png", text=None),
            offset=0,
            page_cap=100,
        )
        assert "image" in content[0].text

    def test_audio_points_at_transcription(self):
        content = _file_content(
            _file(file_type=FileType.AUDIO, mimetype="audio/mpeg", text=None),
            offset=0,
            page_cap=100,
        )
        assert "transcription" in content[0].text

    def test_text_file_without_text_says_so(self):
        content = _file_content(_file(text=None), offset=0, page_cap=100)
        assert "No extracted text" in content[0].text


class TestToolSteering:
    def test_read_file_defers_to_more_specific_tools(self):
        doc = read_file.__doc__ or ""
        assert "fallback" in doc
        assert "prefer that tool" in doc

    def test_read_file_documents_the_offset_resume(self):
        assert "offset" in (read_file.__doc__ or "")
