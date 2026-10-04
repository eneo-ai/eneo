"""The one rule for staging data never attached to a run.

A runtime upload never bound to a run input and a live transcript never bound to
a run are kept for the tenant's current window (30 days when unset), counted from
their creation; changing the window applies to existing items too.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa

from eneo.database.tables.tenant_table import Tenants
from eneo.flows.flow_retention_policy import (
    DEFAULT_FLOW_RUNTIME_UPLOAD_ABANDONMENT_DAYS,
)


def abandonment_window_days(
    tenant_id: UUID | sa.ColumnElement[UUID],
) -> sa.ColumnElement[int]:
    """The tenant's current window in days, evaluated once per statement."""
    return sa.func.coalesce(
        sa.select(Tenants.flow_runtime_upload_abandonment_days)
        .where(Tenants.id == tenant_id)
        .scalar_subquery(),
        DEFAULT_FLOW_RUNTIME_UPLOAD_ABANDONMENT_DAYS,
    )


def abandonment_cutoff(
    now: datetime, tenant_id: UUID | sa.ColumnElement[UUID]
) -> sa.ColumnElement[datetime]:
    """Items created at or before this instant are past the window."""
    return sa.literal(now) - sa.func.make_interval(
        0, 0, 0, abandonment_window_days(tenant_id)
    )
