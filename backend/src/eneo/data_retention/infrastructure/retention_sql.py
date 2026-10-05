"""SQL building blocks the retention repositories share."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from eneo.data_retention.constants import DEFAULT_AUDIT_RETENTION_DAYS
from eneo.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from eneo.database.tables.tenant_table import Tenants


def uuid_in(column: Any, values: Collection[UUID]) -> sa.ColumnElement[bool]:
    """`column = ANY(:ids)` with one array bind, whatever the number of ids."""
    return column == sa.any_(
        sa.literal(list(values), type_=postgresql.ARRAY(postgresql.UUID(as_uuid=True)))
    )


def deployment_tenant_id() -> sa.ScalarSelect[UUID]:
    """The deployment's tenant (docs/adr/single-tenant-assumption.md); a legacy
    deployment with several uses its first."""
    return (
        sa.select(Tenants.id)
        .order_by(Tenants.created_at, Tenants.id)
        .limit(1)
        .scalar_subquery()
    )


def deployment_audit_retention_days() -> sa.ColumnElement[int]:
    """The deployment's audit retention in days (365 when unset); evaluated once."""
    return sa.func.coalesce(
        sa.select(AuditRetentionPolicy.retention_days)
        .where(AuditRetentionPolicy.tenant_id == deployment_tenant_id())
        .scalar_subquery(),
        DEFAULT_AUDIT_RETENTION_DAYS,
    )
