from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.authentication.auth_models import ApiKeyPermission
from eneo.authentication.principal_types import PrincipalType
from eneo.flows.application.flow_run_review_checkpoint_service import (
    FlowRunReviewCheckpointService,
    review_open_terminal_invariant_error,
)
from eneo.flows.domain.flow import FlowRun, FlowRunReviewCheckpoint, FlowRunStatus
from eneo.flows.domain.flow_run_exceptions import FlowRunNotFoundError
from eneo.flows.domain.review_checkpoint_exceptions import (
    FlowReviewCheckpointAlreadyResumedError,
    FlowReviewCheckpointCancelledError,
    FlowReviewCheckpointExpiredError,
    FlowReviewCheckpointNotActiveError,
    FlowReviewCheckpointNotApprovedError,
    FlowReviewCheckpointNotFoundError,
    FlowReviewCheckpointRejectedError,
    FlowReviewCheckpointStaleRevisionError,
    FlowReviewCheckpointStepResultIncompleteError,
    FlowReviewEditStepResultMissingError,
    FlowReviewMultipleActiveCheckpointsError,
    FlowReviewOpenBlockedByActiveCheckpointError,
    FlowReviewRunNoLongerAwaitingReviewError,
    FlowReviewRunNotAwaitingReviewError,
)
from eneo.flows.domain.step_output import build_text_overflow_metadata
from eneo.flows.enums import (
    FlowOutputType,
    FlowRunLifecycleSource,
    FlowRunReviewCheckpointState,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointResumeResult,
)
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    TypedIOValidationException,
    UnauthorizedException,
)


def _run(user, flow_id) -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=flow_id,
        flow_version=1,
        principal_type="user",
        principal_user_id=user.id,
        tenant_id=user.tenant_id,
        trace_id=uuid4(),
        status=FlowRunStatus.AWAITING_REVIEW,
        cancelled_at=None,
        input_payload_json={"input": "value"},
        output_payload_json=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _service_key_user(user):
    return user.model_copy(
        update={
            "active_api_key": SimpleNamespace(
                id=uuid4(),
                ownership="service",
                service_principal_id=uuid4(),
                permission=ApiKeyPermission.WRITE,
                resource_permissions=None,
            ),
        }
    )


def _review_checkpoint(
    user,
    run: FlowRun,
    *,
    state: FlowRunReviewCheckpointState = FlowRunReviewCheckpointState.AWAITING_REVIEW,
    revision: int = 1,
    resume_idempotency_key: str | None = None,
    output_contract_json: dict[str, object] | None = None,
) -> FlowRunReviewCheckpoint:
    now = datetime.now(timezone.utc)
    return FlowRunReviewCheckpoint(
        id=uuid4(),
        tenant_id=user.tenant_id,
        flow_id=run.flow_id,
        flow_run_id=run.id,
        step_id=uuid4(),
        step_order=1,
        attempt_no=1,
        state=state,
        revision=revision,
        schema_version=1,
        original_payload_json={"text": "Draft"},
        current_payload_json={"text": "Draft"},
        step_label="Review step",
        review_mode=FlowStepReviewMode.EDIT,
        output_type=FlowOutputType.JSON,
        output_contract_json=output_contract_json,
        requester_user_id=user.id,
        requester_service_id=None,
        requester_principal_type=PrincipalType.USER,
        decided_by_user_id=None,
        decided_by_service_id=None,
        decided_by_principal_type=None,
        next_step_ids_json=[],
        resume_idempotency_key=resume_idempotency_key,
        edited_at=None,
        approved_at=None,
        rejected_at=None,
        resumed_at=None,
        cancelled_at=None,
        created_at=now,
        updated_at=now,
    )


def _service(
    user,
    *,
    checkpoint_repo: AsyncMock,
    flow_run_repo: AsyncMock | None = None,
    access_policy: AsyncMock | None = None,
    terminalizer: AsyncMock | None = None,
) -> FlowRunReviewCheckpointService:
    return FlowRunReviewCheckpointService(
        user=user,
        flow_run_review_checkpoint_repo=checkpoint_repo,
        flow_run_repo=flow_run_repo or AsyncMock(),
        access_policy=access_policy or AsyncMock(),
        flow_run_terminalizer=terminalizer or AsyncMock(),
    )


async def _edit_payload(
    *,
    service: FlowRunReviewCheckpointService,
    run: FlowRun,
    checkpoint: FlowRunReviewCheckpoint,
    payload: dict[str, object],
) -> FlowRunReviewCheckpoint:
    return await service.edit_review_checkpoint(
        flow_id=run.flow_id,
        run_id=run.id,
        checkpoint_id=checkpoint.id,
        expected_checkpoint_revision=checkpoint.revision,
        current_payload_json=payload,
    )


@pytest.mark.parametrize(
    ("invariant_error", "expected_code", "expected_message"),
    [
        (
            FlowReviewOpenBlockedByActiveCheckpointError(active_checkpoint_id=uuid4()),
            "flow_review_open_active_conflict_invariant",
            "Review checkpoint opening failed because another checkpoint is active.",
        ),
        (
            FlowReviewCheckpointStepResultIncompleteError(
                step_id=uuid4(), attempt_no=1
            ),
            "flow_review_open_step_result_incomplete_invariant",
            "Review checkpoint opening failed because the completed step result was unavailable.",
        ),
        (
            FlowReviewMultipleActiveCheckpointsError(),
            "flow_review_open_multiple_active_checkpoints_invariant",
            "Review checkpoint opening failed because multiple checkpoints are active.",
        ),
    ],
)
def test_review_open_terminal_invariant_mapping_is_owned_by_checkpoint_service(
    invariant_error,
    expected_code: str,
    expected_message: str,
) -> None:
    code, message = review_open_terminal_invariant_error(invariant_error)

    assert code.value == expected_code
    assert message == expected_message


@pytest.mark.asyncio
async def test_get_active_review_checkpoint_preserves_multiple_active_conflict(user):
    flow_id = uuid4()
    run = _run(user=user, flow_id=flow_id)
    checkpoint_repo = AsyncMock()
    access_policy = AsyncMock()
    service = _service(
        user, checkpoint_repo=checkpoint_repo, access_policy=access_policy
    )
    access_policy.load_run.return_value = run
    checkpoint_repo.get_active_review_checkpoint.side_effect = (
        FlowReviewMultipleActiveCheckpointsError()
    )

    with pytest.raises(FlowReviewMultipleActiveCheckpointsError):
        await service.get_active_review_checkpoint(flow_id=flow_id, run_id=run.id)

    access_policy.load_run.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="content",
    )
    checkpoint_repo.get_active_review_checkpoint.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name",
    [
        "edit_review_checkpoint",
        "approve_review_checkpoint",
        "reject_review_checkpoint",
        "resume_review_checkpoint",
    ],
)
async def test_review_mutations_allow_service_key_for_own_run(user, method_name):
    service_user = _service_key_user(user)
    checkpoint_repo = AsyncMock()
    access_policy = AsyncMock()
    terminalizer = AsyncMock()
    service = _service(
        service_user,
        checkpoint_repo=checkpoint_repo,
        access_policy=access_policy,
        terminalizer=terminalizer,
    )
    method = getattr(service, method_name)
    flow_id = uuid4()
    run = _run(user=user, flow_id=flow_id).model_copy(
        update={
            "user_id": None,
            "principal_type": PrincipalType.SERVICE_KEY.value,
            "principal_user_id": None,
            "principal_service_id": service_user.active_api_key.service_principal_id,
            "created_by_api_key_id": service_user.active_api_key.id,
            "runtime_service_permission": ApiKeyPermission.WRITE,
        }
    )
    checkpoint = _review_checkpoint(user, run).model_copy(
        update={
            "requester_user_id": None,
            "requester_service_id": service_user.active_api_key.service_principal_id,
            "requester_principal_type": PrincipalType.SERVICE_KEY,
        }
    )
    access_policy.load_run.return_value = run
    checkpoint_repo.get_review_checkpoint_for_edit.return_value = checkpoint
    checkpoint_repo.edit_review_checkpoint_payload.return_value = checkpoint
    checkpoint_repo.approve_review_checkpoint.return_value = checkpoint
    checkpoint_repo.reject_review_checkpoint.return_value = checkpoint
    checkpoint_repo.resume_review_checkpoint.return_value = (
        FlowRunReviewCheckpointResumeResult(
            checkpoint=checkpoint,
            run=run,
            accepted=True,
        )
    )
    kwargs = {
        "flow_id": flow_id,
        "run_id": run.id,
        "checkpoint_id": checkpoint.id,
        "expected_checkpoint_revision": 1,
    }
    if method_name == "edit_review_checkpoint":
        kwargs["current_payload_json"] = {"text": "Edited"}
    if method_name == "reject_review_checkpoint":
        kwargs["reason"] = "Reject the draft."
    if method_name == "resume_review_checkpoint":
        kwargs["idempotency_key"] = "resume-key"

    result = await method(**kwargs)

    if method_name == "resume_review_checkpoint":
        assert result.checkpoint == checkpoint
        awaited = checkpoint_repo.resume_review_checkpoint.await_args.kwargs
    else:
        assert result == checkpoint
        repo_method_name = (
            "edit_review_checkpoint_payload"
            if method_name == "edit_review_checkpoint"
            else method_name
        )
        awaited = getattr(checkpoint_repo, repo_method_name).await_args.kwargs
    principal = awaited["principal"]
    assert principal.principal_type == PrincipalType.SERVICE_KEY
    assert (
        principal.principal_service_id
        == service_user.active_api_key.service_principal_id
    )
    assert principal.actor_api_key_id == service_user.active_api_key.id
    access_policy.load_run.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="content",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("repo_exception", "expected_exception_type", "expected_code", "expected_context"),
    [
        (
            FlowReviewCheckpointNotFoundError(),
            NotFoundException,
            "flow_review_checkpoint_not_found",
            None,
        ),
        (
            FlowReviewRunNotAwaitingReviewError(status="queued"),
            BadRequestException,
            "flow_review_not_active",
            {"status": "queued"},
        ),
        (
            FlowReviewRunNoLongerAwaitingReviewError(),
            BadRequestException,
            "flow_review_not_active",
            None,
        ),
        (
            FlowReviewCheckpointExpiredError(
                checkpoint_id=uuid4(),
                state="awaiting_review",
                expires_at=None,
                expired_at=None,
            ),
            BadRequestException,
            "flow_review_expired",
            "__expired_no_timestamps__",
        ),
        (
            FlowReviewCheckpointExpiredError(
                checkpoint_id=uuid4(),
                state="awaiting_review",
                expires_at=datetime(2026, 6, 8, 10, 0, tzinfo=timezone.utc),
                expired_at=None,
            ),
            BadRequestException,
            "flow_review_expired",
            "__expired_expires_at__",
        ),
        (
            FlowReviewCheckpointExpiredError(
                checkpoint_id=uuid4(),
                state="expired",
                expires_at=datetime(2026, 6, 8, 10, 0),
                expired_at=datetime(2026, 6, 8, 10, 5, tzinfo=timezone.utc),
            ),
            BadRequestException,
            "flow_review_expired",
            "__expired_both_timestamps__",
        ),
        (
            FlowReviewCheckpointStaleRevisionError(
                expected_checkpoint_revision=3,
                current_checkpoint_revision=4,
            ),
            BadRequestException,
            "flow_review_stale_revision",
            {
                "expected_checkpoint_revision": 3,
                "current_checkpoint_revision": 4,
            },
        ),
        (
            FlowReviewCheckpointNotActiveError(state="rejected"),
            BadRequestException,
            "flow_review_not_active",
            {"state": "rejected"},
        ),
        (
            FlowReviewEditStepResultMissingError(),
            BadRequestException,
            "flow_review_step_result_not_found",
            None,
        ),
        (
            FlowReviewCheckpointAlreadyResumedError(),
            BadRequestException,
            "flow_review_already_resumed",
            None,
        ),
        (
            FlowReviewCheckpointRejectedError(),
            BadRequestException,
            "flow_review_rejected",
            None,
        ),
        (
            FlowReviewCheckpointCancelledError(),
            BadRequestException,
            "flow_review_cancelled",
            None,
        ),
        (
            FlowReviewCheckpointNotApprovedError(state="edited"),
            BadRequestException,
            "flow_review_not_approved",
            {"state": "edited"},
        ),
    ],
)
async def test_approve_review_checkpoint_maps_repository_lifecycle_errors(
    user,
    repo_exception,
    expected_exception_type,
    expected_code,
    expected_context,
):
    checkpoint_repo = AsyncMock()
    access_policy = AsyncMock()
    run = _run(user=user, flow_id=uuid4())
    access_policy.load_run.return_value = run
    checkpoint_repo.approve_review_checkpoint.side_effect = repo_exception
    service = _service(
        user,
        checkpoint_repo=checkpoint_repo,
        access_policy=access_policy,
    )

    with pytest.raises(expected_exception_type) as exc_info:
        await service.approve_review_checkpoint(
            flow_id=run.flow_id,
            run_id=run.id,
            checkpoint_id=uuid4(),
            expected_checkpoint_revision=1,
        )

    assert exc_info.value.code == expected_code
    if expected_context == "__expired_no_timestamps__":
        assert isinstance(repo_exception, FlowReviewCheckpointExpiredError)
        assert exc_info.value.context == {
            "checkpoint_id": str(repo_exception.checkpoint_id),
            "state": repo_exception.state,
        }
    elif expected_context == "__expired_expires_at__":
        assert isinstance(repo_exception, FlowReviewCheckpointExpiredError)
        assert exc_info.value.context == {
            "checkpoint_id": str(repo_exception.checkpoint_id),
            "state": repo_exception.state,
            "expires_at": "2026-06-08T10:00:00+00:00",
        }
    elif expected_context == "__expired_both_timestamps__":
        assert isinstance(repo_exception, FlowReviewCheckpointExpiredError)
        assert exc_info.value.context == {
            "checkpoint_id": str(repo_exception.checkpoint_id),
            "state": repo_exception.state,
            "expires_at": "2026-06-08T10:00:00+00:00",
            "expired_at": "2026-06-08T10:05:00+00:00",
        }
    else:
        assert exc_info.value.context == expected_context


@pytest.mark.asyncio
async def test_review_mutation_translates_parent_run_missing_race_to_generic_not_found(
    user,
):
    checkpoint_repo = AsyncMock()
    access_policy = AsyncMock()
    run = _run(user=user, flow_id=uuid4())
    access_policy.load_run.return_value = run
    checkpoint_repo.approve_review_checkpoint.side_effect = FlowRunNotFoundError(
        run_id=run.id,
        tenant_id=user.tenant_id,
        flow_id=run.flow_id,
    )
    service = _service(
        user,
        checkpoint_repo=checkpoint_repo,
        access_policy=access_policy,
    )

    with pytest.raises(NotFoundException) as exc_info:
        await service.approve_review_checkpoint(
            flow_id=run.flow_id,
            run_id=run.id,
            checkpoint_id=uuid4(),
            expected_checkpoint_revision=1,
        )

    assert exc_info.value.code is None


@pytest.mark.asyncio
async def test_reject_review_checkpoint_translates_terminalizer_missing_run_race_to_generic_not_found(
    user,
):
    checkpoint_repo = AsyncMock()
    access_policy = AsyncMock()
    terminalizer = AsyncMock()
    run = _run(user=user, flow_id=uuid4())
    checkpoint = _review_checkpoint(user, run)
    access_policy.load_run.return_value = run
    checkpoint_repo.reject_review_checkpoint.return_value = checkpoint
    terminalizer.terminalize_run.side_effect = FlowRunNotFoundError(
        run_id=run.id,
        tenant_id=user.tenant_id,
        flow_id=run.flow_id,
    )
    service = _service(
        user,
        checkpoint_repo=checkpoint_repo,
        access_policy=access_policy,
        terminalizer=terminalizer,
    )

    with pytest.raises(NotFoundException) as exc_info:
        await service.reject_review_checkpoint(
            flow_id=run.flow_id,
            run_id=run.id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=1,
            reason="Reject the draft.",
        )

    assert exc_info.value.code is None


@pytest.mark.asyncio
async def test_reject_review_checkpoint_lifecycle_error_skips_terminalization(user):
    checkpoint_repo = AsyncMock()
    access_policy = AsyncMock()
    terminalizer = AsyncMock()
    run = _run(user=user, flow_id=uuid4())
    access_policy.load_run.return_value = run
    checkpoint_repo.reject_review_checkpoint.side_effect = (
        FlowReviewCheckpointNotActiveError(state="resumed")
    )
    service = _service(
        user,
        checkpoint_repo=checkpoint_repo,
        access_policy=access_policy,
        terminalizer=terminalizer,
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.reject_review_checkpoint(
            flow_id=run.flow_id,
            run_id=run.id,
            checkpoint_id=uuid4(),
            expected_checkpoint_revision=1,
            reason="Reject the draft.",
        )

    assert exc_info.value.code == "flow_review_not_active"
    assert exc_info.value.context == {"state": "resumed"}
    terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_review_mutations_reject_service_key_for_run_owned_by_another_principal(
    user,
):
    service_user = _service_key_user(user)
    checkpoint_repo = AsyncMock()
    access_policy = AsyncMock()
    service = _service(
        service_user,
        checkpoint_repo=checkpoint_repo,
        access_policy=access_policy,
    )
    access_policy.load_run.side_effect = UnauthorizedException(
        "You do not have access to this flow run.",
        code="flow_run_access_denied",
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.edit_review_checkpoint(
            flow_id=uuid4(),
            run_id=uuid4(),
            checkpoint_id=uuid4(),
            expected_checkpoint_revision=1,
            current_payload_json={"text": "Edited"},
        )

    assert exc_info.value.code == "flow_run_access_denied"
    checkpoint_repo.get_review_checkpoint_for_edit.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_review_checkpoint_rejects_extra_structured_properties(user):
    checkpoint_repo = AsyncMock()
    access_policy = AsyncMock()
    flow_id = uuid4()
    run = _run(user=user, flow_id=flow_id)
    checkpoint = _review_checkpoint(
        user,
        run,
        output_contract_json={
            "type": "object",
            "required": ["title"],
            "properties": {"title": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    access_policy.load_run.return_value = run
    checkpoint_repo.get_review_checkpoint_for_edit.return_value = checkpoint
    service = _service(
        user,
        checkpoint_repo=checkpoint_repo,
        access_policy=access_policy,
    )

    with pytest.raises(TypedIOValidationException) as exc_info:
        await service.edit_review_checkpoint(
            flow_id=flow_id,
            run_id=run.id,
            checkpoint_id=checkpoint.id,
            expected_checkpoint_revision=checkpoint.revision,
            current_payload_json={
                "text": '{"title":"Draft","extra":"not allowed"}',
                "structured": {"title": "Draft", "extra": "not allowed"},
            },
        )

    assert exc_info.value.code == "typed_io_contract_violation"
    assert "Additional properties are not allowed" in str(exc_info.value)
    checkpoint_repo.edit_review_checkpoint_payload.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_payload",
    [{}, {"structured": {"answer": "missing text"}}, {"text": 42}],
)
async def test_edit_review_checkpoint_rejects_payload_without_canonical_text_before_write(
    user,
    invalid_payload,
):
    checkpoint_repo = AsyncMock()
    access_policy = AsyncMock()
    run = _run(user=user, flow_id=uuid4())
    checkpoint = _review_checkpoint(user, run)
    access_policy.load_run.return_value = run
    checkpoint_repo.get_review_checkpoint_for_edit.return_value = checkpoint
    service = _service(
        user, checkpoint_repo=checkpoint_repo, access_policy=access_policy
    )

    with pytest.raises(TypedIOValidationException) as exc_info:
        await _edit_payload(
            service=service,
            run=run,
            checkpoint=checkpoint,
            payload=invalid_payload,
        )

    assert exc_info.value.code == "typed_io_validation_failed"
    checkpoint_repo.edit_review_checkpoint_payload.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_review_checkpoint_rejects_utf8_text_over_inline_ceiling_before_write(
    user,
    monkeypatch,
):
    checkpoint_repo = AsyncMock()
    access_policy = AsyncMock()
    run = _run(user=user, flow_id=uuid4())
    checkpoint = _review_checkpoint(user, run)
    access_policy.load_run.return_value = run
    checkpoint_repo.get_review_checkpoint_for_edit.return_value = checkpoint
    monkeypatch.setattr(
        "eneo.flows.application.flow_run_review_checkpoint_service.get_settings",
        lambda: SimpleNamespace(flow_max_inline_text_bytes=4),
    )
    service = _service(
        user, checkpoint_repo=checkpoint_repo, access_policy=access_policy
    )

    with pytest.raises(TypedIOValidationException) as exc_info:
        await _edit_payload(
            service=service,
            run=run,
            checkpoint=checkpoint,
            payload={"text": "ååå"},
        )

    assert exc_info.value.code == "typed_io_validation_failed"
    assert exc_info.value.context == {"max_inline_text_bytes": 4}
    checkpoint_repo.edit_review_checkpoint_payload.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_review_checkpoint_rejects_forged_text_overflow_before_lookup_or_write(
    user,
):
    checkpoint_repo = AsyncMock()
    flow_run_repo = AsyncMock()
    access_policy = AsyncMock()
    run = _run(user=user, flow_id=uuid4())
    checkpoint = _review_checkpoint(user, run)
    access_policy.load_run.return_value = run
    checkpoint_repo.get_review_checkpoint_for_edit.return_value = checkpoint
    service = _service(
        user,
        checkpoint_repo=checkpoint_repo,
        flow_run_repo=flow_run_repo,
        access_policy=access_policy,
    )
    overflow = build_text_overflow_metadata(
        file_ids=[uuid4()], preview="Draft", full_text="Draft with overflow"
    )

    with pytest.raises(TypedIOValidationException):
        await _edit_payload(
            service=service,
            run=run,
            checkpoint=checkpoint,
            payload={"text": "Draft", "text_overflow": overflow},
        )

    flow_run_repo.get_result_file.assert_not_awaited()
    checkpoint_repo.edit_review_checkpoint_payload.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("reference_is_valid", [True, False, None])
async def test_edit_review_checkpoint_validates_existing_overflow_reference(
    user,
    reference_is_valid,
):
    checkpoint_repo = AsyncMock()
    flow_run_repo = AsyncMock()
    access_policy = AsyncMock()
    run = _run(user=user, flow_id=uuid4())
    file_id = uuid4()
    overflow = build_text_overflow_metadata(
        file_ids=[file_id], preview="Draft", full_text="Draft with overflow"
    )
    payload = {"text": "Draft", "text_overflow": overflow}
    checkpoint = _review_checkpoint(user, run).model_copy(
        update={"original_payload_json": payload, "current_payload_json": payload}
    )
    access_policy.load_run.return_value = run
    checkpoint_repo.get_review_checkpoint_for_edit.return_value = checkpoint
    checkpoint_repo.edit_review_checkpoint_payload.return_value = checkpoint
    if reference_is_valid is None:
        flow_run_repo.get_result_file.return_value = None
    else:
        flow_run_repo.get_result_file.return_value = SimpleNamespace(
            flow_run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=user.tenant_id,
            step_id=checkpoint.step_id if reference_is_valid else uuid4(),
            attempt_no=checkpoint.attempt_no,
            file_id=file_id,
            source="generated_output",
        )
    service = _service(
        user,
        checkpoint_repo=checkpoint_repo,
        flow_run_repo=flow_run_repo,
        access_policy=access_policy,
    )

    if reference_is_valid is True:
        assert (
            await _edit_payload(
                service=service,
                run=run,
                checkpoint=checkpoint,
                payload=payload,
            )
            == checkpoint
        )
        checkpoint_repo.edit_review_checkpoint_payload.assert_awaited_once()
    else:
        with pytest.raises(TypedIOValidationException):
            await _edit_payload(
                service=service,
                run=run,
                checkpoint=checkpoint,
                payload=payload,
            )
        checkpoint_repo.edit_review_checkpoint_payload.assert_not_awaited()

    flow_run_repo.get_result_file.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        file_id=file_id,
    )


@pytest.mark.asyncio
async def test_edit_review_checkpoint_rejects_changed_overflow_preview_before_lookup(
    user,
):
    checkpoint_repo = AsyncMock()
    flow_run_repo = AsyncMock()
    access_policy = AsyncMock()
    run = _run(user=user, flow_id=uuid4())
    file_id = uuid4()
    overflow = build_text_overflow_metadata(
        file_ids=[file_id], preview="Draft", full_text="Draft with overflow"
    )
    checkpoint = _review_checkpoint(user, run).model_copy(
        update={"current_payload_json": {"text": "Draft", "text_overflow": overflow}}
    )
    access_policy.load_run.return_value = run
    checkpoint_repo.get_review_checkpoint_for_edit.return_value = checkpoint
    service = _service(
        user,
        checkpoint_repo=checkpoint_repo,
        flow_run_repo=flow_run_repo,
        access_policy=access_policy,
    )

    with pytest.raises(TypedIOValidationException) as exc_info:
        await _edit_payload(
            service=service,
            run=run,
            checkpoint=checkpoint,
            payload={"text": "Other", "text_overflow": overflow},
        )

    assert "overflow-backed text preview cannot be changed" in str(exc_info.value)
    flow_run_repo.get_result_file.assert_not_awaited()
    checkpoint_repo.edit_review_checkpoint_payload.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "edited_payload",
    [
        {"text": "Edited"},
        {"text": "Edited", "template_provenance": {"template_id": "changed"}},
    ],
)
async def test_edit_review_checkpoint_rejects_runtime_owned_key_destruction_or_change(
    user,
    edited_payload,
):
    checkpoint_repo = AsyncMock()
    access_policy = AsyncMock()
    run = _run(user=user, flow_id=uuid4())
    checkpoint = _review_checkpoint(user, run).model_copy(
        update={
            "current_payload_json": {
                "text": "Draft",
                "template_provenance": {"template_id": "original"},
            }
        }
    )
    access_policy.load_run.return_value = run
    checkpoint_repo.get_review_checkpoint_for_edit.return_value = checkpoint
    service = _service(
        user, checkpoint_repo=checkpoint_repo, access_policy=access_policy
    )

    with pytest.raises(TypedIOValidationException):
        await _edit_payload(
            service=service,
            run=run,
            checkpoint=checkpoint,
            payload=edited_payload,
        )

    checkpoint_repo.edit_review_checkpoint_payload.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_review_checkpoint_rejects_unsupported_checkpoint_schema_version(
    user,
):
    checkpoint_repo = AsyncMock()
    access_policy = AsyncMock()
    run = _run(user=user, flow_id=uuid4())
    checkpoint = _review_checkpoint(user, run).model_copy(update={"schema_version": 2})
    access_policy.load_run.return_value = run
    checkpoint_repo.get_review_checkpoint_for_edit.return_value = checkpoint
    service = _service(
        user, checkpoint_repo=checkpoint_repo, access_policy=access_policy
    )

    with pytest.raises(TypedIOValidationException):
        await _edit_payload(
            service=service,
            run=run,
            checkpoint=checkpoint,
            payload={"text": "Edited"},
        )

    checkpoint_repo.edit_review_checkpoint_payload.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_review_checkpoint_requires_idempotency_key(user):
    checkpoint_repo = AsyncMock()
    service = _service(user, checkpoint_repo=checkpoint_repo)

    with pytest.raises(BadRequestException) as exc_info:
        await service.resume_review_checkpoint(
            flow_id=uuid4(),
            run_id=uuid4(),
            checkpoint_id=uuid4(),
            expected_checkpoint_revision=1,
            idempotency_key=" ",
        )

    assert exc_info.value.code == "flow_review_idempotency_key_required"
    checkpoint_repo.resume_review_checkpoint.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_review_checkpoint_rejects_too_long_idempotency_key(user):
    checkpoint_repo = AsyncMock()
    service = _service(user, checkpoint_repo=checkpoint_repo)

    with pytest.raises(BadRequestException) as exc_info:
        await service.resume_review_checkpoint(
            flow_id=uuid4(),
            run_id=uuid4(),
            checkpoint_id=uuid4(),
            expected_checkpoint_revision=1,
            idempotency_key="x" * 256,
        )

    assert exc_info.value.code == "flow_run_invalid_idempotency_key"
    assert exc_info.value.context == {"max_length": 255}
    checkpoint_repo.resume_review_checkpoint.assert_not_awaited()


@pytest.mark.asyncio
async def test_reject_review_checkpoint_requires_reason(user):
    checkpoint_repo = AsyncMock()
    service = _service(user, checkpoint_repo=checkpoint_repo)

    with pytest.raises(BadRequestException) as exc_info:
        await service.reject_review_checkpoint(
            flow_id=uuid4(),
            run_id=uuid4(),
            checkpoint_id=uuid4(),
            expected_checkpoint_revision=1,
            reason=" ",
        )

    assert exc_info.value.code == "flow_review_reject_reason_required"
    checkpoint_repo.reject_review_checkpoint.assert_not_awaited()


@pytest.mark.asyncio
async def test_reject_review_checkpoint_rejects_too_long_reason(user):
    checkpoint_repo = AsyncMock()
    service = _service(user, checkpoint_repo=checkpoint_repo)

    with pytest.raises(BadRequestException) as exc_info:
        await service.reject_review_checkpoint(
            flow_id=uuid4(),
            run_id=uuid4(),
            checkpoint_id=uuid4(),
            expected_checkpoint_revision=1,
            reason="x" * 1025,
        )

    assert exc_info.value.code == "flow_review_reject_reason_too_long"
    assert exc_info.value.context == {"max_length": 1024}
    checkpoint_repo.reject_review_checkpoint.assert_not_awaited()


@pytest.mark.asyncio
async def test_reject_review_checkpoint_terminalizes_run_with_review_source(user):
    checkpoint_repo = AsyncMock()
    access_policy = AsyncMock()
    terminalizer = AsyncMock()
    run = _run(user=user, flow_id=uuid4())
    checkpoint = _review_checkpoint(user, run)
    access_policy.load_run.return_value = run
    checkpoint_repo.reject_review_checkpoint.return_value = checkpoint
    service = _service(
        user,
        checkpoint_repo=checkpoint_repo,
        access_policy=access_policy,
        terminalizer=terminalizer,
    )

    result = await service.reject_review_checkpoint(
        flow_id=run.flow_id,
        run_id=run.id,
        checkpoint_id=checkpoint.id,
        expected_checkpoint_revision=checkpoint.revision,
        reason="Reject the draft.",
    )

    assert result == checkpoint
    checkpoint_repo.reject_review_checkpoint.assert_awaited_once()
    terminalizer.terminalize_run.assert_awaited_once()
    terminal_kwargs = terminalizer.terminalize_run.await_args.kwargs
    assert terminal_kwargs["run_id"] == run.id
    assert terminal_kwargs["target_status"] == FlowRunStatus.CANCELLED
    assert terminal_kwargs["source"] == FlowRunLifecycleSource.REVIEW_REJECTED
    assert terminal_kwargs["error"].code == "flow_review_rejected"
    assert terminal_kwargs["error"].message == "Reject the draft."


@pytest.mark.asyncio
async def test_resume_review_checkpoint_normalizes_idempotency_key(user):
    checkpoint_repo = AsyncMock()
    access_policy = AsyncMock()
    run = _run(user=user, flow_id=uuid4())
    checkpoint = _review_checkpoint(
        user,
        run,
        state=FlowRunReviewCheckpointState.RESUMED,
        revision=2,
        resume_idempotency_key="resume-key",
    )
    access_policy.load_run.return_value = run
    checkpoint_repo.resume_review_checkpoint.return_value = (
        FlowRunReviewCheckpointResumeResult(
            checkpoint=checkpoint,
            run=run,
            accepted=False,
        )
    )
    service = _service(
        user,
        checkpoint_repo=checkpoint_repo,
        access_policy=access_policy,
    )

    result = await service.resume_review_checkpoint(
        flow_id=run.flow_id,
        run_id=run.id,
        checkpoint_id=checkpoint.id,
        expected_checkpoint_revision=1,
        idempotency_key=" resume-key ",
    )

    assert result.accepted is False
    resume_kwargs = checkpoint_repo.resume_review_checkpoint.await_args.kwargs
    assert resume_kwargs["resume_idempotency_key"] == "resume-key"
