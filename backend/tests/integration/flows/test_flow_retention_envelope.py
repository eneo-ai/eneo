from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
    FlowRetentionOrganizationProposal,
)
from eneo.database.tables.flow_classification_retention_policy_table import (
    FlowClassificationRetentionPolicies,
)
from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
    FlowRuns,
    Flows,
    FlowVersions,
)
from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.infrastructure.flow_repo import FlowRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@dataclass(frozen=True, slots=True)
class _EnvelopeCase:
    label: str
    organization_days: int | None
    classification_days: int | None
    space_days: int | None
    flow_days: int | None
    effective_days: int | None


@pytest.mark.parametrize(
    "case",
    [
        _EnvelopeCase("off with latent children", None, None, 7, 3, None),
        _EnvelopeCase("tenant only", 30, None, None, None, 30),
        _EnvelopeCase("matching classification only", None, 20, None, None, 20),
        _EnvelopeCase("tenant and classification minimum", 30, 20, None, None, 20),
        _EnvelopeCase("children tighten", 30, 20, 10, 5, 5),
        _EnvelopeCase("larger children cannot loosen", 10, 20, 30, 40, 10),
        _EnvelopeCase("unclassified space uses tenant", 30, None, 20, 10, 10),
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
    classification = None
    if case.classification_days is not None:
        classification = SecurityClassification(
            name=f"Retention envelope classification {uuid4()}",
            description="Matching Flow retention classification",
            security_level=2,
            tenant_id=test_tenant.id,
        )
        async_session.add(classification)
        await async_session.flush()
        async_session.add(
            FlowClassificationRetentionPolicies(
                tenant_id=test_tenant.id,
                security_classification_id=classification.id,
                data_retention_days=case.classification_days,
            )
        )
    space = Spaces(
        name=f"Inactive Flow retention envelope {uuid4()}",
        description="Latent child retention values",
        tenant_id=test_tenant.id,
        user_id=None,
        tenant_space_id=tenant_space_id,
        security_classification_id=(
            classification.id if classification is not None else None
        ),
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
    blocked_by_audit = case.label == "children tighten"
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
    assert projected_flow.run_history_retention.contributors.model_dump() == {
        "organization_days": case.organization_days,
        "classification_days": case.classification_days,
        "space_days": case.space_days,
        "flow_days": case.flow_days,
        "organization_minimum_days": None,
        "classification_minimum_days": None,
        "organization_no_purge": False,
        "classification_no_purge": False,
    }
    if blocked_by_audit:
        preview = await retention_service.preview_flow_retention_organization_change(
            tenant_id=test_tenant.id,
            proposal=FlowRetentionOrganizationProposal(
                flow_run_history_retention_days=case.organization_days,
                flow_runtime_upload_abandonment_days=None,
            ),
            previewed_at=anchor,
        )
        assert preview.run_history.current_eligible_count == 1
        assert preview.run_history.proposed_eligible_count == 1
        assert preview.lifecycle_blockers.undelivered_audit_count == 1
        assert preview.lifecycle_blockers.unresolved_webhook_count == 0
        assert preview.lifecycle_blockers.active_rerun_count == 0
