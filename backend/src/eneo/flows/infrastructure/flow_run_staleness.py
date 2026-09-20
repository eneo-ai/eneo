from __future__ import annotations

from datetime import datetime, timedelta

import sqlalchemy as sa

from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRuns,
    FlowRunWebhookDeliveries,
)
from eneo.flows.domain.flow_run_recovery_policy import (
    FLOW_EXECUTION_HEARTBEAT_EXPIRY_SECONDS,
)
from eneo.flows.enums import FlowRunStatus


def execution_heartbeat_expiry_cutoff() -> sa.ColumnElement[datetime]:
    return sa.func.statement_timestamp() - timedelta(
        seconds=FLOW_EXECUTION_HEARTBEAT_EXPIRY_SECONDS
    )


def stale_running_flow_run_predicate() -> sa.ColumnElement[bool]:
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
        FlowRuns.execution_heartbeat_at <= execution_heartbeat_expiry_cutoff(),
        ~pending_or_claimed_webhook_delivery,
    )
