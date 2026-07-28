from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_flow_run_service import (
    _file_repo,
    _flow,
    _flow_repo,
    _provider_call_repo,
    _run,
    _step_result_record,
    _trace_user,
    _version,
)

from eneo.database.tables.flow_tables import FlowOutboxDeliveryStatus
from eneo.files.file_models import FileType
from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_run_evidence_service import (
    EMBEDDED_PROVIDER_CALL_LIMIT,
    PROVIDER_CALL_EXPORT_MAX_EVENTS,
    FlowRunEvidenceService,
)
from eneo.flows.domain.provider_call import (
    ProviderCallEvidence,
    ProviderCallEvidencePage,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_step_input_file import FlowRunStepInputFileMetadata
from eneo.flows.infrastructure.flow_run_rerun_repo import FlowRunRerunRepository
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRead,
    FlowRunWebhookDeliveryRepository,
)
from eneo.flows.published_definition import published_definition_checksum
from eneo.main.exceptions import FileTooLargeException, UnauthorizedException


def _flow_run_rerun_repo() -> AsyncMock:
    repo = AsyncMock(spec=FlowRunRerunRepository)
    repo.list_rerun_operations_for_run.return_value = []
    repo.list_rerun_invalidated_steps_for_run.return_value = []
    return repo


def _webhook_delivery_repo() -> AsyncMock:
    repo = AsyncMock(spec=FlowRunWebhookDeliveryRepository)
    repo.list_run_delivery_statuses.return_value = []
    return repo


def _provider_call_evidence() -> ProviderCallEvidence:
    now = datetime.now(timezone.utc)
    return ProviderCallEvidence(
        event_id=uuid4(),
        attempt_id=uuid4(),
        step_id=uuid4(),
        step_order=1,
        attempt_no=1,
        ordinal=1,
        status="completed",
        request_schema_version=2,
        provider_request_hash="a" * 64,
        requested_model="openai/gpt-4o-mini",
        provider="openai",
        response_format="json_schema",
        requested_capabilities=("structured_output",),
        call_reason="initial",
        mapped_execution_mode=None,
        mapped_item_index=None,
        mapped_source_index=None,
        mapped_source_id=None,
        response_model="gpt-4o-mini-2026-07-01",
        provider_response_id="response-1",
        num_tokens_input=12,
        num_tokens_output=None,
        input_source="provider",
        output_source="not_reported",
        outcome_reason=None,
        requested_at=now,
        finished_at=now,
    )


def _service_for_empty_run(
    *,
    user,
    provider_call_repo: AsyncMock,
    access_policy: AsyncMock | None = None,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow = _flow(user=user)
    run = _run(user=user, flow_id=flow.id)
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    flow_run_repo.list_result_files.return_value = []
    flow_version_repo = AsyncMock()
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    review_checkpoint_repo = AsyncMock()
    review_checkpoint_repo.list_review_checkpoints_for_run.return_value = []
    resolved_access_policy = access_policy or AsyncMock(spec=FlowRunAccessPolicy)
    resolved_access_policy.load_run.return_value = run
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        provider_call_repo=provider_call_repo,
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
        access_policy=resolved_access_policy,
    )
    return service, run


@pytest.mark.asyncio
async def test_evidence_embeds_first_bounded_provider_call_page(user):
    user = _trace_user(user)
    provider_call_repo = _provider_call_repo()
    event = _provider_call_evidence()
    page = ProviderCallEvidencePage(
        items=(event,),
        count=1,
        total_count=2,
        has_more=True,
        next_after_event_id=event.event_id,
    )
    provider_call_repo.list_evidence_page.return_value = page
    service, run = _service_for_empty_run(
        user=user,
        provider_call_repo=provider_call_repo,
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

    assert evidence["provider_calls"] == page.model_dump(mode="json")
    provider_call_repo.list_evidence_page.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        limit=EMBEDDED_PROVIDER_CALL_LIMIT,
    )


@pytest.mark.asyncio
async def test_list_provider_calls_authorizes_run_and_forwards_page_cursor(user):
    user = _trace_user(user)
    provider_call_repo = _provider_call_repo()
    access_policy = AsyncMock(spec=FlowRunAccessPolicy)
    service, run = _service_for_empty_run(
        user=user,
        provider_call_repo=provider_call_repo,
        access_policy=access_policy,
    )
    after_event_id = uuid4()
    attempt_id = uuid4()

    page = await service.list_provider_calls(
        run_id=run.id,
        flow_id=run.flow_id,
        limit=375,
        after_event_id=after_event_id,
        attempt_id=attempt_id,
        run=run,
    )

    assert page.total_count == 0
    access_policy.ensure_can_access_run.assert_awaited_once_with(
        run,
        access_kind="evidence_view",
    )
    provider_call_repo.list_evidence_page.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        limit=375,
        after_event_id=after_event_id,
        attempt_id=attempt_id,
    )


@pytest.mark.asyncio
async def test_export_v13_hash_covers_all_provider_call_events(user):
    user = _trace_user(user)
    provider_call_repo = _provider_call_repo()
    event = _provider_call_evidence()
    service, run = _service_for_empty_run(
        user=user,
        provider_call_repo=provider_call_repo,
    )
    provider_call_repo.list_evidence_page.return_value = ProviderCallEvidencePage(
        items=(event,),
        count=1,
        total_count=1,
        has_more=False,
        next_after_event_id=None,
    )

    export_with_event = await service.export_evidence_json(run_id=run.id)
    provider_call_repo.list_evidence_page.return_value = ProviderCallEvidencePage(
        items=(event.model_copy(update={"requested_capabilities": ()}),),
        count=1,
        total_count=1,
        has_more=False,
        next_after_event_id=None,
    )
    export_without_capability = await service.export_evidence_json(run_id=run.id)
    provider_call_repo.list_evidence_page.return_value = ProviderCallEvidencePage(
        items=(),
        count=0,
        total_count=0,
        has_more=False,
        next_after_event_id=None,
    )
    export_without_event = await service.export_evidence_json(run_id=run.id)

    assert export_with_event["schema_version"] == "flow-evidence-export.v13"
    assert export_with_event["bundle"]["provider_calls"]["items"][0]["event_id"] == str(
        event.event_id
    )
    assert (
        export_with_event["content_hash"] != export_without_capability["content_hash"]
    )
    assert export_with_event["content_hash"] != export_without_event["content_hash"]
    assert all(
        call.kwargs["limit"] == PROVIDER_CALL_EXPORT_MAX_EVENTS + 1
        for call in provider_call_repo.list_evidence_page.await_args_list
    )


@pytest.mark.asyncio
async def test_export_rejects_more_than_provider_call_safety_boundary(user):
    user = _trace_user(user)
    provider_call_repo = _provider_call_repo()
    provider_call_repo.list_evidence_page.return_value = ProviderCallEvidencePage(
        items=(),
        count=0,
        total_count=PROVIDER_CALL_EXPORT_MAX_EVENTS + 1,
        has_more=True,
        next_after_event_id=uuid4(),
    )
    service, run = _service_for_empty_run(
        user=user,
        provider_call_repo=provider_call_repo,
    )

    with pytest.raises(FileTooLargeException) as exc_info:
        await service.export_evidence_json(run_id=run.id)

    assert exc_info.value.code == FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE.value
    assert exc_info.value.context == {
        "provider_call_count": PROVIDER_CALL_EXPORT_MAX_EVENTS + 1,
        "max_provider_call_events": PROVIDER_CALL_EXPORT_MAX_EVENTS,
    }
    # The hint may only name recovery paths that exist. There is no offline or
    # asynchronous export surface to send a caller to.
    docs_hint = exc_info.value.docs_hint or ""
    assert "provider-calls" in docs_hint
    assert "offline" not in docs_hint.lower()
    assert "administrator" not in docs_hint.lower()


@pytest.mark.asyncio
async def test_evidence_exports_identical_safe_webhook_delivery_metadata(user):
    user = _trace_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = _flow_run_rerun_repo()
    review_checkpoint_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    webhook_delivery_repo = _webhook_delivery_repo()
    access_policy = AsyncMock(spec=FlowRunAccessPolicy)
    flow = _flow(user=user)
    run = _run(user=user, flow_id=flow.id)
    access_policy.load_run.return_value = run
    now = datetime.now(timezone.utc)
    delivery = FlowRunWebhookDeliveryRead(
        id=uuid4(),
        step_id=uuid4(),
        step_order=2,
        attempt_no=1,
        delivery_status=FlowOutboxDeliveryStatus.DEAD_LETTERED,
        delivery_attempts=5,
        next_delivery_at=None,
        delivered_at=None,
        dead_lettered_at=now,
        created_at=now,
        updated_at=now,
    )
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    review_checkpoint_repo.list_review_checkpoints_for_run.return_value = []
    flow_run_repo.list_result_files.return_value = []
    flow_run_repo.list_current_step_input_file_metadata_by_step_result_id.return_value = {}
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    webhook_delivery_repo.list_run_delivery_statuses.return_value = [delivery]
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        provider_call_repo=_provider_call_repo(),
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_run_review_checkpoint_repo=review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=webhook_delivery_repo,
        access_policy=access_policy,
    )

    redacted = await service.export_evidence_json(run_id=run.id)
    raw = await service.export_evidence_json(
        run_id=run.id,
        detail="raw",
        export_reason="delivery-audit",
    )

    expected = {
        "id": str(delivery.id),
        "step_id": str(delivery.step_id),
        "step_order": 2,
        "attempt_no": 1,
        "delivery_status": "dead_lettered",
        "delivery_attempts": 5,
        "next_delivery_at": None,
        "delivered_at": None,
        "dead_lettered_at": now.isoformat(),
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    assert redacted["bundle"]["webhook_deliveries"] == [expected]
    assert raw["bundle"]["webhook_deliveries"] == [expected]
    assert "idempotency_key" not in expected
    assert "payload_ref" not in expected
    assert "delivery_last_error" not in expected
    assert "claim_token" not in expected
    webhook_delivery_repo.list_run_delivery_statuses.assert_awaited_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
async def test_get_evidence_loads_run_through_access_policy(user):
    user = _trace_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = _flow_run_rerun_repo()
    review_checkpoint_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    run = _run(user=user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    review_checkpoint_repo.list_review_checkpoints_for_run.return_value = []
    flow_run_repo.list_result_files.return_value = []
    flow_run_repo.list_current_step_input_file_metadata_by_step_result_id.return_value = {}
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        provider_call_repo=_provider_call_repo(),
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_run_review_checkpoint_repo=review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

    assert evidence["run"]["id"] == str(run.id)
    flow_run_repo.get.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        flow_id=None,
    )


@pytest.mark.asyncio
async def test_get_evidence_preserves_corrupt_snapshot_with_integrity_status(user):
    user = _trace_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = _flow_run_rerun_repo()
    review_checkpoint_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    run = _run(user=user, flow_id=flow.id)
    version = _version(user=user, flow=flow, version=run.flow_version).model_copy(
        update={"definition_checksum": "stored-checksum-does-not-match"}
    )
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    review_checkpoint_repo.list_review_checkpoints_for_run.return_value = []
    flow_run_repo.list_result_files.return_value = []
    flow_version_repo.get.return_value = version
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        provider_call_repo=_provider_call_repo(),
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_run_review_checkpoint_repo=review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

    assert evidence["definition_snapshot"] == version.definition_json
    assert evidence["definition_integrity"] == {
        "status": "invalid",
        "expected_checksum": "stored-checksum-does-not-match",
        "current_checksum": published_definition_checksum(version.definition_json),
    }
    flow_version_repo.get.assert_awaited_once_with(
        flow_id=run.flow_id,
        version=run.flow_version,
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
async def test_get_evidence_populates_runtime_input_file_metadata_from_repo(user):
    user = _trace_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = _flow_run_rerun_repo()
    review_checkpoint_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    run = _run(user=user, flow_id=flow.id)
    stale_payload_file_id = uuid4()
    relational_file_id = uuid4()
    result = _step_result_record(
        run,
        step_order=1,
        input_payload_json={
            "runtime_input": {
                "file_ids": [str(stale_payload_file_id)],
                "files_count": 1,
            }
        },
    )
    assert result.id is not None
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = [result]
    flow_run_repo.list_step_attempts.return_value = []
    review_checkpoint_repo.list_review_checkpoints_for_run.return_value = []
    flow_run_repo.list_result_files.return_value = []
    flow_run_repo.list_current_step_input_file_metadata_by_step_result_id.return_value = {
        result.id: (
            FlowRunStepInputFileMetadata(
                file_id=relational_file_id,
                name="relational.pdf",
                checksum="relational-checksum",
                size=256,
                mimetype="application/pdf",
                file_type=FileType.DOCUMENT,
                text_length=12,
                has_text=True,
                has_transcription=False,
            ),
        )
    }
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        provider_call_repo=_provider_call_repo(),
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_run_review_checkpoint_repo=review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
    )

    evidence = (await service.get_redacted_evidence_bundle(run_id=run.id)).to_dict()

    assert evidence["step_results"][0]["runtime_input_file_ids"] == [
        str(relational_file_id)
    ]
    runtime_input = evidence["step_results"][0]["input_payload_json"]["runtime_input"]
    assert runtime_input["files"] == [
        {
            "id": str(relational_file_id),
            "name": "relational.pdf",
            "checksum": "relational-checksum",
            "size": 256,
            "mimetype": "application/pdf",
            "file_type": "document",
            "text_length": 12,
            "has_text": True,
            "has_transcription": False,
        }
    ]
    flow_run_repo.list_current_step_input_file_metadata_by_step_result_id.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        step_results=[result],
    )


@pytest.mark.asyncio
async def test_export_evidence_json_rejects_injected_run_id_mismatch(user):
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=AsyncMock(),
        provider_call_repo=_provider_call_repo(),
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=AsyncMock(),
        flow_version_repo=AsyncMock(),
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
    )
    run = _run(user=user, flow_id=uuid4())

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.export_evidence_json(
            run_id=uuid4(),
            run=run,
        )

    assert exc_info.value.code == "flow_run_access_denied"
    assert exc_info.value.context == {"auth_layer": "flow_run_argument"}


@pytest.mark.asyncio
async def test_preloaded_run_is_revalidated_before_evidence_is_returned(
    user,
    monkeypatch,
):
    user = _trace_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = _flow_run_rerun_repo()
    review_checkpoint_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    run = _run(user=user, flow_id=flow.id)
    access_policy = FlowRunAccessPolicy(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
    )
    ensure_can_access_run = AsyncMock()
    monkeypatch.setattr(
        access_policy,
        "ensure_can_access_run",
        ensure_can_access_run,
    )
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = []
    review_checkpoint_repo.list_review_checkpoints_for_run.return_value = []
    flow_run_repo.list_result_files.return_value = []
    flow_run_repo.list_current_step_input_file_metadata_by_step_result_id.return_value = {}
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        provider_call_repo=_provider_call_repo(),
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_run_review_checkpoint_repo=review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
        access_policy=access_policy,
    )

    await service.get_redacted_evidence_bundle(run_id=run.id, run=run)

    ensure_can_access_run.assert_awaited_once_with(
        run,
        access_kind="evidence_view",
    )
    flow_run_repo.get.assert_not_awaited()
