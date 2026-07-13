from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from eneo.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
    FlowRetentionClassificationPolicyState,
    FlowRetentionControlPlaneState,
    _FlowRetentionSqlProposal,
)


def _state() -> FlowRetentionControlPlaneState:
    return FlowRetentionControlPlaneState(
        organization_run_history_days=None,
        runtime_upload_abandonment_days=None,
        classification_policies=(
            FlowRetentionClassificationPolicyState(
                security_classification_id=uuid4(),
                data_retention_days=30,
            ),
        ),
        latent_space_retention_days=(7, 30),
        latent_flow_retention_days=(1, 14),
    )


def _compiled(statement: sa.ClauseElement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_run_impact_preview_is_one_set_based_aggregate_with_lifecycle_blockers() -> (
    None
):
    service = DataRetentionService(AsyncMock())
    sql = _compiled(
        service._build_flow_retention_run_impact_query(
            tenant_id=uuid4(),
            state=_state(),
            proposal=_FlowRetentionSqlProposal(
                organization_run_history_days=7,
                runtime_upload_abandonment_days=14,
            ),
            previewed_at=datetime(2026, 7, 13, 12, tzinfo=timezone.utc),
        )
    )

    assert "WITH flow_retention_preview_candidates AS" in sql
    assert "flow_retention_preview_file_refs AS" in sql
    assert "flow_retention_preview_file_bytes AS" in sql
    assert "count(*) FILTER" in sql
    assert "flow_run_audit_outbox" in sql
    assert "flow_run_webhook_deliveries" in sql
    assert "flow_run_rerun_operations" in sql
    assert "coalesce(flow_runs.finished_at, flow_runs.created_at)" in sql
    assert "flow_runs.tenant_id =" in sql
    assert "LIMIT" not in sql


def test_upload_impact_preview_counts_only_never_attached_files_in_one_query() -> None:
    service = DataRetentionService(AsyncMock())
    sql = _compiled(
        service._build_flow_retention_upload_impact_query(
            tenant_id=uuid4(),
            state=_state(),
            proposal=_FlowRetentionSqlProposal(
                organization_run_history_days=None,
                runtime_upload_abandonment_days=14,
            ),
            previewed_at=datetime(2026, 7, 13, 12, tzinfo=timezone.utc),
        )
    )

    assert "FROM flow_runtime_uploaded_files JOIN files" in sql
    assert "NOT (EXISTS (SELECT 1" in sql
    assert "flow_run_step_input_files.file_id" in sql
    assert "sum(files.size) FILTER" in sql
    assert "flow_runtime_uploaded_files.created_at" in sql
    assert "LIMIT" not in sql


def test_control_plane_version_covers_tenant_and_classification_inputs_only() -> None:
    state = _state()
    same_policy_different_latent_values = FlowRetentionControlPlaneState(
        organization_run_history_days=state.organization_run_history_days,
        runtime_upload_abandonment_days=state.runtime_upload_abandonment_days,
        classification_policies=state.classification_policies,
        latent_space_retention_days=(2555,),
        latent_flow_retention_days=(),
    )
    changed_policy = FlowRetentionControlPlaneState(
        organization_run_history_days=7,
        runtime_upload_abandonment_days=state.runtime_upload_abandonment_days,
        classification_policies=state.classification_policies,
        latent_space_retention_days=state.latent_space_retention_days,
        latent_flow_retention_days=state.latent_flow_retention_days,
    )

    assert state.version == same_policy_different_latent_values.version
    assert state.version != changed_policy.version
