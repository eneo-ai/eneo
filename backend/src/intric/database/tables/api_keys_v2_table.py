from datetime import datetime
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.base_class import BasePublic
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users


class ApiKeysV2(BasePublic):
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(nullable=False)
    scope_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    permission: Mapped[str] = mapped_column(nullable=False)
    key_type: Mapped[str] = mapped_column(nullable=False)
    key_hash: Mapped[str] = mapped_column(nullable=False)
    hash_version: Mapped[str] = mapped_column(nullable=False)
    key_prefix: Mapped[str] = mapped_column(nullable=False)
    key_suffix: Mapped[str] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    rate_limit: Mapped[Optional[int]] = mapped_column(nullable=True)
    allowed_origins: Mapped[Optional[list[str]]] = mapped_column(JSONB, nullable=True)
    allowed_ips: Mapped[Optional[list[str]]] = mapped_column(JSONB, nullable=True)
    state: Mapped[str] = mapped_column(nullable=False, server_default="active")
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    revoked_reason_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    revoked_reason_text: Mapped[Optional[str]] = mapped_column(sa.String(length=500))
    suspended_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    suspended_reason_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    suspended_reason_text: Mapped[Optional[str]] = mapped_column(sa.String(length=500))
    rotation_grace_until: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    rotated_from_key_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("api_keys_v2.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"), nullable=True
    )
    created_by_key_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("api_keys_v2.id", ondelete="SET NULL"), nullable=True
    )
    delegation_depth: Mapped[int] = mapped_column(nullable=False, server_default="0")

    __table_args__ = (
        sa.Index("idx_api_keys_v2_tenant_scope", "tenant_id", "scope_type", "scope_id"),
        sa.Index("idx_api_keys_v2_key_hash", "key_hash"),
        sa.Index("idx_api_keys_v2_expires_at", "expires_at"),
        sa.Index("idx_api_keys_v2_created_by_key_id", "created_by_key_id"),
        sa.Index("idx_api_keys_v2_tenant_state", "tenant_id", "state"),
        sa.UniqueConstraint(
            "key_hash",
            "hash_version",
            name="uq_api_keys_v2_key_hash_version",
        ),
    )
