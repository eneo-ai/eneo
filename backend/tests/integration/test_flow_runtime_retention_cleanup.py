from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from intric.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
)
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.files_table import Files
from intric.database.tables.flow_tables import (
    FlowRuns,
    Flows,
    FlowStepAttempts,
    FlowStepResults,
    FlowVersions,
)
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants


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
        published_version=1,
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
        owner_api_key_id=None,
        user_id=user.id,
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
        principal_api_key_id=None,
        user_id=user.id,
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
        error_message=None,
        job_id=None,
        created_at=created_at,
        updated_at=created_at,
    )
    async_session.add(run)
    await async_session.flush()

    step_result = FlowStepResults(
        flow_run_id=run.id,
        flow_id=flow.id,
        tenant_id=tenant.id,
        step_id=None,
        step_order=1,
        assistant_id=assistant.id,
        input_payload_json={"text": "sensitive input"},
        effective_prompt="Very sensitive prompt",
        output_payload_json={
            "text": "kept output",
            "webhook_delivered": False,
            "generated_file_ids": [str(generated_file.id)],
            "file_ids": [str(generated_file.id)],
            "artifacts": [
                {"file_id": str(generated_file.id), "name": generated_file.name}
            ],
            "template_fill_debug": {"rendered_docx_text_raw": "debug body"},
        },
        model_parameters_json={"temperature": 0.1},
        num_tokens_input=10,
        num_tokens_output=20,
        status="completed",
        error_message=None,
        flow_step_execution_hash=None,
        tool_calls_metadata={"count": 1},
        started_at=created_at,
        finished_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )
    async_session.add(step_result)

    step_attempt = FlowStepAttempts(
        flow_run_id=run.id,
        flow_id=flow.id,
        tenant_id=tenant.id,
        step_id=None,
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


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_clears_debug_evidence_and_generated_artifacts(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    (
        _run,
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
                "generated_artifact_days": 1,
            }
        },
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await async_session.flush()

    assert counts == {
        "debug_step_results": 1,
        "debug_step_attempts": 1,
        "generated_artifact_rows": 1,
        "generated_artifact_files": 1,
        "reconciled_artifact_references": 0,
    }

    refreshed_step_result = await async_session.get(FlowStepResults, step_result.id)
    refreshed_attempt = await async_session.get(FlowStepAttempts, step_attempt.id)
    refreshed_file = await async_session.get(Files, generated_file.id)

    assert refreshed_step_result is not None
    assert refreshed_step_result.input_payload_json is None
    assert refreshed_step_result.effective_prompt is None
    assert refreshed_step_result.model_parameters_json is None
    assert refreshed_step_result.tool_calls_metadata is None
    assert refreshed_step_result.output_payload_json == {
        "text": "kept output",
        "webhook_delivered": False,
    }
    assert refreshed_attempt is not None
    assert refreshed_attempt.provenance_json is None
    assert refreshed_file is not None
    assert refreshed_file.blob is None
    assert refreshed_file.text is None
    assert refreshed_file.transcription is None


@pytest.mark.asyncio
async def test_cleanup_old_flow_runtime_data_reconciles_missing_generated_artifact_references(
    async_session: AsyncSession,
    test_tenant,
    admin_user,
    flow_retention_space: Spaces,
    flow_retention_assistant: Assistants,
    flow_retention_service: DataRetentionService,
):
    _run, step_result, _attempt, _generated_file = await _create_flow_runtime_fixture(
        async_session,
        tenant=test_tenant,
        user=admin_user,
        space=flow_retention_space,
        assistant=flow_retention_assistant,
        days_old=0,
        flow_settings={},
        generated_file_has_content=False,
    )

    counts = await flow_retention_service.cleanup_old_flow_runtime_data()
    await async_session.flush()

    assert counts == {
        "debug_step_results": 0,
        "debug_step_attempts": 0,
        "generated_artifact_rows": 0,
        "generated_artifact_files": 0,
        "reconciled_artifact_references": 1,
    }

    refreshed_step_result = await async_session.get(FlowStepResults, step_result.id)
    assert refreshed_step_result is not None
    assert refreshed_step_result.output_payload_json == {
        "text": "kept output",
        "webhook_delivered": False,
        "template_fill_debug": {"rendered_docx_text_raw": "debug body"},
    }
