from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event

from eneo.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
    FlowRetentionOrganizationProposal,
)
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_classification_retention_policy_table import (
    FlowClassificationRetentionPolicies,
)
from eneo.database.tables.flow_tables import (
    FlowRuns,
    FlowRuntimeUploadedFiles,
    Flows,
    FlowVersions,
)
from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.main.models import ModelId
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt):
    async with db_container() as container:
        user = await container.user_repo().get_user_by_email("test@example.com")
        return container.auth_service().create_access_token_for_user(user)


@pytest.fixture
async def non_admin_token(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"flow-retention-member-{uuid4().hex[:8]}",
                permissions=[],
                tenant_id=admin_user.tenant_id,
            )
        )
        user = await container.user_repo().add(
            UserAdd(
                email=f"flow-retention-member-{uuid4().hex[:8]}@example.com",
                username=f"flow_retention_member_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )
        return container.auth_service().create_access_token_for_user(user)


@pytest.fixture
async def retention_existing_data(db_container, admin_user) -> tuple[UUID, UUID]:
    old = datetime.now(timezone.utc) - timedelta(days=45)
    async with db_container() as container:
        session = container.session()
        tenant_space_id = await session.scalar(
            sa.select(Spaces.id).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        assert tenant_space_id is not None
        classification = SecurityClassification(
            name=f"Retention classification {uuid4()}",
            description="Preview classification",
            security_level=2,
            tenant_id=admin_user.tenant_id,
        )
        space = Spaces(
            name=f"Retention preview space {uuid4()}",
            description="Preview existing data",
            data_retention_days=7,
            tenant_id=admin_user.tenant_id,
            user_id=None,
            tenant_space_id=tenant_space_id,
            security_classification=classification,
        )
        session.add_all([classification, space])
        await session.flush()

        flow = Flows(
            name=f"Retention preview flow {uuid4()}",
            description="Preview existing run history",
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            created_by_user_id=admin_user.id,
            owner_user_id=admin_user.id,
            published_version=None,
            metadata_json=None,
            data_retention_days=3,
            created_at=old,
            updated_at=old,
        )
        session.add(flow)
        await session.flush()
        session.add(
            FlowVersions(
                flow_id=flow.id,
                version=1,
                tenant_id=admin_user.tenant_id,
                definition_checksum=f"preview-{uuid4()}",
                definition_json={"schema_version": 1, "steps": []},
                created_at=old,
                updated_at=old,
            )
        )
        await session.flush()
        session.add(
            FlowRuns(
                flow_id=flow.id,
                flow_version=1,
                principal_type="user",
                principal_user_id=admin_user.id,
                principal_service_id=None,
                runtime_service_permission=None,
                tenant_id=admin_user.tenant_id,
                trace_id=uuid4(),
                status="completed",
                started_at=old,
                finished_at=old,
                input_payload_json={},
                output_payload_json={},
                created_at=old,
                updated_at=old,
            )
        )
        await _add_unattached_upload(
            session=session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            flow_id=flow.id,
            created_at=old,
        )
        await session.flush()
        return flow.id, classification.id


async def _add_unattached_upload(
    *,
    session,
    tenant_id: UUID,
    user_id: UUID,
    flow_id: UUID,
    created_at: datetime,
) -> None:
    file = Files(
        name=f"unattached-{uuid4()}.txt",
        text="preview source",
        blob=None,
        checksum=f"preview-{uuid4()}",
        size=128,
        mimetype="text/plain",
        file_type="text",
        transcription=None,
        owner_type="user",
        owner_user_id=user_id,
        owner_service_id=None,
        tenant_id=tenant_id,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(file)
    await session.flush()
    session.add(
        FlowRuntimeUploadedFiles(
            file_id=file.id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            uploaded_for_step_id=uuid4(),
            owner_type="user",
            owner_user_id=user_id,
            owner_service_id=None,
            created_at=created_at,
            updated_at=created_at,
        )
    )


def _confirmation(preview: dict[str, object]) -> dict[str, object]:
    return {
        "expected_control_plane_version": preview["control_plane_version"],
        "expected_preview_hash": preview["preview_hash"],
        "previewed_at": preview["previewed_at"],
    }


async def test_preview_has_constant_read_only_statement_cardinality(
    db_container,
    admin_user,
    retention_existing_data,
) -> None:
    flow_id, _classification_id = retention_existing_data
    statements: list[tuple[str, tuple[object, ...]]] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        parameters: object,
        *_args: object,
    ) -> None:
        assert isinstance(parameters, tuple)
        statements.append((statement, parameters))

    async with db_container() as container:
        old = datetime.now(timezone.utc) - timedelta(days=45)
        representative_runs = [
            FlowRuns(
                flow_id=flow_id,
                flow_version=1,
                principal_type="user",
                principal_user_id=admin_user.id,
                principal_service_id=None,
                runtime_service_permission=None,
                tenant_id=admin_user.tenant_id,
                trace_id=uuid4(),
                status="completed",
                started_at=old,
                finished_at=old,
                input_payload_json={},
                output_payload_json={},
                created_at=old,
                updated_at=old,
            )
            for _index in range(255)
        ]
        representative_files = [
            Files(
                name=f"representative-unattached-{uuid4()}.txt",
                text="preview source",
                blob=None,
                checksum=f"representative-preview-{uuid4()}",
                size=128,
                mimetype="text/plain",
                file_type="text",
                transcription=None,
                owner_type="user",
                owner_user_id=admin_user.id,
                owner_service_id=None,
                tenant_id=admin_user.tenant_id,
                created_at=old,
                updated_at=old,
            )
            for _index in range(63)
        ]
        container.session().add_all(representative_runs + representative_files)
        await container.session().flush()
        container.session().add_all(
            [
                FlowRuntimeUploadedFiles(
                    file_id=file.id,
                    flow_id=flow_id,
                    tenant_id=admin_user.tenant_id,
                    uploaded_for_step_id=uuid4(),
                    owner_type="user",
                    owner_user_id=admin_user.id,
                    owner_service_id=None,
                    created_at=old,
                    updated_at=old,
                )
                for file in representative_files
            ]
        )
        await container.session().flush()

        previewed_at = datetime.now(timezone.utc)
        legacy_effective_days = sa.func.least(
            sa.func.coalesce(
                Flows.data_retention_days,
                Spaces.data_retention_days,
            ),
            FlowClassificationRetentionPolicies.data_retention_days,
        )
        legacy_child_only_candidates = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(FlowRuns)
            .join(Flows, FlowRuns.flow_id == Flows.id)
            .join(Spaces, Flows.space_id == Spaces.id)
            .outerjoin(
                FlowClassificationRetentionPolicies,
                sa.and_(
                    FlowClassificationRetentionPolicies.security_classification_id
                    == Spaces.security_classification_id,
                    FlowClassificationRetentionPolicies.tenant_id == Spaces.tenant_id,
                ),
            )
            .where(
                FlowRuns.flow_id == flow_id,
                FlowRuns.status == "completed",
                legacy_effective_days.is_not(None),
                sa.func.coalesce(FlowRuns.finished_at, FlowRuns.created_at)
                <= sa.literal(previewed_at)
                - sa.func.make_interval(0, 0, 0, legacy_effective_days),
            )
        )
        retention_service = DataRetentionService(container.session())
        canonical_off_candidates = list(
            (
                await container.session().scalars(
                    retention_service._build_due_flow_run_history_purge_query(
                        now=previewed_at
                    ).where(FlowRuns.flow_id == flow_id)
                )
            ).all()
        )

        bind = container.session().sync_session.bind
        assert bind is not None
        event.listen(bind, "before_cursor_execute", record_statement)
        try:
            enabled_preview = (
                await retention_service.preview_flow_retention_organization_change(
                    tenant_id=admin_user.tenant_id,
                    proposal=FlowRetentionOrganizationProposal(
                        flow_run_history_retention_days=30,
                        flow_runtime_upload_abandonment_days=30,
                    ),
                    previewed_at=previewed_at,
                )
            )
        finally:
            event.remove(bind, "before_cursor_execute", record_statement)

        enable_statements = list(statements)
        await container.session().execute(
            sa.update(Tenants)
            .where(Tenants.id == admin_user.tenant_id)
            .values(
                flow_run_history_retention_days=30,
                flow_runtime_upload_abandonment_days=30,
            )
        )
        statements.clear()
        event.listen(bind, "before_cursor_execute", record_statement)
        try:
            disabled_preview = (
                await retention_service.preview_flow_retention_organization_change(
                    tenant_id=admin_user.tenant_id,
                    proposal=FlowRetentionOrganizationProposal(
                        flow_run_history_retention_days=None,
                        flow_runtime_upload_abandonment_days=None,
                    ),
                    previewed_at=previewed_at,
                )
            )
        finally:
            event.remove(bind, "before_cursor_execute", record_statement)

        disable_statements = list(statements)
        impact_statements = enable_statements[-2:] + disable_statements[-2:]
        await container.session().execute(sa.text("SET LOCAL enable_seqscan = off"))
        connection = await container.session().connection()
        plans: list[str] = []
        for statement, parameters in impact_statements:
            result = await connection.exec_driver_sql(
                f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {statement}",
                parameters,
            )
            plans.append("\n".join(row[0] for row in result))

    assert legacy_child_only_candidates == 256
    assert canonical_off_candidates == []
    assert enabled_preview.run_history.newly_eligible_count == 256
    assert enabled_preview.run_history.no_longer_eligible_count == 0
    assert enabled_preview.runtime_uploads.newly_eligible_count == 64
    assert enabled_preview.runtime_uploads.newly_eligible_bytes == 64 * 128
    assert enabled_preview.lifecycle_blockers.undelivered_audit_count == 0
    assert enabled_preview.lifecycle_blockers.unresolved_webhook_count == 0
    assert enabled_preview.lifecycle_blockers.active_rerun_count == 0
    assert enabled_preview.latent_space_retention_days == (7,)
    assert enabled_preview.latent_flow_retention_days == (3,)
    assert disabled_preview.run_history.newly_eligible_count == 0
    assert disabled_preview.run_history.no_longer_eligible_count == 256
    assert disabled_preview.runtime_uploads.newly_eligible_count == 0
    assert disabled_preview.runtime_uploads.no_longer_eligible_count == 64
    assert disabled_preview.runtime_uploads.proposed_eligible_bytes == 0
    assert disabled_preview.latent_space_retention_days == (7,)
    assert disabled_preview.latent_flow_retention_days == (3,)
    assert len(enable_statements) == 6
    assert len(disable_statements) == 6
    assert all(
        statement.lstrip().startswith(("SELECT", "WITH"))
        for statement, _parameters in enable_statements + disable_statements
    )
    assert "ix_flow_runs_tenant_created_at" in plans[0]
    assert "ix_flow_runtime_uploaded_files_tenant_id" in plans[1]
    assert "ix_flow_runs_tenant_created_at" in plans[2]
    assert "ix_flow_runtime_uploaded_files_tenant_id" in plans[3]
    assert all("Buffers:" in plan for plan in plans)


async def test_concurrent_same_organization_preview_allows_one_mutation_and_audit(
    client,
    admin_token,
    retention_existing_data,
    db_container,
    admin_user,
) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    proposal = {
        "flow_run_history_retention_days": 30,
        "flow_runtime_upload_abandonment_days": 30,
    }
    preview_response = await client.post(
        "/api/v1/settings/flow-retention-policy/preview",
        headers=headers,
        json=proposal,
    )
    assert preview_response.status_code == 200, preview_response.text
    confirmed_proposal = {
        **proposal,
        "confirmation": _confirmation(preview_response.json()),
    }

    responses = await asyncio.gather(
        client.patch(
            "/api/v1/settings/flow-retention-policy",
            headers=headers,
            json=confirmed_proposal,
        ),
        client.patch(
            "/api/v1/settings/flow-retention-policy",
            headers=headers,
            json=confirmed_proposal,
        ),
    )

    assert sorted(response.status_code for response in responses) == [200, 409]
    stale_response = next(
        response for response in responses if response.status_code == 409
    )
    assert stale_response.json()["code"] == "flow_retention_preview_stale"

    current = await client.get(
        "/api/v1/settings/flow-retention-policy",
        headers=headers,
    )
    assert current.status_code == 200, current.text
    assert current.json()["flow_run_history_retention_days"] == 30
    assert current.json()["flow_runtime_upload_abandonment_days"] == 30

    async with db_container() as container:
        audit_count = await container.session().scalar(
            sa.select(sa.func.count(AuditLog.id)).where(
                AuditLog.tenant_id == admin_user.tenant_id,
                AuditLog.description == "Updated flow retention policy",
            )
        )
    assert audit_count == 1


async def test_concurrent_same_classification_preview_allows_one_mutation_and_audit(
    client,
    admin_token,
    retention_existing_data,
    db_container,
    admin_user,
) -> None:
    _flow_id, classification_id = retention_existing_data
    headers = {"Authorization": f"Bearer {admin_token}"}
    path = (
        f"/api/v1/settings/flow-classification-retention-policies/{classification_id}"
    )
    preview_response = await client.post(
        f"{path}/preview",
        headers=headers,
        json={"data_retention_days": 10},
    )
    assert preview_response.status_code == 200, preview_response.text
    confirmed_proposal = {
        "data_retention_days": 10,
        "confirmation": _confirmation(preview_response.json()),
    }

    responses = await asyncio.gather(
        client.put(path, headers=headers, json=confirmed_proposal),
        client.put(path, headers=headers, json=confirmed_proposal),
    )

    assert sorted(response.status_code for response in responses) == [200, 409]
    stale_response = next(
        response for response in responses if response.status_code == 409
    )
    assert stale_response.json()["code"] == "flow_retention_preview_stale"

    async with db_container() as container:
        policy_days = (
            await container.session().scalars(
                sa.select(
                    FlowClassificationRetentionPolicies.data_retention_days
                ).where(
                    FlowClassificationRetentionPolicies.tenant_id
                    == admin_user.tenant_id,
                    FlowClassificationRetentionPolicies.security_classification_id
                    == classification_id,
                )
            )
        ).all()
        audit_count = await container.session().scalar(
            sa.select(sa.func.count(AuditLog.id)).where(
                AuditLog.tenant_id == admin_user.tenant_id,
                AuditLog.description == "Updated Flow classification retention policy",
            )
        )
    assert policy_days == [10]
    assert audit_count == 1


async def test_admin_organization_and_classification_policy_journeys_use_exact_preview(
    client,
    admin_token,
    retention_existing_data,
    db_container,
    admin_user,
) -> None:
    flow_id, classification_id = retention_existing_data
    headers = {"Authorization": f"Bearer {admin_token}"}

    current = await client.get(
        "/api/v1/settings/flow-retention-policy",
        headers=headers,
    )
    assert current.status_code == 200, current.text
    assert current.json()["flow_run_history_retention_days"] is None
    assert current.json()["flow_runtime_upload_abandonment_days"] is None
    assert current.json()["effective_state"]["run_history_deletion_active"] is False

    proposal = {
        "flow_run_history_retention_days": 30,
        "flow_runtime_upload_abandonment_days": 30,
    }
    preview_response = await client.post(
        "/api/v1/settings/flow-retention-policy/preview",
        headers=headers,
        json=proposal,
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["destructive_change"] is True
    assert preview["run_history"]["newly_eligible_count"] == 1
    assert preview["runtime_uploads"]["newly_eligible_count"] == 1
    assert preview["runtime_uploads"]["newly_eligible_bytes"] == 128
    assert preview["run_history_anchor"] == "finished_at_or_created_at"
    assert preview["runtime_upload_anchor"] == "created_at"
    assert preview["latent_space_retention_days"] == [7]
    assert preview["latent_flow_retention_days"] == [3]

    missing_confirmation = await client.patch(
        "/api/v1/settings/flow-retention-policy",
        headers=headers,
        json=proposal,
    )
    assert missing_confirmation.status_code == 409
    assert missing_confirmation.json()["code"] == "flow_retention_confirmation_required"

    async with db_container() as container:
        flow = await container.session().get(Flows, flow_id)
        assert flow is not None
        await _add_unattached_upload(
            session=container.session(),
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            flow_id=flow.id,
            created_at=datetime.now(timezone.utc) - timedelta(days=45),
        )
        await container.session().flush()

    stale_exact_preview = await client.patch(
        "/api/v1/settings/flow-retention-policy",
        headers=headers,
        json={**proposal, "confirmation": _confirmation(preview)},
    )
    assert stale_exact_preview.status_code == 409
    assert stale_exact_preview.json()["code"] == "flow_retention_preview_stale"

    preview = (
        await client.post(
            "/api/v1/settings/flow-retention-policy/preview",
            headers=headers,
            json=proposal,
        )
    ).json()
    enabled = await client.patch(
        "/api/v1/settings/flow-retention-policy",
        headers=headers,
        json={**proposal, "confirmation": _confirmation(preview)},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["flow_run_history_retention_days"] == 30
    assert enabled.json()["flow_runtime_upload_abandonment_days"] == 30

    lengthened = await client.patch(
        "/api/v1/settings/flow-retention-policy",
        headers=headers,
        json={
            "flow_run_history_retention_days": 60,
            "flow_runtime_upload_abandonment_days": 60,
        },
    )
    assert lengthened.status_code == 200, lengthened.text

    stale_state = await client.patch(
        "/api/v1/settings/flow-retention-policy",
        headers=headers,
        json={**proposal, "confirmation": _confirmation(preview)},
    )
    assert stale_state.status_code == 409
    assert stale_state.json()["code"] == "flow_retention_preview_stale"

    disabled = await client.patch(
        "/api/v1/settings/flow-retention-policy",
        headers=headers,
        json={
            "flow_run_history_retention_days": None,
            "flow_runtime_upload_abandonment_days": None,
        },
    )
    assert disabled.status_code == 200, disabled.text

    classification_preview = await client.post(
        f"/api/v1/settings/flow-classification-retention-policies/{classification_id}/preview",
        headers=headers,
        json={"data_retention_days": 10},
    )
    assert classification_preview.status_code == 200, classification_preview.text
    classification_impact = classification_preview.json()
    assert classification_impact["run_history"]["newly_eligible_count"] == 1

    classification_without_confirmation = await client.put(
        f"/api/v1/settings/flow-classification-retention-policies/{classification_id}",
        headers=headers,
        json={"data_retention_days": 10},
    )
    assert classification_without_confirmation.status_code == 409

    classification_enabled = await client.put(
        f"/api/v1/settings/flow-classification-retention-policies/{classification_id}",
        headers=headers,
        json={
            "data_retention_days": 10,
            "confirmation": _confirmation(classification_impact),
        },
    )
    assert classification_enabled.status_code == 200, classification_enabled.text

    async with db_container() as container:
        audit_metadata_rows = (
            await container.session().scalars(
                sa.select(AuditLog.log_metadata)
                .where(
                    AuditLog.tenant_id == admin_user.tenant_id,
                    AuditLog.description.in_(
                        (
                            "Updated flow retention policy",
                            "Updated Flow classification retention policy",
                        )
                    ),
                )
                .order_by(AuditLog.timestamp)
            )
        ).all()
    assert audit_metadata_rows
    for log_metadata in audit_metadata_rows:
        assert set(log_metadata) == {
            "old_policy",
            "new_policy",
            "preview",
            "activation",
        }


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    (
        ("get", "/api/v1/settings/flow-retention-policy", None),
        (
            "post",
            "/api/v1/settings/flow-retention-policy/preview",
            {
                "flow_run_history_retention_days": 30,
                "flow_runtime_upload_abandonment_days": None,
            },
        ),
        (
            "patch",
            "/api/v1/settings/flow-retention-policy",
            {"flow_run_history_retention_days": None},
        ),
    ),
)
async def test_non_admin_cannot_read_preview_or_write_tenant_flow_retention(
    client,
    non_admin_token,
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    response = await client.request(
        method,
        path,
        headers={"Authorization": f"Bearer {non_admin_token}"},
        json=payload,
    )
    assert response.status_code == 403
