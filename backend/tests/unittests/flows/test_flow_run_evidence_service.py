from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_flow_run_service import (
    _attempts_page,
    _file_repo,
    _flow,
    _flow_repo,
    _provider_call_repo,
    _run,
    _step_result_record,
    _trace_user,
    _version,
    flow_run_repo_mock,
)

from eneo.database.tables.flow_tables import FlowOutboxDeliveryStatus
from eneo.files.file_models import FileType
from eneo.flows.application import flow_run_evidence_service
from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_run_evidence_service import (
    EMBEDDED_PROVIDER_CALL_LIMIT,
    EVIDENCE_EXPORT_MAX_PASSAGE_BYTES,
    EVIDENCE_EXPORT_MAX_STORED_PROVENANCE_BYTES,
    PROVIDER_CALL_EXPORT_MAX_EVENTS,
    RUN_VIEW_MAX_LOADED_ATTEMPTS,
    RUN_VIEW_MAX_LOADED_PASSAGE_BYTES,
    RUN_VIEW_MAX_LOADED_STORED_BYTES,
    FlowRunEvidenceService,
)
from eneo.flows.domain.flow import FlowStepAttempt, FlowStepAttemptStatus
from eneo.flows.domain.provider_call import (
    ProviderCallEvidence,
    ProviderCallEvidencePage,
)
from eneo.flows.domain.rag_evidence import (
    RetrievedKnowledgeEvidence,
    RetrievedPassage,
    RetrievedSource,
    mapped_aggregate_payload,
)
from eneo.flows.domain.rag_evidence_policy import FlowRagEvidencePolicy
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_evidence_policy import (
    FlowEvidenceAccessContext,
    flow_metadata_marks_sensitive_or_unreadable,
)
from eneo.flows.flow_run_provenance import FlowAttemptProvenance, RagProvenance
from eneo.flows.flow_run_step_input_file import FlowRunStepInputFileMetadata
from eneo.flows.infrastructure.flow_run_repo import (
    StepAttemptPage,
    StepAttemptProvenanceSize,
)
from eneo.flows.infrastructure.flow_run_rerun_repo import FlowRunRerunRepository
from eneo.flows.infrastructure.flow_run_webhook_delivery_repo import (
    FlowRunWebhookDeliveryRead,
    FlowRunWebhookDeliveryRepository,
)
from eneo.flows.published_definition import published_definition_checksum
from eneo.main.exceptions import FileTooLargeException, UnauthorizedException


def _seed_flow_repo(flow_repo, flow) -> None:
    """Answer both flow reads the access policy makes with the real flow.

    The disclosure decision reads a narrow typed evidence-access context; a
    double that returned a mock there would withhold every passage.
    """
    flow_repo.get.return_value = flow
    flow_repo.get_evidence_access_context.return_value = FlowEvidenceAccessContext(
        flow_id=flow.id,
        space_id=flow.space_id,
        sensitive=flow_metadata_marks_sensitive_or_unreadable(flow.metadata_json),
        classification_level=0,
    )


def _access_policy_double() -> AsyncMock:
    """Access-policy double that answers the disclosure question it must answer.

    The real policy returns a typed passage-disclosure decision; a double that
    returned a mock here would silently mask every passage.
    """
    policy = AsyncMock(spec=FlowRunAccessPolicy)
    policy.passage_disclosure_for_run.return_value = "text_disclosed"
    return policy


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
    flow_run_repo = flow_run_repo_mock()
    flow = _flow(user=user)
    _seed_flow_repo(flow_repo, flow)
    run = _run(user=user, flow_id=flow.id)
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = _attempts_page([])
    flow_run_repo.list_result_files.return_value = []
    flow_version_repo = AsyncMock()
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    review_checkpoint_repo = AsyncMock()
    review_checkpoint_repo.list_review_checkpoints_for_run.return_value = []
    resolved_access_policy = access_policy or _access_policy_double()
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
    access_policy = _access_policy_double()
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
    assert exc_info.value.context["limit"] == "provider_call_events"
    assert (
        exc_info.value.context["provider_call_count"]
        == PROVIDER_CALL_EXPORT_MAX_EVENTS + 1
    )
    assert (
        exc_info.value.context["max_provider_call_events"]
        == PROVIDER_CALL_EXPORT_MAX_EVENTS
    )
    # The hint may only name recovery paths that exist. There is no offline or
    # asynchronous export surface to send a caller to.
    # Recovery guidance must reach the client, so it lives in the typed
    # context — and may only name recovery paths that exist.
    hint = str(exc_info.value.context.get("hint", ""))
    assert "provider-calls" in hint
    assert "offline" not in hint.lower()
    assert "administrator" not in hint.lower()
    assert exc_info.value.context["limit"] == "provider_call_events"


@pytest.mark.asyncio
async def test_evidence_exports_identical_safe_webhook_delivery_metadata(user):
    user = _trace_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = flow_run_repo_mock()
    flow_run_rerun_repo = _flow_run_rerun_repo()
    review_checkpoint_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    webhook_delivery_repo = _webhook_delivery_repo()
    access_policy = _access_policy_double()
    flow = _flow(user=user)
    _seed_flow_repo(flow_repo, flow)
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
    flow_run_repo.list_step_attempts.return_value = _attempts_page([])
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
    flow_run_repo = flow_run_repo_mock()
    flow_run_rerun_repo = _flow_run_rerun_repo()
    review_checkpoint_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    _seed_flow_repo(flow_repo, flow)
    run = _run(user=user, flow_id=flow.id)
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = _attempts_page([])
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
    flow_run_repo = flow_run_repo_mock()
    flow_run_rerun_repo = _flow_run_rerun_repo()
    review_checkpoint_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    _seed_flow_repo(flow_repo, flow)
    run = _run(user=user, flow_id=flow.id)
    version = _version(user=user, flow=flow, version=run.flow_version).model_copy(
        update={"definition_checksum": "stored-checksum-does-not-match"}
    )
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = _attempts_page([])
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
    flow_run_repo = flow_run_repo_mock()
    flow_run_rerun_repo = _flow_run_rerun_repo()
    review_checkpoint_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    _seed_flow_repo(flow_repo, flow)
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
    flow_run_repo.list_step_attempts.return_value = _attempts_page([])
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
    flow_run_repo = flow_run_repo_mock()
    flow_run_rerun_repo = _flow_run_rerun_repo()
    review_checkpoint_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user)
    _seed_flow_repo(flow_repo, flow)
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
    flow_run_repo.list_step_attempts.return_value = _attempts_page([])
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


def _attempt_with_passage_bytes(run, *, byte_count: int, attempt_no: int = 1):
    passage = "x" * byte_count
    now = datetime.now(timezone.utc)
    return FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        attempt_no=attempt_no,
        celery_task_id=None,
        status=FlowStepAttemptStatus.COMPLETED,
        error_code=None,
        # Built through the production provenance envelope: a bare dict would be
        # read back as corrupt and hide what this test is checking.
        provenance_json=FlowAttemptProvenance(
            rag=RagProvenance.model_validate(
                RetrievedKnowledgeEvidence(
                    sources=[
                        RetrievedSource(
                            id=f"source-{attempt_no}",
                            id_short=f"source-{attempt_no}"[:8],
                            title="Beslutsunderlag",
                            matched_chunk_count=1,
                            recorded_passage_count=1,
                            best_score=0.8,
                            passages=[
                                RetrievedPassage.record(
                                    chunk_no=1,
                                    score=0.8,
                                    retrieved_text=passage,
                                    max_bytes=byte_count,
                                )
                            ],
                        )
                    ]
                ).write_into({"status": "success", "unique_sources": 1})
            )
        ).to_payload(),
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )


def _service_with_attempts(*, user, attempts_bytes: list[int], access_kind_run=None):
    flow_repo = _flow_repo()
    flow_run_repo = flow_run_repo_mock()
    flow = _flow(user=user)
    _seed_flow_repo(flow_repo, flow)
    run = access_kind_run or _run(user=user, flow_id=flow.id)
    attempts = [
        _attempt_with_passage_bytes(run, byte_count=size, attempt_no=index + 1)
        for index, size in enumerate(attempts_bytes)
    ]
    flow_run_repo.get.return_value = run
    flow_run_repo.list_step_results.return_value = []
    flow_run_repo.list_step_attempts.return_value = _attempts_page(attempts)
    flow_run_repo.list_result_files.return_value = []
    flow_run_repo.list_current_step_input_file_metadata_by_step_result_id.return_value = {}
    flow_version_repo = AsyncMock()
    flow_version_repo.get.return_value = _version(user=user, flow=flow, version=1)
    review_checkpoint_repo = AsyncMock()
    review_checkpoint_repo.list_review_checkpoints_for_run.return_value = []
    access_policy = _access_policy_double()
    access_policy.load_run.return_value = run
    service = FlowRunEvidenceService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        provider_call_repo=_provider_call_repo(),
        flow_run_rerun_repo=_flow_run_rerun_repo(),
        flow_run_review_checkpoint_repo=review_checkpoint_repo,
        flow_version_repo=flow_version_repo,
        file_repo=_file_repo(),
        webhook_delivery_repo=_webhook_delivery_repo(),
        access_policy=access_policy,
    )
    return service, run


def _passage_texts_from_payload(payload) -> list[object]:
    return [
        passage.get("text")
        for attempt in payload["step_attempts"]
        for reference in (
            (attempt.get("provenance_json") or {}).get("rag", {}).get("references", [])
        )
        for passage in reference["passages"]
    ]


@pytest.mark.asyncio
async def test_interactive_view_omits_passages_beyond_the_view_budget(
    user, monkeypatch
) -> None:
    user = _trace_user(user)
    monkeypatch.setattr(
        FlowRunEvidenceService,
        "_rag_evidence_policy",
        lambda self: FlowRagEvidencePolicy(max_recorded_passage_bytes_per_run_view=150),
    )
    service, run = _service_with_attempts(user=user, attempts_bytes=[100, 100])

    bundle = await service.get_redacted_evidence_bundle(run_id=run.id)

    texts = _passage_texts_from_payload(bundle.to_dict())
    assert texts.count(None) == 0
    assert len([text for text in texts if text]) == 1
    omission = bundle.debug_export["run"]["summary"]["knowledge_evidence_view"]
    assert omission["byte_budget"] == 150
    assert omission["returned_passage_bytes"] == 100
    assert omission["passages_omitted"] == 1
    assert omission["passage_bytes_omitted"] == 100
    assert omission["attempts_with_omitted_passages"] == 1


@pytest.mark.asyncio
async def test_raw_export_returns_every_retained_passage(user, monkeypatch) -> None:
    """An export is the record of what is retained; it is never quietly trimmed."""
    user = _trace_user(user)
    monkeypatch.setattr(
        FlowRunEvidenceService,
        "_rag_evidence_policy",
        lambda self: FlowRagEvidencePolicy(max_recorded_passage_bytes_per_run_view=150),
    )
    service, run = _service_with_attempts(user=user, attempts_bytes=[100, 100])

    payload = await service.export_evidence_json(run_id=run.id, detail="raw")

    texts = _passage_texts_from_payload(payload["bundle"])
    assert texts == ["x" * 100, "x" * 100]
    assert (
        payload["bundle"]["debug_export"]["run"]["summary"]["knowledge_evidence_view"]
        is None
    )


@pytest.mark.asyncio
async def test_an_export_too_large_to_carry_fails_explicitly(user, monkeypatch) -> None:
    user = _trace_user(user)
    # Patch the imported module object: `eneo.flows` uses lazy exports, so a
    # dotted string path only resolves when the submodule happens to be loaded.
    monkeypatch.setattr(
        flow_run_evidence_service, "EVIDENCE_EXPORT_MAX_PASSAGE_BYTES", 150
    )
    service, run = _service_with_attempts(user=user, attempts_bytes=[100, 100])

    with pytest.raises(FileTooLargeException) as exc_info:
        await service.export_evidence_json(run_id=run.id, detail="raw")

    assert exc_info.value.code == FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE.value


async def test_raw_export_preflight_refuses_on_exact_passage_bytes(user) -> None:
    """A raw export that cannot fit refuses before a single attempt is loaded.

    The measure is the exact recorded-passage aggregate each RAG payload
    stores about itself — not whole-provenance size, which would refuse runs
    whose bulk is unrelated provenance.
    """
    user = _trace_user(user)
    service, run = _service_with_attempts(user=user, attempts_bytes=[100])
    service.flow_run_repo.measure_step_attempt_provenance.return_value = (
        StepAttemptProvenanceSize(
            attempt_count=12,
            stored_provenance_bytes=1024,
            recorded_passage_bytes=EVIDENCE_EXPORT_MAX_PASSAGE_BYTES + 1,
        )
    )

    with pytest.raises(FileTooLargeException) as exc_info:
        await service.export_evidence_json(
            run_id=run.id, detail="raw", export_reason="tillsyn"
        )

    assert exc_info.value.code == FlowApiErrorCode.EVIDENCE_EXPORT_TOO_LARGE.value
    assert exc_info.value.context["limit"] == "recorded_passage_bytes"
    assert "run view" in exc_info.value.context["hint"]
    service.flow_run_repo.list_step_attempts.assert_not_called()


async def test_redacted_export_also_refuses_on_the_passage_load_guard(user) -> None:
    """Retained passage bytes bound the load for redacted exports too.

    Withholding happens after materialization, so a redacted export of a run
    whose retained passages exceed the load ceiling would still expand them in
    memory first. The refusal names the load limit; disclosed-byte accounting
    still governs the finished document below that ceiling.
    """
    user = _trace_user(user)
    service, run = _service_with_attempts(user=user, attempts_bytes=[100])
    service.flow_run_repo.measure_step_attempt_provenance.return_value = (
        StepAttemptProvenanceSize(
            attempt_count=12,
            stored_provenance_bytes=1024,
            recorded_passage_bytes=EVIDENCE_EXPORT_MAX_PASSAGE_BYTES + 1,
        )
    )

    with pytest.raises(FileTooLargeException) as exc_info:
        await service.export_evidence_json(run_id=run.id, export_reason="tillsyn")

    assert exc_info.value.context["limit"] == "recorded_passage_bytes"
    service.flow_run_repo.list_step_attempts.assert_not_called()


async def test_export_preflight_refuses_oversized_materialization(user) -> None:
    """Either export kind refuses when loading itself would cost too much.

    Stored provenance size is the load cost, RAG or not, and is reported as
    exactly that — never as a passage count.
    """
    user = _trace_user(user)
    service, run = _service_with_attempts(user=user, attempts_bytes=[100])
    service.flow_run_repo.measure_step_attempt_provenance.return_value = (
        StepAttemptProvenanceSize(
            attempt_count=12,
            stored_provenance_bytes=EVIDENCE_EXPORT_MAX_STORED_PROVENANCE_BYTES + 1,
            recorded_passage_bytes=0,
        )
    )

    with pytest.raises(FileTooLargeException) as exc_info:
        await service.export_evidence_json(run_id=run.id, export_reason="tillsyn")

    assert exc_info.value.context["limit"] == "stored_provenance_bytes"
    service.flow_run_repo.list_step_attempts.assert_not_called()


async def test_view_preflight_never_refuses_and_never_narrows_small_runs(user) -> None:
    user = _trace_user(user)
    service, run = _service_with_attempts(user=user, attempts_bytes=[100])

    await service.get_redacted_evidence_bundle(run_id=run.id)

    service.flow_run_repo.list_step_attempts.assert_awaited_once()
    assert service.flow_run_repo.list_step_attempts.await_args.kwargs["limit"] is None


async def test_view_narrows_attempt_load_and_reports_unloaded_history(user) -> None:
    """A run with deep rerun history loads a bounded page and says so.

    The response must state how many attempt rows were not loaded — otherwise
    a narrowed view would read as the complete history.
    """
    user = _trace_user(user)
    service, run = _service_with_attempts(user=user, attempts_bytes=[100])
    service.flow_run_repo.measure_step_attempt_provenance.return_value = (
        StepAttemptProvenanceSize(
            attempt_count=8,
            stored_provenance_bytes=RUN_VIEW_MAX_LOADED_STORED_BYTES + 1,
            recorded_passage_bytes=0,
        )
    )
    # The narrowed statement returns one admitted attempt out of eight — the
    # totals travel with the rows so all counts describe one snapshot.
    page = service.flow_run_repo.list_step_attempts.return_value
    service.flow_run_repo.list_step_attempts.return_value = StepAttemptPage(
        attempts=page.attempts,
        total_count=8,
        current_total=2,
        current_admitted=1,
    )

    bundle = await service.get_redacted_evidence_bundle(run_id=run.id)

    call_kwargs = service.flow_run_repo.list_step_attempts.await_args.kwargs
    assert call_kwargs["limit"] == RUN_VIEW_MAX_LOADED_ATTEMPTS
    assert call_kwargs["history_byte_budget"] == RUN_VIEW_MAX_LOADED_STORED_BYTES
    assert call_kwargs["passage_byte_budget"] == RUN_VIEW_MAX_LOADED_PASSAGE_BYTES
    omission = bundle.debug_export["run"]["summary"]["knowledge_evidence_view"]
    assert omission["attempts_not_loaded"] == 7
    # One of the two current attempts did not fit: the response says so
    # instead of letting that step read as having no retrieval evidence.
    assert omission["current_attempts_not_loaded"] == 1


async def test_view_reports_corrupt_passage_aggregates(user) -> None:
    user = _trace_user(user)
    service, run = _service_with_attempts(user=user, attempts_bytes=[])
    service.flow_run_repo.measure_step_attempt_provenance.return_value = (
        StepAttemptProvenanceSize(
            attempt_count=2,
            stored_provenance_bytes=1024,
            recorded_passage_bytes=0,
            corrupt_passage_aggregates=2,
        )
    )
    service.flow_run_repo.list_step_attempts.return_value = StepAttemptPage(
        attempts=[],
        total_count=2,
        current_total=0,
        current_admitted=0,
        corrupt_passage_aggregates=2,
    )

    bundle = await service.get_redacted_evidence_bundle(run_id=run.id)

    call_kwargs = service.flow_run_repo.list_step_attempts.await_args.kwargs
    assert call_kwargs["limit"] == RUN_VIEW_MAX_LOADED_ATTEMPTS
    assert call_kwargs["history_byte_budget"] == RUN_VIEW_MAX_LOADED_STORED_BYTES
    assert call_kwargs["passage_byte_budget"] == RUN_VIEW_MAX_LOADED_PASSAGE_BYTES
    omission = bundle.debug_export["run"]["summary"]["knowledge_evidence_view"]
    assert omission is not None
    assert omission["attempts_not_loaded"] == 2
    assert omission["corrupt_passage_aggregates"] == 2


async def test_redacted_export_is_not_charged_for_withheld_text(
    user, monkeypatch
) -> None:
    """A withheld passage carries no text, so it cannot make an export refuse.

    Charging retained bytes here would reject a classified run's redacted
    export because of content the document will not contain.
    """
    user = _trace_user(user)
    service, run = _service_with_attempts(user=user, attempts_bytes=[100, 100])
    service.access_policy.passage_disclosure_for_run.return_value = (
        "text_withheld_sensitive_flow"
    )
    monkeypatch.setattr(
        "eneo.flows.application.flow_run_evidence_service.EVIDENCE_EXPORT_MAX_PASSAGE_BYTES",
        150,
    )

    payload = await service.export_evidence_json(run_id=run.id, export_reason="tillsyn")

    texts = _passage_texts_from_payload(
        {"step_attempts": payload["bundle"]["step_attempts"]}
        if "bundle" in payload
        else payload
    )
    assert all(text is None for text in texts)


def _mapped_attempt_with_passage_bytes(run, *, byte_count: int, attempt_no: int = 1):
    """A mapped step attempt whose single call recorded one passage."""
    passage = "y" * byte_count
    now = datetime.now(timezone.utc)
    call = RetrievedKnowledgeEvidence(
        sources=[
            RetrievedSource(
                id="mapped-source",
                id_short="mapped-s",
                title="Bilaga",
                matched_chunk_count=1,
                recorded_passage_count=1,
                best_score=0.9,
                passages=[
                    RetrievedPassage.record(
                        chunk_no=1,
                        score=0.9,
                        retrieved_text=passage,
                        max_bytes=byte_count,
                    )
                ],
            )
        ]
    ).write_into({"status": "success", "unique_sources": 1})
    mapped = {
        "status": "success",
        "execution_mode": "per_item",
        "mapped_calls_complete": True,
        "items": [call],
    }
    mapped.update(mapped_aggregate_payload([call]))
    return FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        attempt_no=attempt_no,
        celery_task_id=None,
        status=FlowStepAttemptStatus.COMPLETED,
        error_code=None,
        provenance_json=FlowAttemptProvenance(
            rag=RagProvenance.model_validate(mapped)
        ).to_payload(),
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )


async def test_mapped_view_omission_is_counted_once(user, monkeypatch) -> None:
    """One omitted mapped passage reports as one, not two.

    The mapped root carries the sum of its calls, so a walker that added the
    root and the leaves together would double every count. The public summary
    must show the single omission exactly once.
    """
    user = _trace_user(user)
    monkeypatch.setattr(
        FlowRunEvidenceService,
        "_rag_evidence_policy",
        lambda self: FlowRagEvidencePolicy(max_recorded_passage_bytes_per_run_view=0),
    )
    service, run = _service_with_attempts(user=user, attempts_bytes=[])
    service.flow_run_repo.list_step_attempts.return_value = _attempts_page(
        [_mapped_attempt_with_passage_bytes(run, byte_count=100)]
    )

    bundle = await service.get_redacted_evidence_bundle(run_id=run.id)

    omission = bundle.debug_export["run"]["summary"]["knowledge_evidence_view"]
    assert omission["passages_omitted"] == 1
    assert omission["passage_bytes_omitted"] == 100
