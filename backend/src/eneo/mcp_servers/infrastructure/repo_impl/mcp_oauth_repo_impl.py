"""SQLAlchemy repository for MCP OAuth connections.

Tokens are encrypted here, at the storage boundary, so every caller above
this layer works with plaintext entities and nothing above it can forget to
encrypt.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal, Optional, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from eneo.database.affected_rows import affected_row_count
from eneo.database.tables.mcp_oauth_table import (
    IdpUserTokens,
    MCPOAuthClientRegistrations,
    MCPOAuthConnections,
)
from eneo.mcp_servers.domain.entities.mcp_oauth_connection import (
    ConnectionStatus,
    ConnectionStrategy,
    IdpUserToken,
    MCPOAuthClientRegistration,
    MCPOAuthConnection,
)
from eneo.mcp_servers.domain.repositories.mcp_oauth_repo import MCPOAuthRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from eneo.settings.encryption_service import EncryptionService

# OAuth access tokens and ID tokens are JWTs with rich claims; they routinely
# exceed the API-key sized default limit of the encryption service.
TOKEN_MAX_LENGTH = 64 * 1024


class MCPOAuthRepoImpl(MCPOAuthRepository):
    def __init__(
        self, session: AsyncSession, encryption_service: EncryptionService
    ) -> None:
        super().__init__()
        self.session = session
        self._encryption = encryption_service

    # -- encryption helpers -------------------------------------------------

    def _seal(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return self._encryption.encrypt(value, max_length=TOKEN_MAX_LENGTH)

    def _open(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return self._encryption.decrypt(value)

    # -- connections --------------------------------------------------------

    def _to_connection(self, row: MCPOAuthConnections) -> MCPOAuthConnection:
        return MCPOAuthConnection(
            id=row.id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            tenant_id=row.tenant_id,
            mcp_server_id=row.mcp_server_id,
            user_id=row.user_id,
            issuer=row.issuer,
            resource=row.resource,
            strategy=cast(ConnectionStrategy, row.strategy),
            status=cast(ConnectionStatus, row.status),
            access_token=self._open(row.access_token_ciphertext),
            refresh_token=self._open(row.refresh_token_ciphertext),
            expires_at=row.expires_at,
            scopes=list(row.scopes or []),
            last_error=row.last_error,
            connected_by_user_id=row.connected_by_user_id,
        )

    async def get_connection(
        self, *, mcp_server_id: UUID, user_id: Optional[UUID]
    ) -> Optional[MCPOAuthConnection]:
        stmt = sa.select(MCPOAuthConnections).where(
            MCPOAuthConnections.mcp_server_id == mcp_server_id,
            MCPOAuthConnections.user_id.is_(None)
            if user_id is None
            else MCPOAuthConnections.user_id == user_id,
        )
        row = (await self.session.scalars(stmt)).one_or_none()
        return self._to_connection(row) if row is not None else None

    async def list_connections(
        self, *, mcp_server_ids: Sequence[UUID], user_id: Optional[UUID]
    ) -> list[MCPOAuthConnection]:
        if not mcp_server_ids:
            return []
        stmt = sa.select(MCPOAuthConnections).where(
            MCPOAuthConnections.mcp_server_id.in_(list(mcp_server_ids)),
            MCPOAuthConnections.user_id.is_(None)
            if user_id is None
            else MCPOAuthConnections.user_id == user_id,
        )
        rows = (await self.session.scalars(stmt)).all()
        return [self._to_connection(row) for row in rows]

    async def save_connection(
        self, connection: MCPOAuthConnection
    ) -> MCPOAuthConnection:
        values: dict[str, object] = {
            "tenant_id": connection.tenant_id,
            "mcp_server_id": connection.mcp_server_id,
            "user_id": connection.user_id,
            "issuer": connection.issuer,
            "resource": connection.resource,
            "strategy": connection.strategy,
            "status": connection.status,
            "access_token_ciphertext": self._seal(connection.access_token),
            "refresh_token_ciphertext": self._seal(connection.refresh_token),
            "expires_at": connection.expires_at,
            "scopes": list(connection.scopes) if connection.scopes else None,
            "last_error": connection.last_error,
            "connected_by_user_id": connection.connected_by_user_id,
        }
        update_values = {
            key: value
            for key, value in values.items()
            if key not in ("tenant_id", "mcp_server_id", "user_id")
        }
        update_values["updated_at"] = sa.func.now()
        stmt = insert(MCPOAuthConnections).values(**values)
        if connection.user_id is None:
            stmt = stmt.on_conflict_do_update(
                index_elements=[MCPOAuthConnections.mcp_server_id],
                index_where=MCPOAuthConnections.user_id.is_(None),
                set_=update_values,
            )
        else:
            stmt = stmt.on_conflict_do_update(
                constraint="uq_mcp_oauth_connections_server_user",
                set_=update_values,
            )
        stmt = stmt.returning(MCPOAuthConnections)
        row = (await self.session.scalars(stmt)).one()
        return self._to_connection(row)

    async def delete_connection(
        self, *, mcp_server_id: UUID, user_id: Optional[UUID]
    ) -> bool:
        stmt = sa.delete(MCPOAuthConnections).where(
            MCPOAuthConnections.mcp_server_id == mcp_server_id,
            MCPOAuthConnections.user_id.is_(None)
            if user_id is None
            else MCPOAuthConnections.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return affected_row_count(result) > 0

    async def delete_connections(self, *, mcp_server_id: UUID) -> None:
        await self.session.execute(
            sa.delete(MCPOAuthConnections).where(
                MCPOAuthConnections.mcp_server_id == mcp_server_id
            )
        )

    async def delete_server_state(self, *, mcp_server_id: UUID) -> None:
        await self.delete_connections(mcp_server_id=mcp_server_id)
        await self.session.execute(
            sa.delete(MCPOAuthClientRegistrations).where(
                MCPOAuthClientRegistrations.mcp_server_id == mcp_server_id
            )
        )

    # -- client registrations ----------------------------------------------

    def _to_registration(
        self, row: MCPOAuthClientRegistrations
    ) -> MCPOAuthClientRegistration:
        return MCPOAuthClientRegistration(
            id=row.id,
            tenant_id=row.tenant_id,
            mcp_server_id=row.mcp_server_id,
            issuer=row.issuer,
            client_id=row.client_id,
            client_secret=self._open(row.client_secret_ciphertext),
            source=cast(Literal["pre_registered", "dcr"], row.source),
            registration_payload=row.registration_payload,
        )

    async def get_registration(
        self, *, mcp_server_id: UUID, issuer: str
    ) -> Optional[MCPOAuthClientRegistration]:
        stmt = sa.select(MCPOAuthClientRegistrations).where(
            MCPOAuthClientRegistrations.mcp_server_id == mcp_server_id,
            MCPOAuthClientRegistrations.issuer == issuer,
        )
        row = (await self.session.scalars(stmt)).one_or_none()
        return self._to_registration(row) if row is not None else None

    async def save_registration(
        self, registration: MCPOAuthClientRegistration
    ) -> MCPOAuthClientRegistration:
        values: dict[str, object] = {
            "tenant_id": registration.tenant_id,
            "mcp_server_id": registration.mcp_server_id,
            "issuer": registration.issuer,
            "client_id": registration.client_id,
            "client_secret_ciphertext": self._seal(registration.client_secret),
            "source": registration.source,
            "registration_payload": registration.registration_payload,
        }
        stmt = (
            insert(MCPOAuthClientRegistrations)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_mcp_oauth_client_registrations_server_issuer",
                set_={
                    "client_id": values["client_id"],
                    "client_secret_ciphertext": values["client_secret_ciphertext"],
                    "source": values["source"],
                    "registration_payload": values["registration_payload"],
                    "updated_at": sa.func.now(),
                },
            )
            .returning(MCPOAuthClientRegistrations)
        )
        row = (await self.session.scalars(stmt)).one()
        return self._to_registration(row)

    # -- login ID tokens ----------------------------------------------------

    def _to_idp_token(self, row: IdpUserTokens) -> IdpUserToken:
        return IdpUserToken(
            id=row.id,
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            idp_issuer=row.idp_issuer,
            idp_subject=row.idp_subject,
            id_token=self._open(row.id_token_ciphertext) or "",
            id_token_expires_at=row.id_token_expires_at,
        )

    async def get_idp_token(self, *, user_id: UUID) -> Optional[IdpUserToken]:
        stmt = sa.select(IdpUserTokens).where(IdpUserTokens.user_id == user_id)
        row = (await self.session.scalars(stmt)).one_or_none()
        return self._to_idp_token(row) if row is not None else None

    async def save_idp_token(self, token: IdpUserToken) -> IdpUserToken:
        values: dict[str, object] = {
            "user_id": token.user_id,
            "tenant_id": token.tenant_id,
            "idp_issuer": token.idp_issuer,
            "idp_subject": token.idp_subject,
            "id_token_ciphertext": self._seal(token.id_token),
            "id_token_expires_at": token.id_token_expires_at,
        }
        stmt = (
            insert(IdpUserTokens)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_idp_user_tokens_user",
                set_={
                    "tenant_id": values["tenant_id"],
                    "idp_issuer": values["idp_issuer"],
                    "idp_subject": values["idp_subject"],
                    "id_token_ciphertext": values["id_token_ciphertext"],
                    "id_token_expires_at": values["id_token_expires_at"],
                    "updated_at": sa.func.now(),
                },
            )
            .returning(IdpUserTokens)
        )
        row = (await self.session.scalars(stmt)).one()
        return self._to_idp_token(row)
