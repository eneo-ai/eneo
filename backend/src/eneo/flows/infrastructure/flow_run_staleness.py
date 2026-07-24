from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa

from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRuns,
    FlowRunWebhookDeliveries,
)
from eneo.flows.enums import FlowRunStatus


def stale_running_flow_run_predicate(
    *, stale_before: datetime
) -> sa.ColumnElement[bool]:
    """Select stale running runs that recovery may safely terminalize."""
    pending_or_claimed_webhook_delivery = (
        sa.select(FlowRunWebhookDeliveries.id)
        .where(FlowRunWebhookDeliveries.flow_run_id == FlowRuns.id)
        .where(FlowRunWebhookDeliveries.tenant_id == FlowRuns.tenant_id)
        .where(
            FlowRunWebhookDeliveries.delivery_status
            == FlowOutboxDeliveryStatus.PENDING.value
        )
        .exists()
    )
    return sa.and_(
        FlowRuns.status == FlowRunStatus.RUNNING.value,
        FlowRuns.updated_at <= stale_before,
        ~pending_or_claimed_webhook_delivery,
    )
