"""Orchestration for provider-backed knowledge sources.

A knowledge source is created by asking the external provider for a collection,
then registering that collection's MCP endpoint as a space-scoped MCP server. The
server's tools are enabled-by-default, so simply attaching it to the space makes
the knowledge usable; granting it to an assistant is a separate step
(``assistant.set_knowledge``).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from intric.authentication.signed_urls import build_signed_download_url
from intric.external_knowledge.client import provider_client_from_settings
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException, UnauthorizedException

if TYPE_CHECKING:
    from intric.actors import ActorManager
    from intric.files.file_service import FileService
    from intric.mcp_servers.application.mcp_server_service import MCPServerService
    from intric.mcp_servers.domain.entities.mcp_server import MCPServer
    from intric.settings.encryption_service import EncryptionService
    from intric.spaces.space import Space
    from intric.spaces.space_service import SpaceService
    from intric.users.user import UserInDB

# The retrieval-collection MCP tool Eneo calls to ingest documents. Eneo invokes
# it directly (as an MCP client) so ingest is deterministic and never depends on
# the model choosing the right provider tool.
_INGEST_TOOL_NAME = "ingest_documents"


def _first_text(result: dict[str, Any]) -> str | None:
    """First text content from an MCP tool result, if any."""
    content = result.get("content")
    if not isinstance(content, list):
        return None
    for item in cast("list[Any]", content):
        if isinstance(item, dict):
            entry = cast("dict[str, Any]", item)
            if entry.get("type") == "text":
                text = entry.get("text")
                return text if isinstance(text, str) else None
    return None


def _parse_json_object(text: str | None) -> dict[str, Any]:
    """Parse the tool's JSON result body; {} if absent or not an object."""
    if not text:
        return {}
    try:
        data: Any = json.loads(text)
    except (ValueError, TypeError):
        return {}
    return cast("dict[str, Any]", data) if isinstance(data, dict) else {}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class ExternalKnowledgeService:
    """Create knowledge sources backed by the generic external knowledge provider."""

    def __init__(
        self,
        user: "UserInDB",
        space_service: "SpaceService",
        mcp_server_service: "MCPServerService",
        actor_manager: "ActorManager",
        file_service: "FileService",
        encryption_service: "EncryptionService | None" = None,
    ):
        self.user = user
        self.space_service = space_service
        self.mcp_server_service = mcp_server_service
        self.actor_manager = actor_manager
        self.file_service = file_service
        self.encryption_service = encryption_service

    async def create_knowledge_source(
        self, *, space: "Space", name: str
    ) -> "MCPServer":
        """Provision a knowledge source and enable it in ``space``.

        Authorization is space-admin: this re-checks ``can_edit_space`` as defense
        in depth (the calling capability already gates on it) so the external
        provider is never contacted for an unauthorized actor.
        """
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        if not actor.can_edit_space():
            raise UnauthorizedException(
                "Only a space admin can create knowledge sources.",
                code="forbidden_action",
            )

        client = provider_client_from_settings()
        if client is None:
            raise BadRequestException(
                "No external knowledge provider is configured "
                "(EXTERNAL_KNOWLEDGE_PROVIDER_URL / _API_KEY)."
            )

        collection = await client.create_collection(name=name)
        # create_collection raises unless an endpoint resolved; assert for typing.
        assert collection.mcp_endpoint is not None

        result = await self.mcp_server_service.provision_knowledge_source_server(
            name=name,
            http_url=collection.mcp_endpoint,
            token=collection.mcp_token,
            external_collection_slug=collection.slug or "",
            external_collection_id=collection.external_id,
        )
        if not result.connection.success:
            raise BadRequestException(
                "Could not connect to the knowledge source's MCP endpoint: "
                f"{result.connection.error_message}"
            )

        await self._enable_in_space(space=space, mcp_server_id=result.server.id)
        return result.server

    async def _enable_in_space(self, *, space: "Space", mcp_server_id: UUID) -> None:
        """Add the new server to the space's enabled MCP servers (replace-all set)."""
        enabled_ids = [server.id for server in space.mcp_servers]
        if mcp_server_id not in enabled_ids:
            enabled_ids.append(mcp_server_id)
        await self.space_service.update_space(
            id=cast(UUID, space.id), mcp_server_ids=enabled_ids
        )

    async def ingest_files(
        self, *, space: "Space", knowledge_source_id: UUID, file_ids: list[UUID]
    ) -> dict[str, int]:
        """Ingest already-uploaded files into a knowledge source, deterministically.

        Eneo mints a signed download URL per file and calls the knowledge source's
        own ``ingest_documents`` MCP tool itself (as an MCP client, using the stored
        per-collection token); the provider fetches the bytes from the URLs. No
        model picks the tool, no bytes are pushed by Eneo. Space-admin gated; the
        files must be owned by the actor and have original bytes in object storage.
        """
        actor = self.actor_manager.get_space_actor_from_space(space=space)
        if not actor.can_edit_space():
            raise UnauthorizedException(
                "Only a space admin can manage knowledge sources.",
                code="forbidden_action",
            )

        server = await self.mcp_server_service.get_mcp_server(knowledge_source_id)
        if not space.is_mcp_server_in_space(knowledge_source_id):
            raise BadRequestException(
                "That knowledge source is not enabled in this space."
            )
        if not server.external_collection_slug:
            raise BadRequestException("That server is not a knowledge source.")
        if not file_ids:
            raise BadRequestException("No files were provided to ingest.")

        files = await self.file_service.get_files_by_ids(file_ids)
        found = {file.id for file in files}
        missing = [fid for fid in file_ids if fid not in found]
        if missing:
            raise BadRequestException(
                "Some files were not found or are not yours: "
                + ", ".join(str(fid) for fid in missing)
            )

        settings = get_settings()
        base_url = settings.file_reference_base_url or settings.public_origin
        if not base_url:
            raise BadRequestException(
                "File ingest needs a tool-facing file URL base "
                "(FILE_REFERENCE_BASE_URL or public_origin) and object storage."
            )

        urls: list[str] = []
        for file in files:
            if not getattr(file, "storage_key", None):
                raise BadRequestException(
                    f"File '{file.name}' has no stored original; ingest requires "
                    "object storage to be enabled."
                )
            urls.append(
                build_signed_download_url(
                    file_id=file.id,
                    base_url=base_url,
                    expires_in=settings.file_reference_url_expiry_seconds,
                    tenant_id=self.user.tenant_id,
                    variant="original",
                )
            )

        return await self._call_ingest_tool(
            server=server, urls=urls, expected=len(files)
        )

    async def _call_ingest_tool(
        self, *, server: "MCPServer", urls: list[str], expected: int
    ) -> dict[str, int]:
        """Call the source's ``ingest_documents`` tool; return {ingested, failed}.

        The provider returns per-URL results (``{ingested, failed, results}``); a
        total failure comes back as an MCP error result. We report the provider's
        own counts, falling back to ``expected`` when the result has no counts.
        """
        from intric.mcp_servers.infrastructure.client.mcp_client import (
            MCPClient,
            MCPClientError,
        )

        token = None
        raw_token = (server.http_auth_config_schema or {}).get("token")
        if raw_token:
            if self.encryption_service and self.encryption_service.is_encrypted(
                raw_token
            ):
                token = self.encryption_service.decrypt(raw_token)
            else:
                token = raw_token

        client = MCPClient(
            mcp_server=server,
            auth_credentials={"token": token} if token else None,
        )
        try:
            await client.connect()
            result = await client.call_tool(_INGEST_TOOL_NAME, {"urls": urls})
        except MCPClientError as exc:
            raise BadRequestException(
                f"The knowledge source could not ingest the documents: {exc}"
            )
        finally:
            await client.disconnect()

        text = _first_text(result)
        if result.get("is_error"):
            raise BadRequestException(
                "The knowledge source rejected the ingest request"
                + (f": {text}" if text else ".")
            )

        payload = _parse_json_object(text)
        ingested = _as_int(payload.get("ingested"), expected)
        failed = _as_int(payload.get("failed"), 0)
        return {"ingested": ingested, "failed": failed}
