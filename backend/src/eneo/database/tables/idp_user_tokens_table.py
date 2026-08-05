from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Index, SmallInteger, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class IdpUserTokens(BasePublic):
    """Persisted IdP tokens, encrypted at rest.

    One row per ``(user_id, idp_issuer)``. Re-login UPSERTs. The MCP token
    broker reads the row to mint audience-restricted tokens: the ID token
    is the subject of ID-JAG requests, the access token the subject of
    same-IdP RFC 8693 exchanges. ``revoked_at`` is the logout sentinel;
    non-null means "force re-authentication" without losing the
    audit-trail row.
    """

    __tablename__ = "idp_user_tokens"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idp_issuer",
            name="uq_idp_user_tokens_user_issuer",
        ),
        Index("ix_idp_user_tokens_tenant_id", "tenant_id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    idp_issuer: Mapped[str] = mapped_column(Text, nullable=False)
    idp_subject: Mapped[Optional[str]] = mapped_column(Text)
    refresh_token_ciphertext: Mapped[Optional[str]] = mapped_column(Text)
    access_token_ciphertext: Mapped[Optional[str]] = mapped_column(Text)
    id_token_ciphertext: Mapped[Optional[str]] = mapped_column(Text)
    access_token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    scopes_granted: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    key_version: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="1"
    )
    last_refresh_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
