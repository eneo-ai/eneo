from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.infrastructure import (
    data_retention_service as data_retention_service_module,
)
from eneo.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
)
from eneo.database.tables.assistant_table import Assistants, AssistantsFiles
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_classification_retention_policy_table import (
    FlowClassificationRetentionPolicies,
)
from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
    FlowRunRerunOperations,
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowRuntimeUploadedFiles,
    FlowRunWebhookDeliveries,
    Flows,
    FlowStepAttempts,
    FlowStepResults,
    FlowSteps,
    FlowTemplateAssets,
    FlowVersions,
)
from eneo.database.tables.security_classifications_table import SecurityClassification
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.enums import (
    FlowRunRerunOperationStatus,
    FlowRunReviewCheckpointState,
    FlowRunStatus,
)
from eneo.flows.flow_retention_tombstone import (
    FLOW_RETENTION_ACTOR_SOURCE,
    FlowAttemptRetentionMarker,
    RunDebugAttemptRetentionCounts,
    extract_retention_tombstones,
)
from eneo.flows.infrastructure import (
    flow_run_history_purge_repo as flow_run_history_purge_repo_module,
)
from eneo.flows.infrastructure.flow_run_history_purge_repo import (
    FlowRunHistoryPurgeCounts,
    FlowRunHistoryPurgeRepository,
)
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRepository,
)


@dataclass(frozen=True)
class FlowRuntimeRetentionFixture:
    flow: Flows
    run: FlowRuns
    step_id: UUID
    step_result: FlowStepResults
    step_attempt: FlowStepAttempts
    generated_file: Files
    runtime_input_file: Files
    review_checkpoint: FlowRunReviewCheckpoints
    webhook_delivery: FlowRunWebhookDeliveries


@dataclass(frozen=True)
class FlowTemplateAssetRetentionFixture:
    flow: Flows
    template_file: Files
    template_asset: FlowTemplateAssets


@pytest.fixture
async def flow_retention_service(
    async_session: AsyncSession,
) -> DataRetentionService:
    return DataRetentionService(async_session)


@pytest.fixture
async def flow_retention_space(
    async_session: AsyncSession, test_tenant, admin_user
) -> Spaces:
    space = Spaces(
        name=f"Flow retention space {admin_user.id}",
        description="Flow runtime retention tests",
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
        tenant_space_id=None,
        data_retention_days=None,
    )
    async_session.add(space)
    await async_session.flush()
    return space


@pytest.fixture
async def flow_retention_assistant(
    async_session: AsyncSession,
    flow_retention_space: Spaces,
    admin_user,
    completion_model_factory,
) -> Assistants:
    completion_model = await completion_model_factory(async_session, "gpt-4")
    assistant = Assistants(
        name="Flow retention assistant",
        description="Flow runtime retention",
        user_id=admin_user.id,
        space_id=flow_retention_space.id,
        completion_model_id=completion_model.id,
        completion_model_kwargs={},
        logging_enabled=True,
        is_default=False,
        published=False,
        data_retention_days=None,
    )
    async_session.add(assistant)
    await async_session.flush()
    return assistant


async def _create_flow_runtime_fixture(
    async_session: AsyncSession,
    *,
    tenant,
    user,
    space: Spaces,
    assistant: Assistants,
    days_old: int,
    flow_retention_days: int | None = None,
    flow_settings: dict | None = None,
    generated_file_has_content: bool = True,
    flow_deleted: bool = False,
    run_id: UUID | None = None,
) -> FlowRuntimeRetentionFixture:
    if flow_settings is not None:
        await async_session.execute(
            update(Tenants)
            .where(Tenants.id == tenant.id)
            .values(flow_settings=flow_settings)
        )
        await async_session.flush()

    created_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    step_id = uuid4()
    flow = Flows(
        name=f"Retention flow {uuid4()}",
        description="Retention cleanup target",
        tenant_id=tenant.id,
        space_id=space.id,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json={},
        data_retention_days=flow_retention_days,
        draft_revision=0,
        deleted_at=created_at if flow_deleted else None,
        created_at=created_at,
        updated_at=created_at,
    )
    async_session.add(flow)
    await async_session.flush()

    async_session.add(
        FlowVersions(
            flow_id=flow.id,
            version=1,
            tenant_id=tenant.id,
            definition_checksum="checksum",
            definition_json={"steps": []},
            created_at=created_at,
            updated_at=created_at,
        )
    )
    await async_session.flush()
    flow.published_version = 1

    generated_file = Files(
        name="generated.docx",
        text=None,
        blob=b"docx-bytes" if generated_file_has_content else None,
        checksum="generated-checksum",
        size=1024,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_type="document",
        transcription=None if generated_file_has_content else "stale-transcript",
        owner_type="user",
        owner_user_id=user.id,
        tenant_id=tenant.id,
        created_at=created_at,
        updated_at=created_at,
    )
    async_session.add(generated_file)
    await async_session.flush()

    runtime_input_file = Files(
        name="runtime-input.txt",
        text="runtime input file text",
        blob=None,
        checksum=f"runtime-input-{uuid4()}",
        size=128,
        mimetype="text/plain",
        file_type="text",
        transcription=None,
        owner_type="user",
        owner_user_id=user.id,
        owner_service_id=None,
        tenant_id=tenant.id,
        created_at=created_at,
        updated_at=created_at,
    )
    async_session.add(runtime_input_file)
    await async_session.flush()

    async_session.add(
        FlowRuntimeUploadedFiles(
            file_id=runtime_input_file.id,
            flow_id=flow.id,
            tenant_id=tenant.id,
            uploaded_for_step_id=step_id,
            owner_type="user",
            owner_user_id=user.id,
            owner_service_id=None,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    await async_session.flush()

    run = FlowRuns(
        id=run_id or uuid4(),
        flow_id=flow.id,
        flow_version=1,
        principal_type="user",
        principal_user_id=user.id,
        tenant_id=tenant.id,
        trace_id=uuid4(),
        idempotency_key=None,
        request_fingerprint=None,
        status="completed",
        cancelled_at=None,
        started_at=created_at,
        finished_at=created_at,
        input_payload_json={"input": "source"},
        output_payload_json={"result": "ok"},
        job_id=None,
        created_at=created_at,
        updated_at=created_at,
    )
    async_session.add(run)
    await async_session.flush()

    async_session.add(
        FlowSteps(
            id=step_id,
            flow_id=flow.id,
            tenant_id=tenant.id,
            assistant_id=assistant.id,
            step_order=1,
            user_description="Generate artifact",
            input_source="flow_input",
            input_type="text",
            output_mode="render_verbatim",
            output_type="docx",
            created_at=created_at,
            updated_at=created_at,
        )
    )
    await async_session.flush()
    output_payload_json = {
        "text": "kept output",
        "template_fill_debug": {"rendered_docx_text_raw": "debug body"},
    }

    step_result = FlowStepResults(
        flow_run_id=run.id,
        flow_id=flow.id,
        tenant_id=tenant.id,
        step_id=step_id,
        step_order=1,
        assistant_id=assistant.id,
        input_payload_json={"text": "sensitive input"},
        effective_prompt="Very sensitive prompt",
        output_payload_json=output_payload_json,
        model_parameters_json={"temperature": 0.1},
        num_tokens_input=10,
        num_tokens_output=20,
        status="completed",
        error_message=None,
        flow_step_execution_hash=None,
        started_at=created_at,
        finished_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )
    async_session.add(step_result)
    await async_session.flush()
    step_attempt = FlowStepAttempts(
        flow_run_id=run.id,
        flow_id=flow.id,
        tenant_id=tenant.id,
        step_id=step_id,
        step_order=1,
        attempt_no=1,
        celery_task_id=None,
        status="completed",
        error_code=None,
        error_message=None,
        requested_model="gpt-4",
        response_model="gpt-4",
        provider="openai",
        finish_reason="stop",
        provider_response_id="resp-1",
        num_tokens_input=10,
        num_tokens_output=20,
        provenance_json={"artifacts": {"items": ["debug"]}},
        input_payload_json={"text": "sensitive attempt input"},
        output_payload_json={"text": "sensitive attempt output"},
        started_at=created_at,
        finished_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )
    async_session.add(step_attempt)
    await async_session.flush()

    async_session.add(
        FlowRunStepResultFiles(
            flow_run_id=run.id,
            flow_id=flow.id,
            tenant_id=tenant.id,
            step_result_id=step_result.id,
            step_id=step_id,
            step_order=1,
            attempt_no=1,
            file_id=generated_file.id,
            ordinal=0,
            source="declared_artifact",
        )
    )
    await async_session.flush()

    async_session.add(
        FlowRunStepInputFiles(
            flow_run_id=run.id,
            flow_id=flow.id,
            tenant_id=tenant.id,
            step_id=step_id,
            step_order=1,
            attempt_no=1,
            file_id=runtime_input_file.id,
            ordinal=0,
            created_at=created_at,
            updated_at=created_at,
        )
    )

    review_checkpoint = FlowRunReviewCheckpoints(
        tenant_id=tenant.id,
        flow_id=flow.id,
        flow_run_id=run.id,
        step_id=step_id,
        step_order=1,
        attempt_no=1,
        state=FlowRunReviewCheckpointState.RESUMED.value,
        revision=1,
        schema_version=1,
        original_payload_json={"text": "review original"},
        current_payload_json={"text": "review final"},
        step_label="Review generated artifact",
        review_mode="edit",
        output_type="docx",
        output_contract_json=None,
        requester_user_id=user.id,
        requester_service_id=None,
        requester_principal_type="user",
        decided_by_user_id=user.id,
        decided_by_service_id=None,
        decided_by_principal_type="user",
        next_step_ids_json=[],
        resume_idempotency_key=f"resume-{uuid4()}",
        edited_at=created_at,
        approved_at=created_at,
        rejected_at=None,
        resumed_at=created_at,
        cancelled_at=None,
        expires_at=None,
        expired_at=None,
        created_at=created_at,
        updated_at=created_at,
    )
    async_session.add(review_checkpoint)
    await async_session.flush()

    webhook_delivery = FlowRunWebhookDeliveries(
        tenant_id=tenant.id,
        flow_id=flow.id,
        flow_run_id=run.id,
        step_id=step_id,
        step_order=1,
        attempt_no=1,
        idempotency_key=f"{run.id}:1:webhook",
        payload_ref="step_output",
        delivery_status=FlowOutboxDeliveryStatus.DELIVERED.value,
        delivery_attempts=1,
        next_delivery_at=None,
        claim_token=None,
        claimed_at=None,
        claim_expires_at=None,
        delivered_at=created_at,
        dead_lettered_at=None,
        delivery_last_error=None,
        created_at=created_at,
        updated_at=created_at,
    )
    async_session.add(webhook_delivery)
    await async_session.flush()

    return FlowRuntimeRetentionFixture(
        flow=flow,
        run=run,
        step_id=step_id,
        step_result=step_result,
        step_attempt=step_attempt,
        generated_file=generated_file,
        runtime_input_file=runtime_input_file,
        review_checkpoint=review_checkpoint,
        webhook_delivery=webhook_delivery,
    )


async def _create_flow_template_asset_fixture(
    async_session: AsyncSession,
    *,
    tenant,
    user,
    space: Spaces,
    deleted: bool,
) -> FlowTemplateAssetRetentionFixture:
    now = datetime.now(timezone.utc)
    flow = Flows(
        name=f"Template retention flow {uuid4()}",
        description="Template asset retention target",
        tenant_id=tenant.id,
        space_id=space.id,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json={},
        data_retention_days=None,
        draft_revision=0,
        created_at=now,
        updated_at=now,
    )
    async_session.add(flow)
    await async_session.flush()

    template_file = Files(
        name="template.docx",
        text=None,
        blob=b"docx-template-bytes",
        checksum=f"template-{uuid4()}",
        size=1024,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_type="document",
        transcription=None,
        owner_type="user",
        owner_user_id=user.id,
        owner_service_id=None,
        tenant_id=tenant.id,
        created_at=now,
        updated_at=now,
    )
    async_session.add(template_file)
    await async_session.flush()

    template_asset = FlowTemplateAssets(
        flow_id=flow.id,
        space_id=space.id,
        tenant_id=tenant.id,
        file_id=template_file.id,
        name=template_file.name,
        checksum=template_file.checksum,
        mimetype=template_file.mimetype,
        placeholders=["Body"],
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
        status="ready",
        deleted_at=now if deleted else None,
        created_at=now,
        updated_at=now,
    )
    async_session.add(template_asset)
    await async_session.flush()
    return FlowTemplateAssetRetentionFixture(
        flow=flow,
        template_file=template_file,
        template_asset=template_asset,
    )


async def _add_flow_version_definition(
    async_session: AsyncSession,
    *,
    flow: Flows,
    tenant_id: UUID,
    version: int,
    definition_json: FlowPersistedJsonObject,
) -> None:
    async_session.add(
        FlowVersions(
            flow_id=flow.id,
            version=version,
            tenant_id=tenant_id,
            definition_checksum=f"checksum-{uuid4()}",
            definition_json=definition_json,
        )
    )
    await async_session.flush()


async def _add_younger_flow_runtime_result_file_reference(
    async_session: AsyncSession,
    *,
    source_run: FlowRuns,
    source_step_result: FlowStepResults,
    generated_file: Files,
) -> None:
    """Add a second live Flow result-file reference to the same file row."""
    created_at = datetime.now(timezone.utc)
    reference_run = FlowRuns(
        flow_id=source_run.flow_id,
        flow_version=source_run.flow_version,
        principal_type="user",
        principal_user_id=source_run.principal_user_id,
        tenant_id=source_run.tenant_id,
        trace_id=uuid4(),
        idempotency_key=None,
        request_fingerprint=None,
        status="completed",
        cancelled_at=None,
        started_at=created_at,
        finished_at=created_at,
        input_payload_json={"input": "still live"},
        output_payload_json={"result": "still live"},
        job_id=None,
        created_at=created_at,
        updated_at=created_at,
    )
    async_session.add(reference_run)
    await async_session.flush()

    reference_step_result = FlowStepResults(
        flow_run_id=reference_run.id,
        flow_id=reference_run.flow_id,
        tenant_id=reference_run.tenant_id,
        step_id=source_step_result.step_id,
        step_order=source_step_result.step_order,
        assistant_id=source_step_result.assistant_id,
        input_payload_json={"text": "live input"},
        effective_prompt="Live prompt",
        output_payload_json={"text": "live output"},
        model_parameters_json={"temperature": 0.2},
        num_tokens_input=5,
        num_tokens_output=8,
        status="completed",
        error_message=None,
        flow_step_execution_hash=None,
        started_at=created_at,
        finished_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )
    async_session.add(reference_step_result)
    await async_session.flush()

    async_session.add(
        FlowStepAttempts(
            flow_run_id=reference_run.id,
            flow_id=reference_run.flow_id,
            tenant_id=reference_run.tenant_id,
            step_id=source_step_result.step_id,
            step_order=source_step_result.step_order,
            attempt_no=1,
            celery_task_id=None,
            status="completed",
            error_code=None,
            error_message=None,
            requested_model="gpt-4",
            response_model="gpt-4",
            provider="openai",
            finish_reason="stop",
            provider_response_id="resp-younger",
            num_tokens_input=5,
            num_tokens_output=8,
            provenance_json={"artifacts": {"items": ["live"]}},
            started_at=created_at,
            finished_at=created_at,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    await async_session.flush()

    async_session.add(
        FlowRunStepResultFiles(
            flow_run_id=reference_run.id,
            flow_id=reference_run.flow_id,
            tenant_id=reference_run.tenant_id,
            step_result_id=reference_step_result.id,
            step_id=reference_step_result.step_id,
            step_order=reference_step_result.step_order,
            attempt_no=1,
            file_id=generated_file.id,
            ordinal=0,
            source="declared_artifact",
        )
    )
    await async_session.flush()


async def _add_flow_runtime_input_reference(
    async_session: AsyncSession,
    *,
    source_run: FlowRuns,
    step_id: UUID,
    file_id: UUID,
    run_id: UUID,
    created_at: datetime,
) -> FlowRuns:
    reference_run = FlowRuns(
        id=run_id,
        flow_id=source_run.flow_id,
        flow_version=source_run.flow_version,
        principal_type=source_run.principal_type,
        principal_user_id=source_run.principal_user_id,
        principal_service_id=source_run.principal_service_id,
        tenant_id=source_run.tenant_id,
        trace_id=uuid4(),
        idempotency_key=None,
        request_fingerprint=None,
        status=FlowRunStatus.COMPLETED.value,
        cancelled_at=None,
        started_at=created_at,
        finished_at=created_at,
        input_payload_json={"input": "shared source"},
        output_payload_json={"result": "complete"},
        job_id=None,
        created_at=created_at,
        updated_at=created_at,
    )
    async_session.add(reference_run)
    await async_session.flush()
    async_session.add(
        FlowRunStepInputFiles(
            flow_run_id=reference_run.id,
            flow_id=reference_run.flow_id,
            tenant_id=reference_run.tenant_id,
            step_id=step_id,
            step_order=1,
            attempt_no=1,
            file_id=file_id,
            ordinal=0,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    await async_session.flush()
    return reference_run


async def _add_flow_audit_outbox_row(
    async_session: AsyncSession,
    *,
    run: FlowRuns,
    user_id: UUID,
    delivery_status: str,
    with_audit_log: bool,
):
    created_at = run.created_at
    delivered_at = (
        created_at
        if delivery_status == FlowOutboxDeliveryStatus.DELIVERED.value
        else None
    )
    dead_lettered_at = (
        created_at
        if delivery_status == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
        else None
    )
    outbox = FlowRunAuditOutbox(
        tenant_id=run.tenant_id,
        flow_id=run.flow_id,
        flow_run_id=run.id,
        run_revision=run.revision,
        review_checkpoint_id=None,
        checkpoint_revision=None,
        description="flow_run_completed:executor_completed",
        action="flow_run_completed",
        entity_type="flow_run",
        entity_id=run.id,
        actor_id=user_id,
        actor_type="user",
        actor_api_key_id=None,
        source="executor_completed",
        target_status="completed",
        error_code=None,
        error_message=None,
        delivery_status=delivery_status,
        delivery_attempts=(
            1 if delivery_status != FlowOutboxDeliveryStatus.PENDING.value else 0
        ),
        next_delivery_at=(
            None
            if delivery_status != FlowOutboxDeliveryStatus.PENDING.value
            else created_at
        ),
        delivered_at=delivered_at,
        dead_lettered_at=dead_lettered_at,
        delivery_last_error=(
            "audit projection failed"
            if delivery_status == FlowOutboxDeliveryStatus.DEAD_LETTERED.value
            else None
        ),
        created_at=created_at,
        updated_at=created_at,
    )
    async_session.add(outbox)
    await async_session.flush()

    if with_audit_log:
        async_session.add(
            AuditLogTable(
                id=outbox.id,
                tenant_id=run.tenant_id,
                actor_id=user_id,
                actor_type="user",
                actor_api_key_id=None,
                action="flow_run_completed",
                entity_type="flow_run",
                entity_id=run.id,
                timestamp=created_at,
                description="Flow run completed by executor_completed.",
                log_metadata={"flow_run_id": str(run.id)},
                outcome="success",
                error_message=None,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        await async_session.flush()

    return outbox.id


async def _add_active_rerun_operation(
    async_session: AsyncSession,
    *,
    fixture: FlowRuntimeRetentionFixture,
    user_id: UUID,
    status: FlowRunRerunOperationStatus = FlowRunRerunOperationStatus.QUEUED,
) -> UUID:
    operation = FlowRunRerunOperations(
        tenant_id=fixture.run.tenant_id,
        flow_id=fixture.run.flow_id,
        flow_run_id=fixture.run.id,
        rerun_step_id=fixture.step_id,
        rerun_step_order=1,
        root_attempt_no=1,
        root_attempt_id=fixture.step_attempt.id,
        status=status.value,
        request_fingerprint=f"rerun-{uuid4()}",
        expected_run_revision=fixture.run.revision,
        accepted_run_revision=fixture.run.revision + 1,
        reason="Retry after manual review.",
        input_payload_json=None,
        root_step_input_override_requested=False,
        requested_by_principal_type="user",
        requested_by_user_id=user_id,
        requested_by_service_id=None,
        failure_code=None,
        failure_message=None,
        started_at=fixture.run.finished_at
        if status == FlowRunRerunOperationStatus.RUNNING
        else None,
        finished_at=None,
        created_at=fixture.run.created_at,
        updated_at=fixture.run.created_at,
    )
    async_session.add(operation)
    await async_session.flush()
    return operation.id


async def _set_webhook_delivery_pending(
    async_session: AsyncSession,
    *,
    delivery_id: UUID,
    now: datetime,
    claim_expires_at: datetime | None,
) -> UUID | None:
    claim_token = uuid4() if claim_expires_at is not None else None
    await async_session.execute(
        update(FlowRunWebhookDeliveries)
        .where(FlowRunWebhookDeliveries.id == delivery_id)
        .values(
            delivery_status=FlowOutboxDeliveryStatus.PENDING.value,
            delivery_attempts=0,
            next_delivery_at=now,
            claim_token=claim_token,
            claimed_at=(
                now - timedelta(minutes=1) if claim_token is not None else None
            ),
            claim_expires_at=claim_expires_at,
            delivered_at=None,
            dead_lettered_at=None,
            delivery_last_error=None,
        )
    )
    return claim_token


async def _assign_space_classification_retention_policy(
    async_session: AsyncSession,
    *,
    tenant_id: UUID,
    space: Spaces,
    data_retention_days: int,
    name: str = "Sensitive Flow history",
) -> SecurityClassification:
    classification = SecurityClassification(
        name=f"{name} {uuid4()}",
        description="Retention test classification",
        security_level=0,
        tenant_id=tenant_id,
    )
    async_session.add(classification)
    await async_session.flush()

    space.security_classification_id = classification.id
    async_session.add(
        FlowClassificationRetentionPolicies(
            tenant_id=tenant_id,
            security_classification_id=classification.id,
            data_retention_days=data_retention_days,
        )
    )
    await async_session.flush()
    return classification


async def _count_for_run(
    async_session: AsyncSession,
    table: type,
    *,
    run_id: UUID,
) -> int:
    return int(
        await async_session.scalar(
            select(func.count()).select_from(table).where(table.flow_run_id == run_id)
        )
        or 0
    )


async def _flow_runtime_upload_exists(
    async_session: AsyncSession,
    *,
    file_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
) -> bool:
    return bool(
        await async_session.scalar(
            select(FlowRuntimeUploadedFiles.file_id)
            .where(FlowRuntimeUploadedFiles.file_id == file_id)
            .where(FlowRuntimeUploadedFiles.flow_id == flow_id)
            .where(FlowRuntimeUploadedFiles.tenant_id == tenant_id)
        )
    )


async def _flush_and_clear_identity_map(async_session: AsyncSession) -> None:
    await async_session.flush()
    async_session.expunge_all()


@pytest.mark.asyncio
async def test_purge_soft_deleted_flow_template_assets_reclaims_unpinned_blob(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_template_asset_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        deleted=True,
    )

    counts = await flow_retention_service.purge_soft_deleted_flow_template_assets(
        limit=10,
    )
    await _flush_and_clear_identity_map(async_session)

    assert counts.flow_template_assets_purged == 1
    assert counts.flow_template_asset_files_deleted == 1
    assert counts.flow_template_assets_skipped_published_reference == 0
    assert counts.flow_template_assets_skipped_undetermined_reference == 0
    assert (
        await async_session.get(FlowTemplateAssets, fixture.template_asset.id) is None
    )
    assert await async_session.get(Files, fixture.template_file.id) is None


@pytest.mark.asyncio
async def test_purge_soft_deleted_flow_template_assets_keeps_active_asset_blob(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_template_asset_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        deleted=False,
    )

    counts = await flow_retention_service.purge_soft_deleted_flow_template_assets(
        limit=10,
    )
    await _flush_and_clear_identity_map(async_session)

    assert counts.flow_template_assets_purged == 0
    assert counts.flow_template_asset_files_deleted == 0
    assert await async_session.get(FlowTemplateAssets, fixture.template_asset.id)
    assert await async_session.get(Files, fixture.template_file.id)


@pytest.mark.asyncio
async def test_purge_soft_deleted_flow_template_assets_keeps_non_current_version_pin(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_template_asset_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        deleted=True,
    )
    await _add_flow_version_definition(
        async_session,
        flow=fixture.flow,
        tenant_id=test_tenant.id,
        version=1,
        definition_json={
            "schema_version": 1,
            "steps": [
                {
                    "output_config": {
                        "template_asset_id": str(fixture.template_asset.id),
                        "template_file_id": str(fixture.template_file.id),
                    }
                }
            ],
        },
    )
    await _add_flow_version_definition(
        async_session,
        flow=fixture.flow,
        tenant_id=test_tenant.id,
        version=2,
        definition_json={"schema_version": 1, "steps": []},
    )

    counts = await flow_retention_service.purge_soft_deleted_flow_template_assets(
        limit=10,
    )
    await _flush_and_clear_identity_map(async_session)

    assert counts.flow_template_assets_purged == 0
    assert counts.flow_template_asset_files_deleted == 0
    assert counts.flow_template_assets_skipped_published_reference == 1
    assert counts.flow_template_assets_skipped_undetermined_reference == 0
    assert await async_session.get(FlowTemplateAssets, fixture.template_asset.id)
    assert await async_session.get(Files, fixture.template_file.id)


@pytest.mark.asyncio
async def test_purge_soft_deleted_flow_template_assets_counts_unknown_schema_skip(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_template_asset_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        deleted=True,
    )
    await _add_flow_version_definition(
        async_session,
        flow=fixture.flow,
        tenant_id=test_tenant.id,
        version=1,
        definition_json={"schema_version": 2, "future_steps": []},
    )

    counts = await flow_retention_service.purge_soft_deleted_flow_template_assets(
        limit=10,
    )
    await _flush_and_clear_identity_map(async_session)

    assert counts.flow_template_assets_purged == 0
    assert counts.flow_template_asset_files_deleted == 0
    assert counts.flow_template_assets_skipped_published_reference == 0
    assert counts.flow_template_assets_skipped_undetermined_reference == 1
    assert await async_session.get(FlowTemplateAssets, fixture.template_asset.id)
    assert await async_session.get(Files, fixture.template_file.id)


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_purges_old_flow_run_history_and_preserves_audit(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
    )
    audit_log_id = await _add_flow_audit_outbox_row(
        async_session,
        run=fixture.run,
        user_id=admin_user.id,
        delivery_status=FlowOutboxDeliveryStatus.DELIVERED.value,
        with_audit_log=True,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_considered"] == 1
    assert counts["flow_runs_lock_deferred"] == 0
    assert counts["flow_runs_purged"] == 1
    assert counts["flow_generated_files_deleted"] == 1
    assert counts["flow_runtime_source_candidates"] == 1
    assert counts["flow_runtime_source_candidate_bytes"] == 128
    assert counts["flow_runtime_source_bindings_deleted"] == 1
    assert counts["flow_runtime_source_files_deleted"] == 1
    assert counts["flow_runtime_source_bytes_deleted"] == 128
    assert counts["flow_webhook_deliveries_deleted"] == 1
    assert counts["flow_audit_outbox_rows_deleted"] == 1
    assert counts["flow_review_checkpoints_deleted"] == 1
    assert counts["flow_runs_skipped_undelivered_audit"] == 0
    assert counts["flow_runs_skipped_unresolved_webhook"] == 0
    assert counts["flow_runs_skipped_active_rerun"] == 0
    assert counts["debug_step_results"] == 0
    assert counts["debug_step_attempts"] == 0

    assert await async_session.get(FlowRuns, fixture.run.id) is None
    assert await async_session.get(FlowStepResults, fixture.step_result.id) is None
    assert await async_session.get(FlowStepAttempts, fixture.step_attempt.id) is None
    assert await async_session.get(Files, fixture.generated_file.id) is None
    assert await async_session.get(AuditLogTable, audit_log_id) is not None
    assert await async_session.get(Files, fixture.runtime_input_file.id) is None
    assert not await _flow_runtime_upload_exists(
        async_session,
        file_id=fixture.runtime_input_file.id,
        flow_id=fixture.flow.id,
        tenant_id=test_tenant.id,
    )
    assert (
        await _count_for_run(
            async_session,
            FlowRunReviewCheckpoints,
            run_id=fixture.run.id,
        )
        == 0
    )
    assert (
        await _count_for_run(
            async_session,
            FlowRunWebhookDeliveries,
            run_id=fixture.run.id,
        )
        == 0
    )
    assert (
        await _count_for_run(async_session, FlowRunAuditOutbox, run_id=fixture.run.id)
        == 0
    )
    assert (
        await _count_for_run(
            async_session,
            FlowRunStepInputFiles,
            run_id=fixture.run.id,
        )
        == 0
    )
    assert (
        await _count_for_run(
            async_session,
            FlowRunStepResultFiles,
            run_id=fixture.run.id,
        )
        == 0
    )

    second_counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert second_counts["flow_runs_considered"] == 0
    assert second_counts["flow_runs_lock_deferred"] == 0
    assert second_counts["flow_runs_purged"] == 0
    assert second_counts["flow_generated_files_deleted"] == 0
    assert second_counts["flow_runtime_source_candidates"] == 0
    assert second_counts["flow_runtime_source_candidate_bytes"] == 0
    assert second_counts["flow_runtime_source_bindings_deleted"] == 0
    assert second_counts["flow_runtime_source_files_deleted"] == 0
    assert second_counts["flow_runtime_source_bytes_deleted"] == 0
    assert second_counts["flow_webhook_deliveries_deleted"] == 0
    assert second_counts["flow_audit_outbox_rows_deleted"] == 0
    assert second_counts["flow_review_checkpoints_deleted"] == 0


@pytest.mark.asyncio
async def test_flow_run_history_purge_reclaims_runtime_source_after_final_reference(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        flow_run_history_purge_repo_module,
        "_FLOW_RUN_HISTORY_PURGE_FILE_CANDIDATE_LIMIT",
        2,
    )
    first_run_id = UUID("00000000-0000-0000-0000-000000000001")
    second_run_id = UUID("00000000-0000-0000-0000-000000000002")
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
        run_id=first_run_id,
    )
    async_session.add(
        FlowRunStepInputFiles(
            flow_run_id=fixture.run.id,
            flow_id=fixture.flow.id,
            tenant_id=test_tenant.id,
            step_id=fixture.step_id,
            step_order=1,
            attempt_no=2,
            file_id=fixture.runtime_input_file.id,
            ordinal=0,
        )
    )
    await async_session.flush()
    await _add_flow_runtime_input_reference(
        async_session,
        source_run=fixture.run,
        step_id=fixture.step_id,
        file_id=fixture.runtime_input_file.id,
        run_id=second_run_id,
        created_at=fixture.run.created_at,
    )
    source_file_id = fixture.runtime_input_file.id
    flow_id = fixture.flow.id

    first_result = await flow_retention_service.purge_old_flow_run_history_batch(
        now=datetime.now(timezone.utc),
        limit=10,
    )
    await _flush_and_clear_identity_map(async_session)

    assert first_result.counts.flow_runs_considered == 1
    assert first_result.counts.flow_runs_lock_deferred == 0
    assert first_result.counts.flow_runs_purged == 1
    assert first_result.counts.flow_runtime_source_candidates == 1
    assert first_result.counts.flow_runtime_source_candidate_bytes == 128
    assert first_result.counts.flow_runtime_source_bindings_deleted == 0
    assert first_result.counts.flow_runtime_source_files_deleted == 0
    assert first_result.counts.flow_runtime_source_bytes_deleted == 0
    assert await async_session.get(FlowRuns, first_run_id) is None
    assert await async_session.get(FlowRuns, second_run_id) is not None
    assert await async_session.get(Files, source_file_id) is not None
    assert await _flow_runtime_upload_exists(
        async_session,
        file_id=source_file_id,
        flow_id=flow_id,
        tenant_id=test_tenant.id,
    )

    second_result = await flow_retention_service.purge_old_flow_run_history_batch(
        now=datetime.now(timezone.utc),
        limit=10,
    )
    await _flush_and_clear_identity_map(async_session)

    assert second_result.counts.flow_runs_considered == 1
    assert second_result.counts.flow_runs_lock_deferred == 0
    assert second_result.counts.flow_runs_purged == 1
    assert second_result.counts.flow_runtime_source_candidates == 1
    assert second_result.counts.flow_runtime_source_candidate_bytes == 128
    assert second_result.counts.flow_runtime_source_bindings_deleted == 1
    assert second_result.counts.flow_runtime_source_files_deleted == 1
    assert second_result.counts.flow_runtime_source_bytes_deleted == 128
    assert await async_session.get(FlowRuns, second_run_id) is None
    assert await async_session.get(Files, source_file_id) is None
    assert not await _flow_runtime_upload_exists(
        async_session,
        file_id=source_file_id,
        flow_id=flow_id,
        tenant_id=test_tenant.id,
    )

    third_result = await flow_retention_service.purge_old_flow_run_history_batch(
        now=datetime.now(timezone.utc),
        limit=10,
    )
    assert third_result.counts == FlowRunHistoryPurgeCounts()
    assert third_result.affected_flow_tenant_ids == frozenset()


@pytest.mark.asyncio
async def test_flow_run_history_purge_keeps_runtime_source_with_another_owner(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
    )
    source_file_id = fixture.runtime_input_file.id
    async_session.add(
        AssistantsFiles(
            assistant_id=flow_retention_assistant.id,
            file_id=source_file_id,
        )
    )
    await async_session.flush()

    result = await flow_retention_service.purge_old_flow_run_history_batch(
        now=datetime.now(timezone.utc),
        limit=10,
    )
    await _flush_and_clear_identity_map(async_session)

    assert result.counts.flow_runs_purged == 1
    assert result.counts.flow_runtime_source_candidates == 1
    assert result.counts.flow_runtime_source_bindings_deleted == 1
    assert result.counts.flow_runtime_source_files_deleted == 0
    assert result.counts.flow_runtime_source_bytes_deleted == 0
    assert await async_session.get(Files, source_file_id) is not None
    assert await async_session.get(
        AssistantsFiles,
        (flow_retention_assistant.id, source_file_id),
    )
    assert not await _flow_runtime_upload_exists(
        async_session,
        file_id=source_file_id,
        flow_id=fixture.flow.id,
        tenant_id=test_tenant.id,
    )


@pytest.mark.asyncio
async def test_flow_run_history_purge_keeps_runtime_source_with_derived_child(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
    )
    source_file_id = fixture.runtime_input_file.id
    child_file = Files(
        name="runtime-source-child.txt",
        text="derived child",
        blob=None,
        checksum=f"runtime-source-child-{uuid4()}",
        size=13,
        mimetype="text/plain",
        file_type="text",
        transcription=None,
        owner_type="user",
        owner_user_id=admin_user.id,
        owner_service_id=None,
        tenant_id=test_tenant.id,
        parent_file_id=source_file_id,
    )
    async_session.add(child_file)
    await async_session.flush()
    child_file_id = child_file.id

    result = await flow_retention_service.purge_old_flow_run_history_batch(
        now=datetime.now(timezone.utc),
        limit=10,
    )
    await _flush_and_clear_identity_map(async_session)

    assert result.counts.flow_runs_purged == 1
    assert result.counts.flow_runtime_source_candidates == 1
    assert result.counts.flow_runtime_source_bindings_deleted == 1
    assert result.counts.flow_runtime_source_files_deleted == 0
    assert result.counts.flow_runtime_source_bytes_deleted == 0
    assert await async_session.get(Files, source_file_id) is not None
    assert await async_session.get(Files, child_file_id) is not None
    assert not await _flow_runtime_upload_exists(
        async_session,
        file_id=source_file_id,
        flow_id=fixture.flow.id,
        tenant_id=test_tenant.id,
    )


@pytest.mark.asyncio
async def test_flow_run_history_purge_rollback_restores_run_binding_and_source(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
    )
    run_id = fixture.run.id
    flow_id = fixture.flow.id
    source_file_id = fixture.runtime_input_file.id
    savepoint = await async_session.begin_nested()

    result = await FlowRunHistoryPurgeRepository(async_session).purge_run_history(
        [run_id]
    )

    assert result.counts.flow_runs_purged == 1
    assert result.counts.flow_runtime_source_bindings_deleted == 1
    assert result.counts.flow_runtime_source_files_deleted == 1
    assert (
        await async_session.scalar(select(FlowRuns.id).where(FlowRuns.id == run_id))
        is None
    )
    assert (
        await async_session.scalar(select(Files.id).where(Files.id == source_file_id))
        is None
    )
    await savepoint.rollback()
    async_session.expunge_all()

    assert await async_session.get(FlowRuns, run_id) is not None
    assert await async_session.get(Files, source_file_id) is not None
    assert await _flow_runtime_upload_exists(
        async_session,
        file_id=source_file_id,
        flow_id=flow_id,
        tenant_id=test_tenant.id,
    )
    assert (
        await _count_for_run(
            async_session,
            FlowRunStepInputFiles,
            run_id=run_id,
        )
        == 1
    )


@pytest.mark.parametrize(
    "claim_expiry_offset_seconds",
    [None, 120, -1],
    ids=["unclaimed", "active-claim", "expired-claim"],
)
@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_keeps_run_with_pending_webhook(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
    claim_expiry_offset_seconds: int | None,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
    )
    now = datetime.now(timezone.utc)
    original_claim_token = await _set_webhook_delivery_pending(
        async_session,
        delivery_id=fixture.webhook_delivery.id,
        now=now,
        claim_expires_at=(
            now + timedelta(seconds=claim_expiry_offset_seconds)
            if claim_expiry_offset_seconds is not None
            else None
        ),
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 0
    assert counts["flow_runs_skipped_unresolved_webhook"] == 1
    assert await async_session.get(FlowRuns, fixture.run.id)
    assert await async_session.get(
        FlowRunWebhookDeliveries,
        fixture.webhook_delivery.id,
    )

    if claim_expiry_offset_seconds is not None:
        claimed = await FlowRunWebhookDeliveryRepository(
            session=async_session
        ).claim_due_delivery_rows(
            now=now,
            limit=10,
            claim_ttl_seconds=120,
        )
        if claim_expiry_offset_seconds > 0:
            assert claimed == []
        else:
            assert [row.id for row in claimed] == [fixture.webhook_delivery.id]
            assert claimed[0].claim_token != original_claim_token


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_purges_run_with_dead_lettered_webhook(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
    )
    await async_session.execute(
        update(FlowRunWebhookDeliveries)
        .where(FlowRunWebhookDeliveries.id == fixture.webhook_delivery.id)
        .values(
            delivery_status=FlowOutboxDeliveryStatus.DEAD_LETTERED.value,
            delivered_at=None,
            dead_lettered_at=datetime.now(timezone.utc),
            delivery_last_error="terminal delivery failure",
        )
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 1
    assert counts["flow_runs_skipped_unresolved_webhook"] == 0
    assert await async_session.get(FlowRuns, fixture.run.id) is None
    assert (
        await async_session.get(
            FlowRunWebhookDeliveries,
            fixture.webhook_delivery.id,
        )
        is None
    )


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_keeps_generated_file_shared_with_retained_run(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
    )
    await _add_younger_flow_runtime_result_file_reference(
        async_session,
        source_run=fixture.run,
        source_step_result=fixture.step_result,
        generated_file=fixture.generated_file,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 1
    assert counts["flow_generated_files_deleted"] == 0
    assert await async_session.get(FlowRuns, fixture.run.id) is None
    assert await async_session.get(Files, fixture.generated_file.id) is not None


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_keeps_generated_file_with_derived_child(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
    )
    child_file = Files(
        name="generated-child.txt",
        text="derived child",
        blob=None,
        checksum=f"generated-child-{uuid4()}",
        size=13,
        mimetype="text/plain",
        file_type="text",
        transcription=None,
        owner_type="user",
        owner_user_id=admin_user.id,
        owner_service_id=None,
        tenant_id=test_tenant.id,
        parent_file_id=fixture.generated_file.id,
    )
    async_session.add(child_file)
    await async_session.flush()

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 1
    assert counts["flow_generated_files_deleted"] == 0
    assert await async_session.get(FlowRuns, fixture.run.id) is None
    assert await async_session.get(Files, fixture.generated_file.id) is not None
    assert await async_session.get(Files, child_file.id) is not None


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_uses_flow_retention_before_space_default(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    flow_retention_space.data_retention_days = 1
    retained_by_flow_override = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=10,
        flow_retention_days=30,
    )
    purged_by_flow_override = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=10,
        flow_retention_days=1,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 1
    assert await async_session.get(FlowRuns, retained_by_flow_override.run.id)
    assert await async_session.get(FlowRuns, purged_by_flow_override.run.id) is None


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_uses_space_default_when_flow_retention_is_null(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    flow_retention_space.data_retention_days = 1
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=None,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 1
    assert counts["debug_step_results"] == 0
    assert await async_session.get(FlowRuns, fixture.run.id) is None


@pytest.mark.asyncio
async def test_flow_run_history_purge_uses_classification_policy_without_flow_or_space_retention(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    await _assign_space_classification_retention_policy(
        async_session,
        tenant_id=test_tenant.id,
        space=flow_retention_space,
        data_retention_days=1,
    )
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=None,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 1
    assert await async_session.get(FlowRuns, fixture.run.id) is None


@pytest.mark.asyncio
async def test_flow_run_history_purge_classification_policy_tightens_flow_retention(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    await _assign_space_classification_retention_policy(
        async_session,
        tenant_id=test_tenant.id,
        space=flow_retention_space,
        data_retention_days=1,
    )
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=365,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 1
    assert await async_session.get(FlowRuns, fixture.run.id) is None


@pytest.mark.asyncio
async def test_flow_run_history_purge_classification_policy_cannot_loosen_flow_retention(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    await _assign_space_classification_retention_policy(
        async_session,
        tenant_id=test_tenant.id,
        space=flow_retention_space,
        data_retention_days=2555,
    )
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=31,
        flow_retention_days=30,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 1
    assert await async_session.get(FlowRuns, fixture.run.id) is None


@pytest.mark.asyncio
async def test_flow_run_history_purge_keeps_classification_policy_when_security_disabled(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    await _assign_space_classification_retention_policy(
        async_session,
        tenant_id=test_tenant.id,
        space=flow_retention_space,
        data_retention_days=1,
    )
    await async_session.execute(
        update(Tenants)
        .where(Tenants.id == test_tenant.id)
        .values(security_enabled=False)
    )
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=None,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 1
    assert await async_session.get(FlowRuns, fixture.run.id) is None


@pytest.mark.asyncio
async def test_flow_run_history_purge_classification_delete_can_loosen_dynamic_policy(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    classification = await _assign_space_classification_retention_policy(
        async_session,
        tenant_id=test_tenant.id,
        space=flow_retention_space,
        data_retention_days=1,
    )
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=None,
    )
    await async_session.execute(
        delete(SecurityClassification).where(
            SecurityClassification.id == classification.id
        )
    )
    await async_session.flush()

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 0
    assert await async_session.get(FlowRuns, fixture.run.id)


@pytest.mark.asyncio
async def test_flow_run_history_purge_uses_space_retention_one_day_boundary(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
    flow_retention_space.data_retention_days = 1
    retained = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=None,
    )
    purged = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=None,
    )
    retained_anchor = now - timedelta(days=1) + timedelta(seconds=1)
    purged_anchor = now - timedelta(days=1)
    retained.run.created_at = retained_anchor
    retained.run.finished_at = retained_anchor
    purged.run.created_at = purged_anchor
    purged.run.finished_at = purged_anchor
    await async_session.flush()

    result = await flow_retention_service.purge_old_flow_run_history_batch(
        now=now,
        limit=10,
    )
    await _flush_and_clear_identity_map(async_session)

    assert result.counts.flow_runs_purged == 1
    assert await async_session.get(FlowRuns, retained.run.id)
    assert await async_session.get(FlowRuns, purged.run.id) is None


@pytest.mark.parametrize(
    "status",
    [
        FlowRunStatus.QUEUED,
        FlowRunStatus.RUNNING,
        FlowRunStatus.AWAITING_REVIEW,
    ],
)
@pytest.mark.asyncio
async def test_flow_run_history_purge_skips_old_non_terminal_runs(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
    status: FlowRunStatus,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=30,
        flow_retention_days=1,
    )
    fixture.run.status = status.value
    fixture.run.finished_at = None
    await async_session.flush()
    source_file_id = fixture.runtime_input_file.id
    run_id = fixture.run.id
    flow_id = fixture.flow.id

    counts = await flow_retention_service.purge_old_flow_run_history_batch(
        now=datetime.now(timezone.utc),
        limit=10,
    )
    await _flush_and_clear_identity_map(async_session)

    assert counts.counts == FlowRunHistoryPurgeCounts()
    assert await async_session.get(FlowRuns, run_id)
    assert await async_session.get(Files, source_file_id)
    assert await _flow_runtime_upload_exists(
        async_session,
        file_id=source_file_id,
        flow_id=flow_id,
        tenant_id=test_tenant.id,
    )
    assert (
        await _count_for_run(
            async_session,
            FlowRunStepInputFiles,
            run_id=run_id,
        )
        == 1
    )


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_keeps_runs_without_flow_or_space_retention(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=30,
        flow_retention_days=None,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 0
    assert await async_session.get(FlowRuns, fixture.run.id)


@pytest.mark.parametrize(
    "delivery_status",
    [
        FlowOutboxDeliveryStatus.PENDING.value,
        FlowOutboxDeliveryStatus.DEAD_LETTERED.value,
    ],
)
@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_skips_runs_with_undelivered_audit_outbox(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
    delivery_status: str,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
    )
    await _add_flow_audit_outbox_row(
        async_session,
        run=fixture.run,
        user_id=admin_user.id,
        delivery_status=delivery_status,
        with_audit_log=False,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 0
    assert counts["flow_runs_skipped_undelivered_audit"] == 1
    assert await async_session.get(FlowRuns, fixture.run.id)
    assert await async_session.get(FlowStepResults, fixture.step_result.id)


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_paginates_purge_candidates_with_skips(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(data_retention_service_module, "RETENTION_BATCH_SIZE", 2)
    purge_first = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
        run_id=UUID("00000000-0000-0000-0000-000000000001"),
    )
    skipped = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
        run_id=UUID("00000000-0000-0000-0000-000000000002"),
    )
    purge_second = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
        run_id=UUID("00000000-0000-0000-0000-000000000003"),
    )
    purge_third = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
        run_id=UUID("00000000-0000-0000-0000-000000000004"),
    )
    await _add_flow_audit_outbox_row(
        async_session,
        run=skipped.run,
        user_id=admin_user.id,
        delivery_status=FlowOutboxDeliveryStatus.PENDING.value,
        with_audit_log=False,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 3
    assert counts["flow_runs_skipped_undelivered_audit"] == 1
    assert await async_session.get(FlowRuns, purge_first.run.id) is None
    assert await async_session.get(FlowRuns, purge_second.run.id) is None
    assert await async_session.get(FlowRuns, purge_third.run.id) is None
    assert await async_session.get(FlowRuns, skipped.run.id) is not None


@pytest.mark.asyncio
async def test_purge_old_flow_run_history_batch_drains_only_eligible_runs(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    purge_first = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
        run_id=UUID("00000000-0000-0000-0000-000000000101"),
    )
    skipped = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
        run_id=UUID("00000000-0000-0000-0000-000000000102"),
    )
    purge_second = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
        run_id=UUID("00000000-0000-0000-0000-000000000103"),
    )
    await _add_flow_audit_outbox_row(
        async_session,
        run=skipped.run,
        user_id=admin_user.id,
        delivery_status=FlowOutboxDeliveryStatus.PENDING.value,
        with_audit_log=False,
    )

    now = datetime.now(timezone.utc)
    first_batch = await flow_retention_service.purge_old_flow_run_history_batch(
        now=now,
        limit=1,
    )
    second_batch = await flow_retention_service.purge_old_flow_run_history_batch(
        now=now,
        limit=1,
    )
    drained_batch = await flow_retention_service.purge_old_flow_run_history_batch(
        now=now,
        limit=1,
    )
    blocked_counts = (
        await flow_retention_service.count_blocked_flow_run_history_purge_candidates(
            now=now,
        )
    )
    await _flush_and_clear_identity_map(async_session)

    assert first_batch.counts.flow_runs_purged == 1
    assert second_batch.counts.flow_runs_purged == 1
    assert drained_batch.counts.flow_runs_purged == 0
    assert blocked_counts.skipped_undelivered_audit == 1
    assert blocked_counts.skipped_active_rerun == 0
    assert await async_session.get(FlowRuns, purge_first.run.id) is None
    assert await async_session.get(FlowRuns, purge_second.run.id) is None
    assert await async_session.get(FlowRuns, skipped.run.id) is not None


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_skips_terminal_runs_with_active_rerun_operation(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
    )
    await _add_active_rerun_operation(
        async_session,
        fixture=fixture,
        user_id=admin_user.id,
        status=FlowRunRerunOperationStatus.QUEUED,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 0
    assert counts["flow_runs_skipped_active_rerun"] == 1
    assert await async_session.get(FlowRuns, fixture.run.id)


@pytest.mark.asyncio
async def test_flow_run_history_purge_rechecks_active_rerun_before_cascade(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
    )
    await _add_active_rerun_operation(
        async_session,
        fixture=fixture,
        user_id=admin_user.id,
        status=FlowRunRerunOperationStatus.QUEUED,
    )

    result = await FlowRunHistoryPurgeRepository(async_session).purge_run_history(
        [fixture.run.id]
    )

    assert result.counts == FlowRunHistoryPurgeCounts(flow_runs_considered=1)
    assert result.affected_flow_tenant_ids == frozenset()
    assert await async_session.get(FlowRuns, fixture.run.id)
    assert await async_session.get(Files, fixture.runtime_input_file.id)
    assert await _flow_runtime_upload_exists(
        async_session,
        file_id=fixture.runtime_input_file.id,
        flow_id=fixture.flow.id,
        tenant_id=test_tenant.id,
    )


@pytest.mark.asyncio
async def test_flow_run_history_blocked_counts_use_audit_webhook_rerun_precedence(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    audit_blocked = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
    )
    webhook_blocked = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
    )
    now = datetime.now(timezone.utc)
    for fixture in (audit_blocked, webhook_blocked):
        await _set_webhook_delivery_pending(
            async_session,
            delivery_id=fixture.webhook_delivery.id,
            now=now,
            claim_expires_at=None,
        )
        await _add_active_rerun_operation(
            async_session,
            fixture=fixture,
            user_id=admin_user.id,
        )
    await _add_flow_audit_outbox_row(
        async_session,
        run=audit_blocked.run,
        user_id=admin_user.id,
        delivery_status=FlowOutboxDeliveryStatus.PENDING.value,
        with_audit_log=False,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 0
    assert counts["flow_runs_skipped_undelivered_audit"] == 1
    assert counts["flow_runs_skipped_unresolved_webhook"] == 1
    assert counts["flow_runs_skipped_active_rerun"] == 0
    assert await async_session.get(FlowRuns, audit_blocked.run.id)
    assert await async_session.get(FlowRuns, webhook_blocked.run.id)


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_purges_soft_deleted_flow_run_history(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_retention_days=1,
        flow_deleted=True,
    )

    result = await flow_retention_service.purge_old_flow_run_history_batch(
        now=datetime.now(timezone.utc),
        limit=10,
    )
    await _flush_and_clear_identity_map(async_session)

    assert result.counts.flow_runs_purged == 1
    assert result.counts.flow_runtime_source_files_deleted == 1
    assert result.affected_flow_tenant_ids == frozenset(
        {(fixture.flow.id, test_tenant.id)}
    )
    assert await async_session.get(Flows, fixture.flow.id)
    assert await async_session.get(FlowRuns, fixture.run.id) is None
    assert await async_session.get(Files, fixture.runtime_input_file.id) is None


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_redacts_tenant_debug_before_later_flow_purge(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=10,
        flow_retention_days=30,
        flow_settings={
            "retention_policy": {
                "run_debug_evidence_days": 7,
            }
        },
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["flow_runs_purged"] == 0
    assert counts["debug_step_results"] == 1
    assert counts["debug_step_attempts"] == 1

    refreshed_run = await async_session.get(FlowRuns, fixture.run.id)
    refreshed_step_result = await async_session.get(
        FlowStepResults, fixture.step_result.id
    )
    refreshed_attempt = await async_session.get(
        FlowStepAttempts, fixture.step_attempt.id
    )

    assert refreshed_run is not None
    assert refreshed_step_result is not None
    assert refreshed_step_result.input_payload_json is None
    assert refreshed_step_result.effective_prompt is None
    assert refreshed_step_result.model_parameters_json is None
    assert refreshed_step_result.output_payload_json is not None
    assert refreshed_step_result.output_payload_json["text"] == "kept output"
    tombstones = extract_retention_tombstones(refreshed_step_result.output_payload_json)
    assert [item.retention_state for item in tombstones] == ["retention_purged"]
    assert {item.actor_source for item in tombstones} == {FLOW_RETENTION_ACTOR_SOURCE}
    assert {item.tenant_id for item in tombstones} == {str(test_tenant.id)}
    assert {item.run_id for item in tombstones} == {str(fixture.run.id)}
    assert {item.trace_id for item in tombstones} == {str(fixture.run.trace_id)}
    assert refreshed_attempt is not None
    attempt_marker = FlowAttemptRetentionMarker.model_validate(
        refreshed_attempt.provenance_json
    )
    assert attempt_marker.status == "retention_purged"
    assert attempt_marker.tombstone.actor_source == FLOW_RETENTION_ACTOR_SOURCE
    assert attempt_marker.tombstone.object_id == str(fixture.step_attempt.id)
    assert isinstance(attempt_marker.tombstone.counts, RunDebugAttemptRetentionCounts)
    assert attempt_marker.tombstone.counts.cleared_field_count == 3
    assert refreshed_attempt.input_payload_json is None
    assert refreshed_attempt.output_payload_json is None


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_redacts_attempt_payloads_without_provenance(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=10,
        flow_retention_days=30,
        flow_settings={
            "retention_policy": {
                "run_debug_evidence_days": 7,
            }
        },
    )
    fixture.step_attempt.provenance_json = None
    await async_session.flush()

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    assert counts["debug_step_attempts"] == 1
    refreshed_attempt = await async_session.get(
        FlowStepAttempts, fixture.step_attempt.id
    )
    assert refreshed_attempt is not None
    assert refreshed_attempt.input_payload_json is None
    assert refreshed_attempt.output_payload_json is None
    attempt_marker = FlowAttemptRetentionMarker.model_validate(
        refreshed_attempt.provenance_json
    )
    assert isinstance(attempt_marker.tombstone.counts, RunDebugAttemptRetentionCounts)
    assert attempt_marker.tombstone.counts.cleared_field_count == 2


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_does_not_redact_from_flow_retention_before_purge_horizon(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    fixture = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=10,
        flow_retention_days=30,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await _flush_and_clear_identity_map(async_session)

    refreshed_step_result = await async_session.get(
        FlowStepResults, fixture.step_result.id
    )
    refreshed_attempt = await async_session.get(
        FlowStepAttempts, fixture.step_attempt.id
    )

    assert counts["flow_runs_purged"] == 0
    assert counts["debug_step_results"] == 0
    assert counts["debug_step_attempts"] == 0
    assert refreshed_step_result is not None
    assert refreshed_step_result.input_payload_json == {"text": "sensitive input"}
    assert refreshed_step_result.effective_prompt == "Very sensitive prompt"
    assert refreshed_step_result.model_parameters_json == {"temperature": 0.1}
    assert refreshed_attempt is not None
    assert refreshed_attempt.provenance_json == {"artifacts": {"items": ["debug"]}}
    assert refreshed_attempt.input_payload_json == {"text": "sensitive attempt input"}
    assert refreshed_attempt.output_payload_json == {"text": "sensitive attempt output"}


@pytest.mark.asyncio
async def test_delete_old_delivered_flow_audit_outbox_rows_follows_audit_log_lifetime(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    async def create_outbox_row(*, delivery_status: str, with_audit_log: bool):
        fixture = await _create_flow_runtime_fixture(
            async_session,
            tenant=test_tenant,
            user=admin_user,
            space=flow_retention_space,
            assistant=flow_retention_assistant,
            days_old=3,
            generated_file_has_content=False,
        )
        return await _add_flow_audit_outbox_row(
            async_session,
            run=fixture.run,
            user_id=admin_user.id,
            delivery_status=delivery_status,
            with_audit_log=with_audit_log,
        )

    orphaned_delivered_id = await create_outbox_row(
        delivery_status=FlowOutboxDeliveryStatus.DELIVERED.value,
        with_audit_log=False,
    )
    delivered_with_audit_id = await create_outbox_row(
        delivery_status=FlowOutboxDeliveryStatus.DELIVERED.value,
        with_audit_log=True,
    )
    pending_id = await create_outbox_row(
        delivery_status=FlowOutboxDeliveryStatus.PENDING.value,
        with_audit_log=False,
    )
    dead_lettered_id = await create_outbox_row(
        delivery_status=FlowOutboxDeliveryStatus.DEAD_LETTERED.value,
        with_audit_log=False,
    )

    deleted = await flow_retention_service.delete_old_delivered_flow_audit_outbox_rows()
    await async_session.flush()

    assert deleted == 1
    assert await async_session.get(FlowRunAuditOutbox, orphaned_delivered_id) is None
    assert await async_session.get(FlowRunAuditOutbox, delivered_with_audit_id)
    assert await async_session.get(FlowRunAuditOutbox, pending_id)
    assert await async_session.get(FlowRunAuditOutbox, dead_lettered_id)

    second_deleted = (
        await flow_retention_service.delete_old_delivered_flow_audit_outbox_rows()
    )
    assert second_deleted == 0

    await async_session.execute(
        delete(AuditLogTable).where(AuditLogTable.id == delivered_with_audit_id)
    )
    deleted_after_audit_retention = (
        await flow_retention_service.delete_old_delivered_flow_audit_outbox_rows()
    )
    await async_session.flush()

    assert deleted_after_audit_retention == 1
    assert await async_session.get(FlowRunAuditOutbox, delivered_with_audit_id) is None
    assert await async_session.get(FlowRunAuditOutbox, pending_id)
    assert await async_session.get(FlowRunAuditOutbox, dead_lettered_id)


@pytest.mark.asyncio
async def test_delete_old_delivered_flow_audit_outbox_rows_uses_retention_batches(
    monkeypatch: pytest.MonkeyPatch,
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    monkeypatch.setattr(
        "eneo.data_retention.infrastructure.data_retention_service.RETENTION_BATCH_SIZE",
        2,
    )
    outbox_ids = []
    for _ in range(3):
        fixture = await _create_flow_runtime_fixture(
            async_session,
            tenant=test_tenant,
            user=admin_user,
            space=flow_retention_space,
            assistant=flow_retention_assistant,
            days_old=3,
            generated_file_has_content=False,
        )
        outbox_ids.append(
            await _add_flow_audit_outbox_row(
                async_session,
                run=fixture.run,
                user_id=admin_user.id,
                delivery_status=FlowOutboxDeliveryStatus.DELIVERED.value,
                with_audit_log=False,
            )
        )

    deleted = await flow_retention_service.delete_old_delivered_flow_audit_outbox_rows()
    remaining = await async_session.scalar(
        select(func.count())
        .select_from(FlowRunAuditOutbox)
        .where(FlowRunAuditOutbox.id.in_(outbox_ids))
    )

    assert deleted == 3
    assert remaining == 0
