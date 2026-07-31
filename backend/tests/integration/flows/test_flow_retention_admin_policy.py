from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
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
    FlowRunStepInputFiles,
    FlowRuntimeUploadedFiles,
    Flows,
    FlowVersions,
)
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
    ObjectContents,
    ObjectStoreObjects,
)
from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.main.models import ModelId
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _inline_content(
    *,
    tenant_id: UUID,
    user_id: UUID,
    payload: bytes,
    created_at: datetime,
) -> ObjectContents:
    digest = sha256(payload).digest()
    return ObjectContents(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        storage_kind="postgres_inline",
        state="available",
        access_class="private_resource",
        sha256=digest,
        size_bytes=len(payload),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        idempotency_key=f"flow-retention-preview-{uuid4()}",
        request_fingerprint=digest,
        available_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )


def _object_store_content(
    *,
    tenant_id: UUID,
    user_id: UUID,
    size_bytes: int,
    created_at: datetime,
) -> ObjectContents:
    digest = sha256(str(uuid4()).encode()).digest()
    return ObjectContents(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        storage_kind="object_store",
        state="available",
        access_class="private_resource",
        sha256=digest,
        size_bytes=size_bytes,
        declared_media_type="application/octet-stream",
        verified_media_type="application/octet-stream",
        idempotency_key=f"flow-retention-preview-{uuid4()}",
        request_fingerprint=digest,
        available_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )


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
    payload = b"x" * 128
    file = Files(
        name=f"unattached-{uuid4()}.txt",
        mimetype="text/plain",
        file_type="text",
        owner_type="user",
        owner_user_id=user_id,
        owner_service_id=None,
        tenant_id=tenant_id,
        created_at=created_at,
        updated_at=created_at,
    )
    content = _inline_content(
        tenant_id=tenant_id,
        user_id=user_id,
        payload=payload,
        created_at=created_at,
    )
    session.add_all([file, content])
    await session.flush()
    session.add_all(
        [
            InlineContentPayloads(
                content_id=content.id,
                storage_kind="postgres_inline",
                payload=payload,
            ),
            FileContentReferences(
                file_id=file.id,
                content_id=content.id,
                variant="original",
                ordinal=0,
            ),
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
            ),
        ]
    )


def _confirmation(preview: dict[str, object]) -> dict[str, object]:
    return {
        "expected_control_plane_version": preview["control_plane_version"],
        "expected_preview_hash": preview["preview_hash"],
        "previewed_at": preview["previewed_at"],
    }


async def test_preview_has_constant_query_count_and_natural_representative_plan(
    db_container,
    admin_user,
    retention_existing_data,
) -> None:
    flow_id, classification_id = retention_existing_data
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
        duplicate_file_id, duplicate_content_id = (
            await container.session().execute(
                sa.select(
                    FlowRuntimeUploadedFiles.file_id,
                    FileContentReferences.content_id,
                )
                .join(
                    FileContentReferences,
                    FileContentReferences.file_id == FlowRuntimeUploadedFiles.file_id,
                )
                .where(FlowRuntimeUploadedFiles.flow_id == flow_id)
                .limit(1)
            )
        ).one()
        container.session().add(
            FileContentReferences(
                file_id=duplicate_file_id,
                content_id=duplicate_content_id,
                variant="extracted_text",
                ordinal=0,
            )
        )
        await container.session().flush()
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
                mimetype="text/plain",
                file_type="text",
                owner_type="user",
                owner_user_id=admin_user.id,
                owner_service_id=None,
                tenant_id=admin_user.tenant_id,
                created_at=old,
                updated_at=old,
            )
            for _index in range(63)
        ]
        representative_payload = b"x" * 128
        large_content_size = 2**63 - 1
        large_content = _object_store_content(
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            size_bytes=large_content_size,
            created_at=old,
        )
        representative_contents = [large_content] + [
            _inline_content(
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
                payload=representative_payload,
                created_at=old,
            )
            for _index in range(62)
        ]
        container.session().add_all(
            representative_runs + representative_files + representative_contents
        )
        await container.session().flush()
        container.session().add_all(
            [
                InlineContentPayloads(
                    content_id=content.id,
                    storage_kind="postgres_inline",
                    payload=representative_payload,
                )
                for content in representative_contents[1:]
            ]
            + [
                ObjectStoreObjects(
                    content_id=large_content.id,
                    storage_kind="object_store",
                    object_key=f"retention-preview/{uuid4()}",
                    verification_chunk_size_bytes=1,
                    verification_chunk_sha256=large_content.sha256,
                    remote_observed_at=old,
                )
            ]
            + [
                FileContentReferences(
                    file_id=file.id,
                    content_id=content.id,
                    variant="original",
                    ordinal=0,
                )
                for file, content in zip(
                    representative_files,
                    representative_contents,
                    strict=True,
                )
            ]
        )
        await container.session().flush()
        representative_classifications = [
            SecurityClassification(
                name=f"Representative retention class {uuid4()}",
                description="Natural planner cardinality",
                security_level=2,
                tenant_id=admin_user.tenant_id,
            )
            for _index in range(127)
        ]
        container.session().add_all(representative_classifications)
        await container.session().flush()
        container.session().add_all(
            [
                FlowClassificationRetentionPolicies(
                    tenant_id=admin_user.tenant_id,
                    security_classification_id=classification.id,
                    data_retention_days=30,
                    minimum_retention_days=None,
                    no_purge=False,
                )
                for classification in representative_classifications
            ]
            + [
                FlowClassificationRetentionPolicies(
                    tenant_id=admin_user.tenant_id,
                    security_classification_id=classification_id,
                    data_retention_days=None,
                    minimum_retention_days=1,
                    no_purge=False,
                )
            ]
        )
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
        attached_step_id = uuid4()
        container.session().add_all(
            [
                FlowRunStepInputFiles(
                    flow_run_id=representative_runs[0].id,
                    flow_id=flow_id,
                    tenant_id=admin_user.tenant_id,
                    step_id=attached_step_id,
                    step_order=1,
                    attempt_no=1,
                    file_id=file_id,
                    ordinal=ordinal,
                )
                for ordinal, file_id in enumerate(
                    (
                        duplicate_file_id,
                        representative_files[0].id,
                        representative_files[1].id,
                    )
                )
            ]
        )
        await container.session().flush()
        content_reference_rows = (
            await container.session().execute(
                sa.select(
                    FlowRuntimeUploadedFiles.file_id,
                    FileContentReferences.content_id,
                    ObjectContents.size_bytes,
                )
                .join(
                    FileContentReferences,
                    FileContentReferences.file_id == FlowRuntimeUploadedFiles.file_id,
                )
                .join(
                    ObjectContents,
                    sa.and_(
                        ObjectContents.id == FileContentReferences.content_id,
                        ObjectContents.tenant_id == FlowRuntimeUploadedFiles.tenant_id,
                    ),
                )
                .where(FlowRuntimeUploadedFiles.flow_id == flow_id)
            )
        ).all()
        assert len(content_reference_rows) == 65
        assert (
            sum(
                {
                    (row.file_id, row.content_id): row.size_bytes
                    for row in content_reference_rows
                }.values()
            )
            == large_content_size + 63 * 128
        )
        classification_policy_count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(FlowClassificationRetentionPolicies)
            .where(
                FlowClassificationRetentionPolicies.tenant_id == admin_user.tenant_id
            )
        )

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
        connection = await container.session().connection()
        plans: list[str] = []
        for statement, parameters in impact_statements:
            result = await connection.exec_driver_sql(
                f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {statement}",
                parameters,
            )
            plans.append("\n".join(row[0] for row in result))

    assert legacy_child_only_candidates == 256
    assert classification_policy_count == 128
    assert canonical_off_candidates == []
    assert enabled_preview.run_history.newly_eligible_count == 256
    assert enabled_preview.run_history.no_longer_eligible_count == 0
    assert (
        enabled_preview.run_history.newly_eligible_bytes == large_content_size + 2 * 128
    )
    assert enabled_preview.runtime_uploads.newly_eligible_count == 61
    assert enabled_preview.runtime_uploads.newly_eligible_bytes == 61 * 128
    assert enabled_preview.lifecycle_blockers.undelivered_audit_count == 0
    assert enabled_preview.lifecycle_blockers.unresolved_webhook_count == 0
    assert enabled_preview.lifecycle_blockers.active_rerun_count == 0
    assert enabled_preview.latent_space_retention_days == (7,)
    assert enabled_preview.latent_flow_retention_days == (3,)
    assert disabled_preview.run_history.newly_eligible_count == 0
    assert disabled_preview.run_history.no_longer_eligible_count == 256
    assert disabled_preview.runtime_uploads.newly_eligible_count == 0
    assert disabled_preview.runtime_uploads.no_longer_eligible_count == 61
    assert disabled_preview.runtime_uploads.proposed_eligible_bytes == 0
    assert disabled_preview.latent_space_retention_days == (7,)
    assert disabled_preview.latent_flow_retention_days == (3,)
    assert len(enable_statements) == 6
    assert len(disable_statements) == 6
    assert all(
        statement.lstrip().startswith(("SELECT", "WITH"))
        for statement, _parameters in enable_statements + disable_statements
    )
    assert all("Buffers:" in plan for plan in plans)
    assert all("Execution Time:" in plan for plan in plans)
    assert all("enable_seqscan" not in plan for plan in plans)
    assert all(
        "flow_classification_retention_policies" in plan
        for plan in (plans[0], plans[2])
    )


async def test_preview_fails_closed_when_eligible_upload_lacks_primary_content(
    db_container,
    admin_user,
    retention_existing_data,
) -> None:
    flow_id, _classification_id = retention_existing_data
    old = datetime.now(timezone.utc) - timedelta(days=45)

    async with db_container() as container:
        file = Files(
            name=f"missing-retention-content-{uuid4()}.txt",
            mimetype="text/plain",
            file_type="text",
            owner_type="user",
            owner_user_id=admin_user.id,
            owner_service_id=None,
            tenant_id=admin_user.tenant_id,
            created_at=old,
            updated_at=old,
        )
        container.session().add(file)
        await container.session().flush()
        container.session().add(
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
        )
        await container.session().flush()

        retention_service = DataRetentionService(container.session())
        with pytest.raises(
            RuntimeError,
            match="1 File row\\(s\\) without durable primary content",
        ):
            await retention_service.preview_flow_retention_organization_change(
                tenant_id=admin_user.tenant_id,
                proposal=FlowRetentionOrganizationProposal(
                    flow_run_history_retention_days=30,
                    flow_runtime_upload_abandonment_days=30,
                ),
                previewed_at=datetime.now(timezone.utc),
            )


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
        "flow_run_history_minimum_retention_days": None,
        "flow_run_history_no_purge": False,
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
        json={
            "data_retention_days": 10,
            "minimum_retention_days": None,
            "no_purge": False,
        },
    )
    assert preview_response.status_code == 200, preview_response.text
    confirmed_proposal = {
        "data_retention_days": 10,
        "minimum_retention_days": None,
        "no_purge": False,
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
        "flow_run_history_minimum_retention_days": None,
        "flow_run_history_no_purge": False,
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
        json={
            "data_retention_days": 10,
            "minimum_retention_days": None,
            "no_purge": False,
        },
    )
    assert classification_preview.status_code == 200, classification_preview.text
    classification_impact = classification_preview.json()
    assert classification_impact["run_history"]["newly_eligible_count"] == 1

    classification_without_confirmation = await client.put(
        f"/api/v1/settings/flow-classification-retention-policies/{classification_id}",
        headers=headers,
        json={
            "data_retention_days": 10,
            "minimum_retention_days": None,
            "no_purge": False,
        },
    )
    assert classification_without_confirmation.status_code == 409

    classification_enabled = await client.put(
        f"/api/v1/settings/flow-classification-retention-policies/{classification_id}",
        headers=headers,
        json={
            "data_retention_days": 10,
            "minimum_retention_days": None,
            "no_purge": False,
            "confirmation": _confirmation(classification_impact),
        },
    )
    assert classification_enabled.status_code == 200, classification_enabled.text

    all_off = {
        "data_retention_days": None,
        "minimum_retention_days": None,
        "no_purge": False,
    }
    clear_preview_response = await client.post(
        f"/api/v1/settings/flow-classification-retention-policies/{classification_id}/preview",
        headers=headers,
        json=all_off,
    )
    assert clear_preview_response.status_code == 200, clear_preview_response.text
    unpreviewed_clear = await client.put(
        f"/api/v1/settings/flow-classification-retention-policies/{classification_id}",
        headers=headers,
        json=all_off,
    )
    assert unpreviewed_clear.status_code == 409
    cleared = await client.put(
        f"/api/v1/settings/flow-classification-retention-policies/{classification_id}",
        headers=headers,
        json={
            **all_off,
            "confirmation": _confirmation(clear_preview_response.json()),
        },
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json() is None
    independent_delete = await client.delete(
        f"/api/v1/settings/flow-classification-retention-policies/{classification_id}",
        headers=headers,
    )
    assert independent_delete.status_code == 405

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
                "flow_run_history_minimum_retention_days": None,
                "flow_run_history_no_purge": False,
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
