"""Persistence for IdP-issued tokens captured at the federation callback.

The federation callback exchanges the OIDC ``code`` for an IdP bundle
(``id_token`` + ``access_token`` + ``refresh_token``). Eneo's own JWT
takes over for the rest of the session, so the IdP tokens used to be
discarded immediately. With this store they are encrypted (existing
Fernet ``EncryptionService``) and persisted per ``(user_id, idp_issuer)``
so the MCP token broker can mint audience-restricted tokens without
sending the user through a second consent screen. The ID token is the
subject of ID-JAG requests; the access token is the subject of same-IdP
RFC 8693 exchanges.

Surface:

- :meth:`upsert`: called from the federation callback after every
  successful login. Encrypts, writes, and audits.
- :meth:`get_decrypted`: returns plaintext tokens for the broker. Skips
  rows where ``revoked_at`` is set.
- :meth:`refresh_idp_token`: exchanges the stored refresh token for a
  fresh access token (used when the cached access token has expired);
  rotates the refresh and ID tokens if the IdP returns new ones. On
  ``invalid_grant`` the row is marked revoked.
- :meth:`revoke`: logout / security incident. Zeroes ciphertext, stamps
  ``revoked_at``, audits.

Tokens never appear in logs or audit metadata; only the issuer, expiry,
and scopes go into observable surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

import aiohttp
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.tables.idp_user_tokens_table import IdpUserTokens
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from eneo.audit.application.audit_service import AuditService
    from eneo.settings.encryption_service import EncryptionService
    from eneo.users.user import UserInDB

logger = get_logger(__name__)
TOKEN_ENDPOINT_TIMEOUT_SECONDS = 10


class OidcTokenStoreError(Exception):
    """Base for token-store failures the caller may want to handle."""


class IdpRefreshFailedError(OidcTokenStoreError):
    """The IdP rejected the stored refresh token; the user must re-authenticate."""


@dataclass(frozen=True)
class StoredIdpTokens:
    """Plaintext IdP tokens returned by :meth:`get_decrypted`.

    The MCP token broker consumes this; nothing else should.
    """

    user_id: UUID
    tenant_id: UUID
    idp_issuer: str
    refresh_token: Optional[str]
    access_token: Optional[str]
    id_token: Optional[str]
    access_token_expires_at: Optional[datetime]
    scopes_granted: Optional[list[str]]


class OidcTokenStore:
    def __init__(
        self,
        *,
        session: "AsyncSession",
        encryption_service: "EncryptionService",
        audit_service: "AuditService",
    ) -> None:
        self._session = session
        self._encryption = encryption_service
        self._audit = audit_service

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    async def upsert(
        self,
        *,
        user: "UserInDB",
        idp_issuer: str,
        idp_subject: Optional[str],
        refresh_token: Optional[str],
        access_token: Optional[str],
        id_token: Optional[str] = None,
        access_token_expires_at: Optional[datetime],
        scopes_granted: Optional[list[str]],
        correlation_id: Optional[str] = None,
    ) -> Optional[UUID]:
        """Encrypt and persist IdP tokens for this user / issuer.

        No-ops (and returns ``None``) when ``refresh_token`` is absent:
        a row without a refresh token cannot drive the broker, so we
        keep the DB clean instead of writing useless rows.

        ``id_token=None`` keeps any previously stored ID token (refresh
        responses often omit it); pass an empty string to clear.
        """
        if not refresh_token:
            logger.debug(
                "OidcTokenStore.upsert skipped: no refresh_token in IdP response",
                extra={
                    "user_id": str(user.id),
                    "idp_issuer": idp_issuer,
                    "correlation_id": correlation_id,
                },
            )
            return None

        refresh_ciphertext = self._encryption.encrypt(refresh_token)
        access_ciphertext = (
            self._encryption.encrypt(access_token) if access_token else None
        )
        id_token_ciphertext = self._encryption.encrypt(id_token) if id_token else None

        now = datetime.now(timezone.utc)
        values: dict[str, object | None] = {
            "user_id": user.id,
            "tenant_id": user.tenant_id,
            "idp_issuer": idp_issuer,
            "idp_subject": idp_subject,
            "refresh_token_ciphertext": refresh_ciphertext,
            "access_token_ciphertext": access_ciphertext,
            "access_token_expires_at": access_token_expires_at,
            "scopes_granted": scopes_granted,
            "key_version": 1,
            "last_refresh_at": now,
            "revoked_at": None,
        }
        if id_token is not None:
            values["id_token_ciphertext"] = id_token_ciphertext

        # UPSERT on the (user_id, idp_issuer) uniqueness constraint so
        # re-logins replace the prior row in place.
        update_set: dict[str, object | None] = {
            "tenant_id": user.tenant_id,
            "idp_subject": idp_subject,
            "refresh_token_ciphertext": refresh_ciphertext,
            "access_token_ciphertext": access_ciphertext,
            "access_token_expires_at": access_token_expires_at,
            "scopes_granted": scopes_granted,
            "key_version": 1,
            "last_refresh_at": now,
            "revoked_at": None,
            "updated_at": sa.func.now(),
        }
        if id_token is not None:
            update_set["id_token_ciphertext"] = id_token_ciphertext
        stmt = (
            insert(IdpUserTokens)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_idp_user_tokens_user_issuer",
                set_=update_set,
            )
            .returning(IdpUserTokens.id)
        )
        row_id: UUID = (await self._session.execute(stmt)).scalar_one()

        await self._audit.log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.OIDC_TOKEN_STORED,
            entity_type=EntityType.IDP_USER_TOKEN,
            entity_id=row_id,
            description=f"Stored IdP tokens from issuer {idp_issuer}",
            metadata=AuditMetadata.standard(
                actor=user,
                target=_AuditTarget(id=row_id, name=idp_issuer),
                extra={
                    "idp_issuer": idp_issuer,
                    "has_access_token": access_token is not None,
                    "has_id_token": id_token is not None,
                    "scopes_granted": scopes_granted or [],
                    "access_token_expires_at": (
                        access_token_expires_at.isoformat()
                        if access_token_expires_at
                        else None
                    ),
                    "correlation_id": correlation_id,
                },
            ),
        )
        return row_id

    async def get_decrypted(
        self, *, user_id: UUID, idp_issuer: str
    ) -> Optional[StoredIdpTokens]:
        """Return decrypted tokens for the broker; ``None`` if revoked/missing."""
        row = (
            await self._session.execute(
                sa.select(IdpUserTokens).where(
                    IdpUserTokens.user_id == user_id,
                    IdpUserTokens.idp_issuer == idp_issuer,
                    IdpUserTokens.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None

        refresh_plaintext: Optional[str] = None
        if row.refresh_token_ciphertext:
            refresh_plaintext = self._encryption.decrypt(row.refresh_token_ciphertext)

        access_plaintext: Optional[str] = None
        if row.access_token_ciphertext:
            access_plaintext = self._encryption.decrypt(row.access_token_ciphertext)

        id_token_plaintext: Optional[str] = None
        if row.id_token_ciphertext:
            id_token_plaintext = self._encryption.decrypt(row.id_token_ciphertext)

        return StoredIdpTokens(
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            idp_issuer=row.idp_issuer,
            refresh_token=refresh_plaintext,
            access_token=access_plaintext,
            id_token=id_token_plaintext,
            access_token_expires_at=row.access_token_expires_at,
            scopes_granted=row.scopes_granted,
        )

    async def revoke(
        self, *, user: "UserInDB", idp_issuer: Optional[str] = None
    ) -> int:
        """Zero ciphertext + stamp ``revoked_at`` for one or all of a user's rows.

        When ``idp_issuer`` is ``None`` revoke every row for this user (logout).
        Returns the number of rows revoked.
        """
        now = datetime.now(timezone.utc)
        where = [
            IdpUserTokens.user_id == user.id,
            IdpUserTokens.revoked_at.is_(None),
        ]
        if idp_issuer is not None:
            where.append(IdpUserTokens.idp_issuer == idp_issuer)

        result = await self._session.execute(
            sa.update(IdpUserTokens)
            .where(*where)
            .values(
                refresh_token_ciphertext=None,
                access_token_ciphertext=None,
                id_token_ciphertext=None,
                access_token_expires_at=None,
                revoked_at=now,
                updated_at=now,
            )
            .returning(IdpUserTokens.id, IdpUserTokens.idp_issuer)
        )
        revoked_rows = result.all()

        for row_id, row_issuer in revoked_rows:
            await self._audit.log_async(
                tenant_id=user.tenant_id,
                user=user,
                action=ActionType.OIDC_TOKEN_REVOKED,
                entity_type=EntityType.IDP_USER_TOKEN,
                entity_id=row_id,
                description=f"Revoked IdP tokens for issuer {row_issuer}",
                metadata=AuditMetadata.standard(
                    actor=user,
                    target=_AuditTarget(id=row_id, name=row_issuer),
                    extra={"idp_issuer": row_issuer},
                ),
            )
        return len(revoked_rows)

    async def refresh_idp_token(
        self,
        *,
        user: "UserInDB",
        idp_issuer: str,
        token_endpoint: str,
        client_id: str,
        client_secret: Optional[str] = None,
    ) -> StoredIdpTokens:
        """Exchange the stored refresh_token for a fresh access_token.

        Used by the broker when the cached access_token has expired. On
        ``invalid_grant`` the row is marked revoked and the caller
        receives :class:`IdpRefreshFailedError`; the user must
        re-authenticate.
        """
        existing = await self.get_decrypted(user_id=user.id, idp_issuer=idp_issuer)
        if existing is None or not existing.refresh_token:
            raise IdpRefreshFailedError(
                f"No active refresh token stored for user {user.id} / {idp_issuer}"
            )

        form: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": existing.refresh_token,
            "client_id": client_id,
        }
        if client_secret:
            form["client_secret"] = client_secret

        payload: dict[str, Any]
        timeout = aiohttp.ClientTimeout(total=TOKEN_ENDPOINT_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.post(
                token_endpoint,
                data=form,
                allow_redirects=False,
            ) as resp:
                payload = await resp.json(content_type=None) or {}
                if resp.status >= 400:
                    error_code = str(payload.get("error", "unknown_error"))
                    if error_code == "invalid_grant":
                        await self.revoke(user=user, idp_issuer=idp_issuer)
                        raise IdpRefreshFailedError(
                            "IdP rejected refresh token with invalid_grant; "
                            "row revoked, user must re-authenticate"
                        )
                    raise OidcTokenStoreError(
                        f"IdP refresh failed: HTTP {resp.status} {error_code}"
                    )

        new_access_token = payload.get("access_token")
        new_refresh_token = payload.get("refresh_token") or existing.refresh_token
        # Refresh responses may rotate the ID token; None keeps the stored one.
        new_id_token = payload.get("id_token")
        expires_in = payload.get("expires_in")
        access_expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
            if isinstance(expires_in, (int, float, str)) and str(expires_in).isdigit()
            else None
        )
        scope_value = payload.get("scope")
        scopes_granted: Optional[list[str]] = (
            list(scope_value.split())
            if isinstance(scope_value, str) and scope_value
            else existing.scopes_granted
        )

        await self.upsert(
            user=user,
            idp_issuer=idp_issuer,
            idp_subject=None,
            refresh_token=new_refresh_token,
            access_token=new_access_token,
            id_token=new_id_token,
            access_token_expires_at=access_expires_at,
            scopes_granted=scopes_granted,
        )

        await self._audit.log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.OIDC_TOKEN_REFRESHED,
            entity_type=EntityType.IDP_USER_TOKEN,
            entity_id=user.id,
            description=f"Refreshed IdP access token for issuer {idp_issuer}",
            metadata=AuditMetadata.standard(
                actor=user,
                target=_AuditTarget(id=user.id, name=idp_issuer),
                extra={
                    "idp_issuer": idp_issuer,
                    "rotated_refresh_token": bool(payload.get("refresh_token")),
                    "access_token_expires_at": (
                        access_expires_at.isoformat() if access_expires_at else None
                    ),
                },
            ),
        )

        return StoredIdpTokens(
            user_id=user.id,
            tenant_id=user.tenant_id,
            idp_issuer=idp_issuer,
            refresh_token=new_refresh_token,
            access_token=new_access_token,
            id_token=new_id_token if new_id_token is not None else existing.id_token,
            access_token_expires_at=access_expires_at,
            scopes_granted=scopes_granted,
        )


@dataclass(frozen=True)
class _AuditTarget:
    """Adapter so ``AuditMetadata.standard`` can stringify the row id + issuer."""

    id: UUID
    name: str
