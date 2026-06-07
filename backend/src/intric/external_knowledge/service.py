"""Orchestration for provider-backed knowledge sources.

A knowledge source is created by asking the external provider for a collection,
then registering that collection's MCP endpoint as a space-scoped MCP server. The
server's tools are enabled-by-default, so simply attaching it to the space makes
the knowledge usable; granting it to an assistant is a separate step
(``assistant.set_knowledge``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from uuid import UUID

from intric.external_knowledge.client import provider_client_from_settings
from intric.main.exceptions import BadRequestException, UnauthorizedException

if TYPE_CHECKING:
    from intric.actors import ActorManager
    from intric.mcp_servers.application.mcp_server_service import MCPServerService
    from intric.mcp_servers.domain.entities.mcp_server import MCPServer
    from intric.spaces.space import Space
    from intric.spaces.space_service import SpaceService
    from intric.users.user import UserInDB


class ExternalKnowledgeService:
    """Create knowledge sources backed by the generic external knowledge provider."""

    def __init__(
        self,
        user: "UserInDB",
        space_service: "SpaceService",
        mcp_server_service: "MCPServerService",
        actor_manager: "ActorManager",
    ):
        self.user = user
        self.space_service = space_service
        self.mcp_server_service = mcp_server_service
        self.actor_manager = actor_manager

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
