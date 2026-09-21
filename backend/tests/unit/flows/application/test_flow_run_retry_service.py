from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.flows.application.flow_run_retry_service import FlowRunRetryService
from eneo.flows.domain.flow import FlowRunStatus, FlowStepResult, FlowStepResultStatus
from eneo.flows.enums import FlowRunPurpose, FlowRunReviewCheckpointState
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_run_input_envelope import TRANSCRIPT_REGENERATION_KEY
from eneo.main.exceptions import ConflictException, UnauthorizedException


@pytest.fixture
def context(monkeypatch):
    tenant_id, user_id, flow_id, run_id = (uuid4() for _ in range(4))
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id)
    source = SimpleNamespace(
        id=run_id,
        tenant_id=tenant_id,
        flow_id=flow_id,
        principal_type=PrincipalType.USER,
        principal_user_id=user_id,
        principal_service_id=None,
        status=FlowRunStatus.FAILED,
        revision=7,
        flow_version=2,
        run_label="Quarterly report",
        purpose=FlowRunPurpose.TEST,
        input_payload_json={"question": "Summarize", "expected_flow_version": 2},
    )
    results = [
        FlowStepResult(
            id=uuid4(),
            flow_run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            step_id=uuid4(),
            step_order=order,
            current_attempt_no=1,
            status=status,
            input_payload_json={"text": f"Input {order}"},
            output_payload_json={"text": f"Output {order}"},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        for order, status in enumerate(
            ["completed", "completed", "failed", "pending"], start=1
        )
    ]
    files = {result.id: [uuid4(), uuid4()] for result in results}
    run_repo = AsyncMock()
    run_repo.get_idempotent_run.return_value = None
    run_repo.list_step_results.return_value = results
    review_flags = {}
    run_repo.list_step_result_identities.side_effect = lambda **kwargs: [
        SimpleNamespace(
            id=result.id,
            step_id=result.step_id,
            step_order=result.step_order,
            status=result.status,
            current_attempt_no=result.current_attempt_no,
            imported_review_established=review_flags.get(result.step_id),
        )
        for result in results
    ]
    run_repo.list_step_results_by_orders.return_value = results[:2]
    run_repo.measure_prefix_results.return_value = SimpleNamespace(
        step_count=2, logical_bytes=42
    )
    run_repo.list_step_orders_with_result_files.return_value = set()
    run_repo.list_current_step_input_file_ids_by_step_result_id.return_value = files
    flow_repo = AsyncMock()
    flow_repo.get.return_value = SimpleNamespace(published_version=2)
    access = AsyncMock()
    access.load_run.return_value = source
    checkpoints = AsyncMock()
    checkpoints.list_review_checkpoints_for_run.return_value = []
    checkpoints.list_review_checkpoint_identities.return_value = []
    runtime_steps = [
        SimpleNamespace(
            step_id=step.step_id, step_order=step.step_order, review_policy=None
        )
        for step in results
    ]
    definition = SimpleNamespace(runtime_steps=Mock(return_value=runtime_steps))
    monkeypatch.setattr(
        "eneo.flows.application.flow_run_retry_service.load_published_definition",
        AsyncMock(return_value=definition),
    )
    run_service = AsyncMock()
    child = SimpleNamespace(id=uuid4(), revision=1, input_payload_json={})
    run_service.create_run.return_value = SimpleNamespace(run=child, created=True)
    service = FlowRunRetryService(
        user=user,
        run_service=run_service,
        access_policy=access,
        run_repo=run_repo,
        flow_repo=flow_repo,
        checkpoint_repo=checkpoints,
        audit_service=AsyncMock(),
    )
    return SimpleNamespace(
        service=service,
        source=source,
        results=results,
        runtime_steps=runtime_steps,
        review_flags=review_flags,
        files=files,
        child=child,
        request=dict(flow_id=flow_id, run_id=run_id, idempotency_key=" retry-1 "),
    )


async def test_reuses_completed_prefix_and_preserves_creation_inputs(context):
    result = await context.service.retry_from_failed_step(**context.request)
    args = context.service.run_service.create_run.await_args.kwargs
    seed = args["prefix_seed"]
    assert seed.kind == "reused_prefix"
    assert seed.source_run_id == context.source.id
    assert seed.review_established_step_ids == frozenset()
    assert seed.results == tuple(context.results[:2])
    assert result.run_result.run is context.child
    assert result.run_result.created is True
    assert result.source_run_id == context.source.id
    assert result.first_executed_step_order == 3
    assert result.reused_step_orders == (1, 2)
    assert args["flow_id"] == context.source.flow_id
    assert args["input_payload_json"] == {"question": "Summarize"}
    assert args["expected_flow_version"] == 2
    assert args["run_label"] == "Quarterly report"
    assert args["purpose"] == FlowRunPurpose.TEST
    assert args["idempotency_key"] == "retry-1"
    assert {
        step_id: inputs.file_ids for step_id, inputs in args["step_inputs"].items()
    } == {step.step_id: tuple(context.files[step.id]) for step in context.results}
    assert (
        seed.provenance.items()
        >= {
            "version": 1,
            "kind": "reused_prefix",
            "source_run_id": str(context.source.id),
            "source_run_revision": 7,
            "source_flow_version": 2,
            "first_executed_step_order": 3,
        }.items()
    )
    assert seed.provenance["reused_step_orders"] == [1, 2]
    assert context.service.audit_service.log.await_args.kwargs["required"] is True
    assert context.source.status == "failed"


async def test_replay_returns_same_child_without_new_creation_or_audit(context):
    await context.service.retry_from_failed_step(**context.request)
    seed = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    context.child.input_payload_json = {TRANSCRIPT_REGENERATION_KEY: seed.provenance}
    context.service.run_repo.get_idempotent_run.return_value = (context.child, "fp")
    context.service.run_service.create_run.reset_mock()
    context.service.audit_service.log.reset_mock()
    context.service.flow_repo.get.return_value.published_version = 3

    replay = await context.service.retry_from_failed_step(**context.request)

    assert replay.run_result.run is context.child
    assert replay.run_result.created is False
    assert replay.first_executed_step_order == 3
    assert replay.reused_step_orders == (1, 2)
    context.service.run_service.create_run.assert_not_awaited()
    context.service.audit_service.log.assert_not_awaited()


async def test_retry_import_copies_bounded_consumed_material_alias(context):
    import hashlib
    import json

    from sqlalchemy.dialects import postgresql

    from eneo.flows.domain.step_output import ResolvedStepMaterial
    from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
    from eneo.flows.runtime.step_result_builder import build_step_input_payload

    text = "Complete consumed material.\n" * 200
    material = ResolvedStepMaterial(
        source_step_id=uuid4(),
        source_attempt_no=3,
        file_id=uuid4(),
        checksum=hashlib.sha256(text.encode()).hexdigest(),
        byte_size=len(text.encode()),
        text=text,
    )
    payload = build_step_input_payload(
        text=text,
        source_text=text,
        input_source="previous_step",
        used_question_binding=False,
        materials=(material,),
        max_inline_text_bytes=2048,
    )
    context.results[1].input_payload_json = payload
    await context.service.retry_from_failed_step(**context.request)
    seed = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    assert seed.results[1].input_payload_json == payload

    session = AsyncMock()
    session.execute.return_value = Mock()
    await FlowRunRepository(session=session).seed_validated_prefix(
        run=SimpleNamespace(
            id=context.child.id,
            flow_id=context.source.flow_id,
            tenant_id=context.source.tenant_id,
        ),
        seed=seed,
    )
    copied_inputs = [
        call.args[0].compile(dialect=postgresql.dialect()).params["input_payload_json"]
        for call in session.execute.await_args_list[-2:]
    ]
    assert copied_inputs == [payload, payload]
    assert payload["text"] == text[:2048]
    assert payload["text_truncated"] is True
    assert payload["material_aliases"][0]["source_step_id"] == str(
        material.source_step_id
    )
    assert payload["material_aliases"][0]["source_attempt_no"] == 3
    assert payload["material_aliases"][0]["checksum"] == material.checksum
    assert text not in json.dumps(copied_inputs)
    assert len(payload["text"].encode()) <= 2048
    assert len(json.dumps(payload["material_aliases"]).encode()) <= 2048


@pytest.mark.parametrize(
    "failure,code,expected_context",
    [
        ("status", "flow_run_retry_source_not_failed", {"status": "completed"}),
        (
            "version",
            "flow_run_retry_source_version_stale",
            {"source_flow_version": 2, "published_version": 3},
        ),
        ("empty", "flow_run_retry_nothing_to_reuse", {}),
        (
            "files",
            "flow_run_retry_prefix_unsupported",
            {"step_order": 2, "reason": "file_backed_prefix_unsupported"},
        ),
        (
            "review",
            "flow_run_retry_prefix_unsupported",
            {"step_order": 1, "reason": "review_not_established"},
        ),
    ],
)
async def test_refusal_does_not_persist(context, failure, code, expected_context):
    if failure == "status":
        context.source.status = FlowRunStatus.COMPLETED
    elif failure == "version":
        context.service.flow_repo.get.return_value.published_version = 3
    elif failure == "empty":
        context.results[0].status = FlowStepResultStatus.FAILED
    elif failure == "files":
        context.service.run_repo.list_step_orders_with_result_files.return_value = {2}
    elif failure == "review":
        context.runtime_steps[0].review_policy = object()
        _set_checkpoints(context, FlowRunReviewCheckpointState.REJECTED)
    with pytest.raises(ConflictException) as exc:
        await context.service.retry_from_failed_step(**context.request)
    assert exc.value.code == code
    assert exc.value.context == expected_context
    if failure == "files":
        assert str(exc.value) == "The completed prefix cannot be reused."
    context.service.run_service.create_run.assert_not_awaited()
    context.service.audit_service.log.assert_not_awaited()


async def test_file_backed_transcript_prefix_cannot_be_retried(context):
    from eneo.flows.domain.step_output import build_text_overflow_metadata

    payload = context.results[0].output_payload_json
    payload["text_overflow"] = build_text_overflow_metadata(
        file_ids=[uuid4()], preview=payload["text"], full_text=payload["text"] * 100
    )
    with pytest.raises(ConflictException) as exc:
        await context.service.retry_from_failed_step(**context.request)
    assert exc.value.code == "flow_run_retry_prefix_unsupported"
    assert exc.value.context == {
        "step_order": 1,
        "reason": "file_backed_prefix_unsupported",
    }
    assert str(exc.value) == "The completed prefix cannot be reused."
    context.service.run_service.create_run.assert_not_awaited()


@pytest.mark.parametrize("source_index", [0, 1])
async def test_retry_rejects_spilled_transcript_with_inline_output(
    context, source_index
):
    from eneo.flows.domain.step_output import FileBackedStepText

    source = context.results[source_index]
    source.output_payload_json = {"text": "ok"}
    context.source.input_payload_json["transkribering"] = FileBackedStepText(
        preview="raw",
        inline_text_bytes=3,
        full_text_bytes=4096,
        file_id=uuid4(),
        checksum="a" * 64,
        source_step_id=source.step_id,
        source_attempt_no=source.current_attempt_no,
    ).model_dump(mode="json")
    with pytest.raises(ConflictException) as exc:
        await context.service.retry_from_failed_step(**context.request)
    assert exc.value.code == "flow_run_retry_prefix_unsupported"
    assert exc.value.context == {
        "step_order": source.step_order,
        "reason": "file_backed_prefix_unsupported",
    }
    assert str(exc.value) == "The completed prefix cannot be reused."
    context.service.run_service.create_run.assert_not_awaited()
    context.service.audit_service.log.assert_not_awaited()


async def test_approved_prefix_uses_effective_reviewed_payload(context):
    context.results[0].output_payload_json = {"text": "Approved correction"}
    context.runtime_steps[0].review_policy = object()
    _set_checkpoints(context, FlowRunReviewCheckpointState.APPROVED)
    await context.service.retry_from_failed_step(**context.request)
    seed = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    assert seed.results[0].output_payload_json == {"text": "Approved correction"}
    assert seed.review_established_step_ids == frozenset({context.results[0].step_id})


async def test_retry_preserves_transcription_input_from_completed_prefix(context):
    context.source.input_payload_json["transkribering"] = "Approved transcript"
    await context.service.retry_from_failed_step(**context.request)
    args = context.service.run_service.create_run.await_args.kwargs
    assert args["input_payload_json"] == {"question": "Summarize"}
    assert args["prefix_seed"].transcript == "Approved transcript"


async def test_other_principal_is_refused_before_lock_or_creation(context):
    context.source.principal_user_id = uuid4()
    with pytest.raises(UnauthorizedException) as exc:
        await context.service.retry_from_failed_step(**context.request)
    assert exc.value.code == "flow_run_access_denied"
    context.service.run_repo.acquire_tenant_run_creation_lock.assert_not_awaited()
    context.service.run_service.create_run.assert_not_awaited()


async def test_conflicting_idempotency_key_does_not_create(context):
    context.child.input_payload_json = {
        TRANSCRIPT_REGENERATION_KEY: {"request_hash": "different"}
    }
    context.service.run_repo.get_idempotent_run.return_value = (context.child, "fp")
    with pytest.raises(FlowBadRequestException) as exc:
        await context.service.retry_from_failed_step(**context.request)
    assert exc.value.code == "flow_run_idempotency_conflict"
    context.service.run_service.create_run.assert_not_awaited()


async def test_oversized_prefix_uses_existing_inline_bound(context, monkeypatch):
    monkeypatch.setattr(
        "eneo.flows.flow_run_payload_validation.get_settings",
        lambda: SimpleNamespace(flow_max_inline_text_bytes=4),
    )
    with pytest.raises(FlowBadRequestException) as exc:
        await context.service.retry_from_failed_step(**context.request)
    assert exc.value.code == "flow_run_input_payload_too_large"
    context.service.run_service.create_run.assert_not_awaited()


def _set_checkpoints(context, state, *, attempt_no=1):
    checkpoints = [
        SimpleNamespace(
            step_id=context.results[0].step_id,
            step_order=1,
            attempt_no=attempt_no,
            state=state,
        )
    ]
    context.service.checkpoint_repo.list_review_checkpoints_for_run.return_value = (
        checkpoints
    )
    context.service.checkpoint_repo.list_review_checkpoint_identities.return_value = (
        checkpoints
    )


@pytest.mark.parametrize(
    "state,attempt_no",
    [(None, 1)]
    + [
        (state, 1)
        for state in FlowRunReviewCheckpointState
        if state
        not in (
            FlowRunReviewCheckpointState.APPROVED,
            FlowRunReviewCheckpointState.RESUMED,
        )
    ]
    + [(FlowRunReviewCheckpointState.APPROVED, 2)],
)
async def test_required_review_must_be_established_for_imported_attempt(
    context, state, attempt_no
):
    context.runtime_steps[0].review_policy = object()
    if state is not None:
        _set_checkpoints(context, state, attempt_no=attempt_no)
    with pytest.raises(ConflictException) as exc:
        await context.service.retry_from_failed_step(**context.request)
    assert exc.value.code == "flow_run_retry_prefix_unsupported"
    assert exc.value.context == {"step_order": 1, "reason": "review_not_established"}
    context.service.run_service.create_run.assert_not_awaited()
    context.service.run_repo.list_step_results_by_orders.assert_not_awaited()


async def test_resumed_review_reuses_approved_payload(context):
    context.runtime_steps[0].review_policy = object()
    _set_checkpoints(context, FlowRunReviewCheckpointState.RESUMED)
    context.results[0].output_payload_json = {"text": "Approved correction"}
    await context.service.retry_from_failed_step(**context.request)
    seed = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    assert seed.results[0].output_payload_json == {"text": "Approved correction"}
    assert seed.review_established_step_ids == frozenset({context.results[0].step_id})


async def test_prefix_byte_admission_precedes_payload_reads_and_creation_lock(context):
    from eneo.main.config import get_settings

    context.service.run_repo.measure_prefix_results.return_value.logical_bytes = (
        get_settings().flow_max_inline_text_bytes + 1
    )
    with pytest.raises(ConflictException) as exc:
        await context.service.retry_from_failed_step(**context.request)
    assert exc.value.code == "flow_run_retry_prefix_unsupported"
    assert exc.value.context == {"step_order": 1, "reason": "prefix_too_large"}
    context.service.run_repo.list_step_results.assert_not_awaited()
    context.service.run_repo.list_step_results_by_orders.assert_not_awaited()
    context.service.checkpoint_repo.list_review_checkpoints_for_run.assert_not_awaited()
    context.service.run_repo.acquire_tenant_run_creation_lock.assert_not_awaited()
    context.service.run_service.create_run.assert_not_awaited()


async def test_only_admitted_prefix_is_hydrated_before_creation_lock(context):
    repo = context.service.run_repo

    async def load_prefix(**kwargs):
        repo.acquire_tenant_run_creation_lock.assert_not_awaited()
        repo.measure_prefix_results.assert_awaited_once_with(
            run_id=context.source.id,
            tenant_id=context.source.tenant_id,
            step_orders=(1, 2),
        )
        assert kwargs["step_orders"] == (1, 2)
        return context.results[:2]

    repo.list_step_results_by_orders.side_effect = load_prefix
    await context.service.retry_from_failed_step(**context.request)
    repo.list_step_results_by_orders.assert_awaited_once()
    repo.list_step_results.assert_not_awaited()
    repo.acquire_tenant_run_creation_lock.assert_awaited_once()


async def test_prefix_disappearing_after_admission_cannot_create_child(context):
    context.service.run_repo.list_step_results_by_orders.return_value = []
    with pytest.raises(ConflictException) as exc:
        await context.service.retry_from_failed_step(**context.request)
    assert exc.value.context == {"step_order": 1, "reason": "prefix_changed"}
    context.service.run_service.create_run.assert_not_awaited()


async def test_concurrent_acceptance_is_replayed_under_creation_lock(context):
    await context.service.retry_from_failed_step(**context.request)
    seed = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    context.child.input_payload_json = {TRANSCRIPT_REGENERATION_KEY: seed.provenance}
    context.service.run_repo.reset_mock()
    context.service.run_service.create_run.reset_mock()
    context.service.audit_service.log.reset_mock()

    async def find_existing(**kwargs):
        if context.service.run_repo.get_idempotent_run.await_count == 1:
            return None
        context.service.run_repo.acquire_tenant_run_creation_lock.assert_awaited_once()
        return context.child, "fp"

    context.service.run_repo.get_idempotent_run.side_effect = find_existing
    replay = await context.service.retry_from_failed_step(**context.request)
    assert replay.run_result.run is context.child
    assert replay.run_result.created is False
    context.service.run_service.create_run.assert_not_awaited()
    context.service.audit_service.log.assert_not_awaited()


@pytest.mark.parametrize("established", [False, True])
async def test_imported_review_fact_controls_required_review(context, established):
    context.runtime_steps[0].review_policy = object()
    context.review_flags[context.results[0].step_id] = established
    if not established:
        _set_checkpoints(context, FlowRunReviewCheckpointState.APPROVED)
        with pytest.raises(ConflictException) as exc:
            await context.service.retry_from_failed_step(**context.request)
        assert exc.value.context == {
            "step_order": 1,
            "reason": "review_not_established",
        }
        context.service.run_service.create_run.assert_not_awaited()
        return
    await context.service.retry_from_failed_step(**context.request)
    seed = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    assert seed.review_established_step_ids == frozenset({context.results[0].step_id})
    context.service.access_policy.load_run.assert_awaited_once_with(
        flow_id=context.source.flow_id, run_id=context.source.id, access_kind="content"
    )
