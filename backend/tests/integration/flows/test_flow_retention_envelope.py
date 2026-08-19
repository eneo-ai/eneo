from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
)
from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
    FlowRuns,
    Flows,
    FlowVersions,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.infrastructure.flow_repo import FlowRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@dataclass(frozen=True, slots=True)
class _EnvelopeCase:
    label: str
    organization_days: int | None
    space_days: int | None
    flow_days: int | None
    effective_days: int | None
    source: str


@pytest.mark.parametrize(
    "case",
    [
        _EnvelopeCase("off", None, None, None, None, "none"),
        _EnvelopeCase("tenant fallback", 30, None, None, 30, "organization"),
        _EnvelopeCase("space overrides tenant", 30, 20, None, 20, "space"),
        _EnvelopeCase("flow overrides space", 30, 20, 10, 10, "flow"),
        _EnvelopeCase("flow can lengthen parent", 10, 20, 40, 40, "flow"),
    ],
    ids=lambda case: case.label,
)
async def test_flow_retention_envelope_matrix_controls_purge_and_effective_reads(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    case: _EnvelopeCase,
) -> None:
    anchor = datetime.now(timezone.utc)
    old = anchor - timedelta(days=45)
    await async_session.execute(
        sa.update(Tenants)
        .where(Tenants.id == test_tenant.id)
        .values(flow_run_history_retention_days=case.organization_days)
    )
    tenant_space_id = await async_session.scalar(
        sa.select(Spaces.id).where(
            Spaces.tenant_id == test_tenant.id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )
    assert tenant_space_id is not None
    space = Spaces(
        name=f"Inactive Flow retention envelope {uuid4()}",
        description="Latent child retention values",
        tenant_id=test_tenant.id,
        user_id=None,
        tenant_space_id=tenant_space_id,
        security_classification_id=None,
        data_retention_days=case.space_days,
    )
    async_session.add(space)
    await async_session.flush()
    flow = Flows(
        name=f"Inactive Flow retention envelope {uuid4()}",
        description="Latent Flow retention value",
        tenant_id=test_tenant.id,
        space_id=space.id,
        created_by_user_id=admin_user.id,
        owner_user_id=admin_user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=case.flow_days,
        created_at=old,
        updated_at=old,
    )
    async_session.add(flow)
    await async_session.flush()
    async_session.add(
        FlowVersions(
            flow_id=flow.id,
            version=1,
            tenant_id=test_tenant.id,
            definition_checksum=f"retention-envelope-{uuid4()}",
            definition_json={"schema_version": 1, "steps": []},
            created_at=old,
            updated_at=old,
        )
    )
    await async_session.flush()
    run = FlowRuns(
        flow_id=flow.id,
        flow_version=1,
        principal_type="user",
        principal_user_id=admin_user.id,
        principal_service_id=None,
        runtime_service_permission=None,
        tenant_id=test_tenant.id,
        trace_id=uuid4(),
        status="completed",
        started_at=old,
        finished_at=old,
        input_payload_json={},
        output_payload_json={},
        created_at=old,
        updated_at=old,
    )
    async_session.add(run)
    await async_session.flush()
    blocked_by_audit = case.label == "flow overrides space"
    if blocked_by_audit:
        async_session.add(
            FlowRunAuditOutbox(
                tenant_id=test_tenant.id,
                flow_id=flow.id,
                flow_run_id=run.id,
                run_revision=run.revision,
                review_checkpoint_id=None,
                checkpoint_revision=None,
                description="flow_run_completed:executor_completed",
                action="flow_run_completed",
                entity_type="flow_run",
                entity_id=run.id,
                actor_id=admin_user.id,
                actor_type="user",
                actor_api_key_id=None,
                source="executor_completed",
                target_status="completed",
                error_code=None,
                error_message=None,
                delivery_status=FlowOutboxDeliveryStatus.PENDING.value,
                delivery_attempts=0,
                next_delivery_at=anchor,
                delivered_at=None,
                dead_lettered_at=None,
                delivery_last_error=None,
                created_at=old,
                updated_at=old,
            )
        )
        await async_session.flush()

    retention_service = DataRetentionService(async_session)
    due_run_ids = list(
        (
            await async_session.scalars(
                retention_service._build_due_flow_run_history_purge_query(now=anchor)
            )
        ).all()
    )
    candidates = await retention_service._select_flow_run_history_purge_batch(
        now=anchor,
        limit=100,
    )
    projected_flow = await FlowRepository(
        session=async_session,
    ).get(flow.id, test_tenant.id)

    assert (run.id in due_run_ids) is (case.effective_days is not None)
    assert (run.id in candidates) is (
        case.effective_days is not None and not blocked_by_audit
    )
    assert projected_flow.run_history_retention is not None
    assert projected_flow.run_history_retention.effective_days == case.effective_days
    assert projected_flow.run_history_retention.state == (
        "off" if case.effective_days is None else "days"
    )
    assert projected_flow.run_history_retention.source == case.source
    assert projected_flow.run_history_retention.contributors.model_dump() == {
        "organization_days": case.organization_days,
        "space_days": case.space_days,
        "flow_days": case.flow_days,
    }
