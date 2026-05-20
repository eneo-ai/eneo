"""Application service for the proxied "Knowledge source" flow.

A knowledge source is, in eneo's domain, a *backend bookkeeping detail*:
the user clicks "Add knowledge source", we provision an eneo-knowledge
``Collection`` on their behalf (single shared upstream, eneo-admin bearer),
register the returned paired MCP server as a space-scoped row in eneo's
``mcp_servers`` table (Phase 1 surface), and persist the (tenant, space,
upstream slug, mcp_server_id) link in ``knowledge_sources``.

Once persisted, assistants pick up the MCP server through the existing
space-scoped catalog visibility — no special-casing. Generic over
discriminators per the standing user preference: deletion of any
space-scoped MCP server detects the knowledge_sources row, if present,
and cascades the upstream collection delete; nothing in the chat/assistant
layer ever needs to know "this MCP is from eneo-knowledge."
"""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa

from intric.eneo_knowledge.client import (
    EneoKnowledgeClient,
    EneoKnowledgeError,
    ProxiedResponse,
)
from intric.eneo_knowledge.table import KnowledgeSources
from intric.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)

if TYPE_CHECKING:
    from intric.actors.actor_manager import ActorManager
    from intric.mcp_servers.application.mcp_server_service import MCPServerService
    from intric.mcp_servers.domain.entities.mcp_server import MCPServer
    from intric.spaces.space_service import SpaceService
    from intric.users.user import UserInDB

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeSourceCreated:
    knowledge_source_id: UUID
    eneo_knowledge_slug: str
    mcp_server: "MCPServer"


@dataclass
class KnowledgeSourceRow:
    """Sparse mapping row, used by the delete-side detection in the MCP path."""

    id: UUID
    tenant_id: UUID
    space_id: UUID
    eneo_knowledge_slug: str
    mcp_server_id: UUID


_SLUG_ALLOWED = re.compile(r"[^a-z0-9-]+")
_SLUG_COLLAPSE = re.compile(r"-+")


def _slugify(name: str) -> str:
    """Squash a display name into eneo-knowledge's slug rules.

    Returns at most 60 chars (leaving room for a uniqueness suffix added by
    the caller). Falls back to ``knowledge`` if the input contains no
    legal characters.
    """
    lowered = name.strip().lower()
    cleaned = _SLUG_ALLOWED.sub("-", lowered)
    collapsed = _SLUG_COLLAPSE.sub("-", cleaned).strip("-")
    return collapsed[:60] if collapsed else "knowledge"


class KnowledgeSourceService:
    def __init__(
        self,
        session: sa.ext.asyncio.AsyncSession,  # type: ignore[name-defined]
        user: "UserInDB",
        space_service: "SpaceService",
        actor_manager: "ActorManager",
        mcp_server_service: "MCPServerService",
        eneo_knowledge_client: EneoKnowledgeClient | None,
    ):
        self._session = session
        self._user = user
        self._space_service = space_service
        self._actor_manager = actor_manager
        self._mcp_server_service = mcp_server_service
        self._client = eneo_knowledge_client

    async def create_knowledge_source(
        self, *, space_id: UUID, name: str
    ) -> KnowledgeSourceCreated:
        """Proxy-create an eneo-knowledge Collection and link it to this space.

        The user only supplies a display name. We generate a slug
        (``slugified-name`` + 6 random hex chars for collision-resistance)
        and call eneo-knowledge with the API key; eneo-knowledge picks the
        embedding model server-side. The returned URL+bearer is then
        registered as a space-scoped MCP server, which runs the standard
        tools/list discovery and persists the bearer encrypted.
        """
        if self._client is None:
            raise BadRequestException(
                "Knowledge sources are not configured for this deployment "
                "(KNOWLEDGE_URL / KNOWLEDGE_API_KEY)"
            )

        space = await self._space_service.get_space(space_id)
        actor = self._actor_manager.get_space_actor_from_space(space=space)
        if not actor.can_create_mcp_servers():
            raise UnauthorizedException()
        assert space.id is not None

        display_name = name.strip()
        if not display_name:
            raise BadRequestException("Knowledge source name cannot be empty")
        slug = f"{_slugify(display_name)}-{secrets.token_hex(3)}"

        try:
            created = await self._client.create_collection(
                slug=slug,
                name=display_name,
            )
        except EneoKnowledgeError:
            raise
        except Exception as exc:
            logger.exception(
                "Failed to call eneo-knowledge create_collection for tenant=%s space=%s",
                self._user.tenant_id,
                space.id,
            )
            raise BadRequestException(
                "Could not reach the knowledge service. Please try again."
            ) from exc

        # Register the paired MCP server as a space-scoped row. We reuse the
        # Phase 1 service path so tool discovery + bearer encryption + audit
        # rules apply uniformly to every MCP server.
        try:
            mcp_result = await self._mcp_server_service.create_space_mcp_server(
                space_id=space.id,
                name=display_name,
                http_url=created.mcp_server.endpoint,
                http_auth_type="bearer",
                description=f"Kunskapskälla i eneo-knowledge ({slug})",
                http_auth_config_schema={"token": created.mcp_server.bearer},
            )
        except Exception:
            # Roll back the upstream collection so we don't leave a dangling
            # collection without an eneo-side handle. Best-effort: a 404 on
            # the upstream is acceptable.
            try:
                await self._client.delete_collection(slug=slug)
            except Exception:
                logger.warning(
                    "Failed to roll back upstream collection %s after eneo-side "
                    "registration failed; manual cleanup may be needed",
                    slug,
                )
            raise

        if not mcp_result.connection.success:
            # MCP registration failed (URL unreachable / tools/list rejected).
            # Roll back the upstream collection.
            try:
                await self._client.delete_collection(slug=slug)
            except Exception:
                logger.warning(
                    "Failed to roll back upstream collection %s after connection "
                    "validation failed",
                    slug,
                )
            raise BadRequestException(
                mcp_result.connection.error_message
                or "Could not connect to the new knowledge MCP server"
            )

        result = await self._session.execute(
            sa.insert(KnowledgeSources)
            .values(
                tenant_id=self._user.tenant_id,
                space_id=space.id,
                owner_user_id=self._user.id,
                eneo_knowledge_slug=slug,
                mcp_server_id=mcp_result.server.id,
            )
            .returning(KnowledgeSources.id)
        )
        knowledge_source_id = result.scalar_one()
        await self._session.commit()

        return KnowledgeSourceCreated(
            knowledge_source_id=knowledge_source_id,
            eneo_knowledge_slug=slug,
            mcp_server=mcp_result.server,
        )

    async def list_for_space(self, space_id: UUID) -> list[KnowledgeSourceRow]:
        """List all knowledge-source ownership rows for a space.

        Used by the frontend to map MCP server entries (from the existing
        space-scoped MCP list) to their knowledge-source ID so the file
        upload + status UI can address the right ownership row.
        """
        space = await self._space_service.get_space(space_id)
        actor = self._actor_manager.get_space_actor_from_space(space=space)
        if not actor.can_read_mcp_servers():
            raise UnauthorizedException()
        rows = (
            await self._session.execute(
                sa.select(
                    KnowledgeSources.id,
                    KnowledgeSources.tenant_id,
                    KnowledgeSources.space_id,
                    KnowledgeSources.eneo_knowledge_slug,
                    KnowledgeSources.mcp_server_id,
                )
                .where(KnowledgeSources.tenant_id == self._user.tenant_id)
                .where(KnowledgeSources.space_id == space_id)
                .order_by(KnowledgeSources.created_at)
            )
        ).all()
        return [
            KnowledgeSourceRow(
                id=row.id,
                tenant_id=row.tenant_id,
                space_id=row.space_id,
                eneo_knowledge_slug=row.eneo_knowledge_slug,
                mcp_server_id=row.mcp_server_id,
            )
            for row in rows
        ]

    async def find_by_mcp_server_id(
        self, mcp_server_id: UUID
    ) -> KnowledgeSourceRow | None:
        """Look up the ownership row for an MCP server, if it is a knowledge source.

        Used by the space-scoped DELETE endpoint to decide whether to also
        delete the upstream eneo-knowledge collection. Returns ``None`` for
        any space-scoped MCP server not registered through this flow.
        """
        row = (
            await self._session.execute(
                sa.select(
                    KnowledgeSources.id,
                    KnowledgeSources.tenant_id,
                    KnowledgeSources.space_id,
                    KnowledgeSources.eneo_knowledge_slug,
                    KnowledgeSources.mcp_server_id,
                ).where(KnowledgeSources.mcp_server_id == mcp_server_id)
            )
        ).first()
        if row is None:
            return None
        return KnowledgeSourceRow(
            id=row.id,
            tenant_id=row.tenant_id,
            space_id=row.space_id,
            eneo_knowledge_slug=row.eneo_knowledge_slug,
            mcp_server_id=row.mcp_server_id,
        )

    async def _resolve_owned_source(
        self, *, space_id: UUID, knowledge_source_id: UUID
    ) -> KnowledgeSourceRow:
        """Look up an ownership row gated by tenant + URL-supplied space_id.

        Used by every file operation. The tenant gate prevents cross-tenant
        proxy abuse even though eneo-knowledge itself is single-tenant; the
        space gate prevents a member of space A from acting on a row that
        actually belongs to space B in the same tenant.
        """
        row = (
            await self._session.execute(
                sa.select(
                    KnowledgeSources.id,
                    KnowledgeSources.tenant_id,
                    KnowledgeSources.space_id,
                    KnowledgeSources.eneo_knowledge_slug,
                    KnowledgeSources.mcp_server_id,
                )
                .where(KnowledgeSources.id == knowledge_source_id)
                .where(KnowledgeSources.tenant_id == self._user.tenant_id)
                .where(KnowledgeSources.space_id == space_id)
            )
        ).first()
        if row is None:
            raise NotFoundException("Knowledge source not found")
        return KnowledgeSourceRow(
            id=row.id,
            tenant_id=row.tenant_id,
            space_id=row.space_id,
            eneo_knowledge_slug=row.eneo_knowledge_slug,
            mcp_server_id=row.mcp_server_id,
        )

    async def proxy_request(
        self,
        *,
        space_id: UUID,
        knowledge_source_id: UUID,
        method: str,
        upstream_path: str,
        body: bytes | None,
        content_type: str | None,
    ) -> tuple[KnowledgeSourceRow, ProxiedResponse]:
        """Forward a request to /api/collections/{slug}/{upstream_path}.

        Pure passthrough after the tenant + space + ownership gate and the
        method → actor capability check. Specific endpoints that need to
        persist eneo-side state (session ids, ownership rows, ...) stay
        explicit and bypass this generic mount.
        """
        space = await self._space_service.get_space(space_id)
        actor = self._actor_manager.get_space_actor_from_space(space=space)

        normalized = method.upper()
        if normalized == "GET":
            if not actor.can_read_mcp_servers():
                raise UnauthorizedException()
        elif normalized == "DELETE":
            if not actor.can_delete_mcp_servers():
                raise UnauthorizedException()
        elif normalized in {"POST", "PATCH", "PUT"}:
            if not actor.can_edit_mcp_servers():
                raise UnauthorizedException()
        else:
            raise BadRequestException(f"Unsupported proxy method '{method}'")

        ownership = await self._resolve_owned_source(
            space_id=space_id, knowledge_source_id=knowledge_source_id
        )
        if self._client is None:
            raise BadRequestException(
                "Knowledge sources are not configured for this deployment"
            )
        response = await self._client.proxy_collection_request(
            slug=ownership.eneo_knowledge_slug,
            method=normalized,
            upstream_path=upstream_path,
            body=body,
            content_type=content_type,
        )
        return ownership, response

    async def delete_upstream_collection(self, *, slug: str) -> None:
        """Best-effort upstream cleanup. 404 is silently swallowed.

        Always called BEFORE the local ``mcp_servers`` row is deleted (the
        FK cascade then removes the ownership row), so eneo state stays
        consistent even if upstream is briefly unavailable.
        """
        if self._client is None:
            return
        try:
            await self._client.delete_collection(slug=slug)
        except EneoKnowledgeError:
            raise
        except Exception:
            logger.exception(
                "Best-effort upstream delete of slug=%s failed; eneo-side row "
                "will still be removed",
                slug,
            )
