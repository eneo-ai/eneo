from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from intric.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
)
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.audit_log_table import AuditLog as AuditLogTable
from intric.database.tables.files_table import Files
from intric.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
    FlowRuns,
    FlowRunStepResultFiles,
    Flows,
    FlowStepAttempts,
    FlowStepResults,
    FlowSteps,
    FlowVersions,
)
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants
from intric.flows.flow_retention_tombstone import (
    FLOW_RETENTION_ACTOR_SOURCE,
    FlowAttemptRetentionMarker,
    RunDebugAttemptRetentionCounts,
    extract_retention_tombstones,
)


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
):
    if flow_settings is not None:
        await async_session.execute(
            update(Tenants)
            .where(Tenants.id == tenant.id)
            .values(flow_settings=flow_settings)
        )
        await async_session.flush()

    created_at = datetime.now(timezone.utc) - timedelta(days=days_old)
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

    run = FlowRuns(
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

    step_id = uuid4()
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
            output_mode="pass_through",
            output_type="docx",
            mcp_policy="inherit",
            created_at=created_at,
            updated_at=created_at,
        )
    )
    await async_session.flush()
    output_payload_json = {
        "text": "kept output",
        "webhook_delivered": False,
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
        started_at=created_at,
        finished_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )
    async_session.add(step_attempt)
    await async_session.flush()

    return run, step_result, step_attempt, generated_file


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


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_clears_debug_evidence_and_preserves_generated_artifact_content(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    (
        run,
        step_result,
        step_attempt,
        generated_file,
    ) = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_settings={
            "retention_policy": {
                "run_debug_evidence_days": 1,
            }
        },
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await async_session.flush()

    assert counts == {
        "debug_step_results": 1,
        "debug_step_attempts": 1,
        "generated_artifact_rows": 0,
        "generated_artifact_files": 0,
        "reconciled_artifact_references": 0,
    }

    refreshed_step_result = await async_session.get(FlowStepResults, step_result.id)
    refreshed_attempt = await async_session.get(FlowStepAttempts, step_attempt.id)
    refreshed_file = await async_session.get(Files, generated_file.id)

    assert refreshed_step_result is not None
    assert refreshed_step_result.input_payload_json is None
    assert refreshed_step_result.effective_prompt is None
    assert refreshed_step_result.model_parameters_json is None
    assert refreshed_step_result.output_payload_json is not None
    assert refreshed_step_result.output_payload_json["text"] == "kept output"
    assert refreshed_step_result.output_payload_json["webhook_delivered"] is False
    tombstones = extract_retention_tombstones(refreshed_step_result.output_payload_json)
    assert [item.retention_state for item in tombstones] == ["retention_purged"]
    assert {item.actor_source for item in tombstones} == {FLOW_RETENTION_ACTOR_SOURCE}
    assert {item.tenant_id for item in tombstones} == {str(test_tenant.id)}
    assert {item.run_id for item in tombstones} == {str(run.id)}
    assert {item.trace_id for item in tombstones} == {str(run.trace_id)}
    assert refreshed_attempt is not None
    attempt_marker = FlowAttemptRetentionMarker.model_validate(
        refreshed_attempt.provenance_json
    )
    assert attempt_marker.status == "retention_purged"
    assert attempt_marker.tombstone.actor_source == FLOW_RETENTION_ACTOR_SOURCE
    assert attempt_marker.tombstone.object_id == str(step_attempt.id)
    assert isinstance(attempt_marker.tombstone.counts, RunDebugAttemptRetentionCounts)
    assert attempt_marker.tombstone.counts.cleared_field_count == 1
    assert refreshed_file is not None
    assert refreshed_file.blob == b"docx-bytes"
    assert refreshed_file.text is None
    assert refreshed_file.transcription is None

    second_counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await async_session.flush()

    assert second_counts == {
        "debug_step_results": 0,
        "debug_step_attempts": 0,
        "generated_artifact_rows": 0,
        "generated_artifact_files": 0,
        "reconciled_artifact_references": 0,
    }


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_ignores_stale_generated_artifact_policy_without_payload_refs(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    run, step_result, _attempt, generated_file = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_settings={
            "retention_policy": {
                "generated_artifact_days": 1,
            }
        },
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await async_session.flush()

    assert counts == {
        "debug_step_results": 0,
        "debug_step_attempts": 0,
        "generated_artifact_rows": 0,
        "generated_artifact_files": 0,
        "reconciled_artifact_references": 0,
    }

    refreshed_step_result = await async_session.get(FlowStepResults, step_result.id)
    refreshed_file = await async_session.get(Files, generated_file.id)
    assert refreshed_step_result is not None
    payload = refreshed_step_result.output_payload_json
    assert isinstance(payload, dict)
    assert set(payload) == {
        "text",
        "webhook_delivered",
        "template_fill_debug",
    }
    assert payload["text"] == "kept output"
    assert payload["webhook_delivered"] is False
    assert payload["template_fill_debug"] == {"rendered_docx_text_raw": "debug body"}
    assert extract_retention_tombstones(payload) == ()
    assert "artifact_content_purged" not in str(payload)
    assert refreshed_file is not None
    assert refreshed_file.blob == b"docx-bytes"
    assert refreshed_file.text is None
    assert refreshed_file.transcription is None


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_ignores_stale_generated_artifact_policy_with_younger_flow_reference(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    run, step_result, _attempt, generated_file = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=3,
        flow_settings={
            "retention_policy": {
                "generated_artifact_days": 1,
            }
        },
    )
    await _add_younger_flow_runtime_result_file_reference(
        async_session,
        source_run=run,
        source_step_result=step_result,
        generated_file=generated_file,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await async_session.flush()

    assert counts == {
        "debug_step_results": 0,
        "debug_step_attempts": 0,
        "generated_artifact_rows": 0,
        "generated_artifact_files": 0,
        "reconciled_artifact_references": 0,
    }

    refreshed_step_result = await async_session.get(FlowStepResults, step_result.id)
    refreshed_file = await async_session.get(Files, generated_file.id)
    assert refreshed_step_result is not None
    assert refreshed_step_result.output_payload_json is not None
    assert "artifact_content_purged" not in str(
        refreshed_step_result.output_payload_json
    )
    assert extract_retention_tombstones(refreshed_step_result.output_payload_json) == ()
    assert refreshed_file is not None
    assert refreshed_file.blob == b"docx-bytes"
    assert refreshed_file.text is None
    assert refreshed_file.transcription is None


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
        run, _step_result, _attempt, _file = await _create_flow_runtime_fixture(
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
            run=run,
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
        "intric.data_retention.infrastructure.data_retention_service.RETENTION_BATCH_SIZE",
        2,
    )
    outbox_ids = []
    for _ in range(3):
        run, _step_result, _attempt, _file = await _create_flow_runtime_fixture(
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
                run=run,
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
