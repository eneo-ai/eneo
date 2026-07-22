from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

import eneo.flows.application.flow_dispatch as flow_dispatch_module
from eneo.audit.domain.actor_types import ActorType
from eneo.flows.application.flow_dispatch import (
    FlowRunDispatchAccepted,
    FlowRunDispatchExhausted,
    FlowRunDispatchExhaustionGenerationConflictError,
    FlowRunDispatchFailed,
    FlowRunDispatchInvalidRequest,
    FlowRunDispatchNotClaimed,
    FlowRunDispatchOutcomeUnknown,
    dispatch_flow_run_recoverably_after_commit,
    redrive_flow_run_recoverably_after_commit,
)
from eneo.flows.domain.flow import FlowRunStatus
from eneo.flows.domain.flow_run_recovery_policy import (
    FLOW_DISPATCH_MAX_ATTEMPTS,
    flow_dispatch_retry_delay_seconds,
    start_flow_dispatch_epoch,
)
from eneo.flows.execution_backend import FlowExecutionDispatchRejected
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_dispatch_request import (
    FlowRunUserDispatchRequest,
    build_flow_run_dispatch_request,
)
from eneo.flows.flow_run_error import (
    FlowRunDispatchError,
    FlowRunDispatchErrorKind,
)
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunDispatchRedriveGenerationConflict,
)
from eneo.main.exceptions import AuditLoggingUnavailableException
from tests.unittests.flows.test_flow_router import _run


def test_queue_epoch_initializes_one_due_dispatch_state() -> None:
    now = _run(flow_id=uuid4(), tenant_id=uuid4()).created_at
    assert now is not None

    assert start_flow_dispatch_epoch(now) == {
        "dispatch_pending_since": now,
        "dispatch_attempt_count": 0,
        "dispatch_last_attempt_at": None,
        "dispatch_last_error": None,
        "dispatch_next_attempt_at": now,
        "dispatched_at": None,
        "dispatch_exhausted_at": None,
    }


def test_dispatch_retry_policy_is_bounded() -> None:
    assert FLOW_DISPATCH_MAX_ATTEMPTS == 5
    assert [
        flow_dispatch_retry_delay_seconds(attempt_no=attempt_no)
        for attempt_no in range(1, FLOW_DISPATCH_MAX_ATTEMPTS + 1)
    ] == [30, 120, 300, 900, 900]

    with pytest.raises(ValueError, match="outside the bounded policy"):
        flow_dispatch_retry_delay_seconds(attempt_no=0)
    with pytest.raises(ValueError, match="outside the bounded policy"):
        flow_dispatch_retry_delay_seconds(attempt_no=6)


def test_dispatch_error_has_one_strict_secret_free_shape_per_kind() -> None:
    retryable = FlowRunDispatchError.from_kind(
        FlowRunDispatchErrorKind.EXECUTION_BACKEND_FAILURE
    )

    assert retryable.retryable is True
    assert "postgresql://secret@broker" not in retryable.message
    with pytest.raises(ValidationError):
        FlowRunDispatchError(
            kind=FlowRunDispatchErrorKind.EXECUTION_BACKEND_FAILURE,
            code="flow_dispatch_failed",
            retryable=True,
            message="postgresql://secret@broker",
        )


def test_dispatch_request_carries_existing_run_revision() -> None:
    run = _run(flow_id=uuid4(), tenant_id=uuid4()).model_copy(update={"revision": 7})

    assert build_flow_run_dispatch_request(run) == FlowRunUserDispatchRequest(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        run_revision=7,
        principal_user_id=run.principal_user_id,
    )


class _DispatchTransaction:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __aenter__(self):
        self.events.append("transaction_enter")

    async def __aexit__(self, exc_type, exc, tb):
        self.events.append("transaction_exit")
        return False


class _DispatchSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def begin(self) -> _DispatchTransaction:
        return _DispatchTransaction(self.events)


def _install_dispatch_dependencies(
    monkeypatch,
    *,
    run_repo,
    backend,
    terminalizer,
    events: list[str],
    audit_service: MagicMock | None = None,
) -> None:
    session = _DispatchSession(events)

    class _SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Container:
        def flow_run_repo(self):
            return run_repo

        def flow_execution_backend(self):
            return backend

        def flow_run_terminalizer(self):
            return terminalizer

        def audit_service(self):
            return audit_service

    monkeypatch.setattr(
        flow_dispatch_module.sessionmanager,
        "session",
        lambda: _SessionContext(),
    )
    monkeypatch.setattr(flow_dispatch_module, "Container", lambda session: _Container())


@pytest.mark.asyncio
async def test_manual_redrive_commits_audit_with_rearm_before_dispatch(
    monkeypatch,
) -> None:
    events: list[str] = []
    run = _run(flow_id=uuid4(), tenant_id=uuid4())
    run_repo = MagicMock()

    async def _rearm(**_kwargs):
        events.append("rearm")
        return run

    run_repo.rearm_exhausted_accepted_dispatch_for_redrive = AsyncMock(
        side_effect=_rearm
    )
    audit_service = MagicMock()

    async def _audit(**_kwargs):
        events.append("audit")
        return object()

    audit_service.log = AsyncMock(side_effect=_audit)
    _install_dispatch_dependencies(
        monkeypatch,
        run_repo=run_repo,
        backend=MagicMock(),
        terminalizer=MagicMock(),
        events=events,
        audit_service=audit_service,
    )

    async def _dispatch(**_kwargs):
        events.append("dispatch")
        return FlowRunDispatchNotClaimed(run=run)

    dispatch = AsyncMock(side_effect=_dispatch)
    monkeypatch.setattr(
        flow_dispatch_module,
        "dispatch_flow_run_recoverably_after_commit",
        dispatch,
    )

    metadata = {"target": {"id": str(run.id)}}
    result = await redrive_flow_run_recoverably_after_commit(
        run_id=run.id,
        tenant_id=run.tenant_id,
        expected_revision=run.revision,
        actor_id=run.principal_user_id,
        actor_type=ActorType.USER,
        actor_api_key_id=None,
        audit_metadata=metadata,
        expected_dispatch_exhausted_at=run.created_at,
    )

    assert isinstance(result, FlowRunDispatchNotClaimed)
    assert events == [
        "transaction_enter",
        "rearm",
        "audit",
        "transaction_exit",
        "dispatch",
    ]
    audit_kwargs = audit_service.log.await_args.kwargs
    assert audit_kwargs["metadata"] == {
        **metadata,
        "accepted_exhaustion_rearmed": True,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("audit_outcome", ["disabled", "error"])
async def test_manual_redrive_rolls_back_and_skips_dispatch_when_audit_is_unavailable(
    monkeypatch,
    audit_outcome: str,
) -> None:
    events: list[str] = []
    run = _run(flow_id=uuid4(), tenant_id=uuid4())
    run_repo = MagicMock()
    run_repo.rearm_exhausted_accepted_dispatch_for_redrive = AsyncMock(return_value=run)
    audit_service = MagicMock()
    audit_service.log = (
        AsyncMock(return_value=None)
        if audit_outcome == "disabled"
        else AsyncMock(side_effect=RuntimeError("audit write failed"))
    )
    _install_dispatch_dependencies(
        monkeypatch,
        run_repo=run_repo,
        backend=MagicMock(),
        terminalizer=MagicMock(),
        events=events,
        audit_service=audit_service,
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(
        flow_dispatch_module,
        "dispatch_flow_run_recoverably_after_commit",
        dispatch,
    )

    with pytest.raises(AuditLoggingUnavailableException) as exc_info:
        await redrive_flow_run_recoverably_after_commit(
            run_id=run.id,
            tenant_id=run.tenant_id,
            expected_revision=run.revision,
            actor_id=run.principal_user_id,
            actor_type=ActorType.USER,
            actor_api_key_id=None,
            audit_metadata={"target": {"id": str(run.id)}},
            expected_dispatch_exhausted_at=run.created_at,
        )

    assert exc_info.value.code == (
        FlowApiErrorCode.RUN_REDISPATCH_AUDIT_UNAVAILABLE.value
    )
    assert exc_info.value.context == {"audit_required": True}
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("generation_case", ["missing", "stale"])
async def test_manual_redrive_rejects_missing_or_stale_exhaustion_generation_without_audit(
    monkeypatch,
    generation_case: str,
) -> None:
    events: list[str] = []
    run = _run(flow_id=uuid4(), tenant_id=uuid4())
    current_exhausted_at = run.created_at + timedelta(minutes=1)
    expected_dispatch_exhausted_at = (
        None if generation_case == "missing" else run.created_at
    )
    run_repo = MagicMock()

    async def _conflict(**_kwargs):
        events.append("rearm")
        return FlowRunDispatchRedriveGenerationConflict(
            current_dispatch_exhausted_at=current_exhausted_at
        )

    run_repo.rearm_exhausted_accepted_dispatch_for_redrive = AsyncMock(
        side_effect=_conflict
    )
    audit_service = MagicMock()
    audit_service.log = AsyncMock()
    _install_dispatch_dependencies(
        monkeypatch,
        run_repo=run_repo,
        backend=MagicMock(),
        terminalizer=MagicMock(),
        events=events,
        audit_service=audit_service,
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(
        flow_dispatch_module,
        "dispatch_flow_run_recoverably_after_commit",
        dispatch,
    )

    with pytest.raises(FlowRunDispatchExhaustionGenerationConflictError) as exc_info:
        await redrive_flow_run_recoverably_after_commit(
            run_id=run.id,
            tenant_id=run.tenant_id,
            expected_revision=run.revision,
            actor_id=run.principal_user_id,
            actor_type=ActorType.USER,
            actor_api_key_id=None,
            audit_metadata={"target": {"id": str(run.id)}},
            expected_dispatch_exhausted_at=expected_dispatch_exhausted_at,
        )

    assert exc_info.value.current_dispatch_exhausted_at == current_exhausted_at
    assert events == ["transaction_enter", "rearm", "transaction_exit"]
    audit_service.log.assert_not_awaited()
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_coordinator_commits_claim_before_broker_and_records_acceptance(
    monkeypatch,
) -> None:
    events: list[str] = []
    run = _run(flow_id=uuid4(), tenant_id=uuid4())
    claimed = run.model_copy(
        update={
            "dispatch_attempt_count": 1,
            "dispatch_last_attempt_at": run.created_at,
            "dispatch_next_attempt_at": run.created_at + timedelta(seconds=30),
        }
    )
    accepted = claimed.model_copy(
        update={
            "dispatch_next_attempt_at": run.created_at + timedelta(seconds=120),
            "dispatched_at": run.created_at + timedelta(seconds=1),
        }
    )
    run_repo = MagicMock()
    run_repo.mark_dispatch_exhausted_if_due = AsyncMock(return_value=None)

    async def _claim(**_kwargs):
        events.append("claim")
        return claimed

    async def _record_accepted(**_kwargs):
        events.append("record_accepted")
        return accepted

    run_repo.claim_queued_run_for_dispatch = AsyncMock(side_effect=_claim)
    run_repo.record_dispatch_accepted = AsyncMock(side_effect=_record_accepted)
    backend = MagicMock()

    async def _dispatch(**_kwargs):
        events.append("broker_dispatch")

    backend.dispatch = AsyncMock(side_effect=_dispatch)
    terminalizer = MagicMock()
    terminalizer.terminalize_run = AsyncMock()
    _install_dispatch_dependencies(
        monkeypatch,
        run_repo=run_repo,
        backend=backend,
        terminalizer=terminalizer,
        events=events,
    )

    result = await dispatch_flow_run_recoverably_after_commit(
        run_id=run.id,
        tenant_id=run.tenant_id,
        expected_revision=run.revision,
    )

    assert isinstance(result, FlowRunDispatchAccepted)
    assert result.run is accepted
    assert result.run.dispatch_next_attempt_at == run.created_at + timedelta(
        seconds=120
    )
    assert events == [
        "transaction_enter",
        "transaction_exit",
        "transaction_enter",
        "claim",
        "transaction_exit",
        "broker_dispatch",
        "transaction_enter",
        "record_accepted",
        "transaction_exit",
    ]
    terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_coordinator_persists_certified_rejection_without_raw_cause(
    monkeypatch,
    caplog,
) -> None:
    events: list[str] = []
    run = _run(flow_id=uuid4(), tenant_id=uuid4())
    claimed = run.model_copy(update={"dispatch_attempt_count": 1})
    persisted_errors: list[FlowRunDispatchError] = []
    run_repo = MagicMock()
    run_repo.mark_dispatch_exhausted_if_due = AsyncMock(return_value=None)
    run_repo.claim_queued_run_for_dispatch = AsyncMock(return_value=claimed)

    async def _record_failure(*, error, **_kwargs):
        persisted_errors.append(error)
        return claimed.model_copy(update={"dispatch_last_error": error})

    run_repo.record_dispatch_failure = AsyncMock(side_effect=_record_failure)
    backend = MagicMock()
    backend.dispatch = AsyncMock(
        side_effect=FlowExecutionDispatchRejected("postgresql://credential@broker")
    )
    terminalizer = MagicMock()
    terminalizer.terminalize_run = AsyncMock()
    _install_dispatch_dependencies(
        monkeypatch,
        run_repo=run_repo,
        backend=backend,
        terminalizer=terminalizer,
        events=events,
    )

    result = await dispatch_flow_run_recoverably_after_commit(
        run_id=run.id,
        tenant_id=run.tenant_id,
        expected_revision=run.revision,
    )

    assert isinstance(result, FlowRunDispatchFailed)
    assert persisted_errors == [
        FlowRunDispatchError.from_kind(
            FlowRunDispatchErrorKind.EXECUTION_BACKEND_FAILURE
        )
    ]
    assert "credential" not in persisted_errors[0].message
    assert "credential" not in caplog.text
    terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_coordinator_terminalizes_invalid_principal_once(
    monkeypatch,
) -> None:
    events: list[str] = []
    run = _run(flow_id=uuid4(), tenant_id=uuid4())
    claimed = run.model_copy(
        update={
            "principal_type": None,
            "principal_user_id": None,
            "dispatch_attempt_count": 1,
        }
    )
    failed = claimed.model_copy(
        update={
            "dispatch_last_error": FlowRunDispatchError.from_kind(
                FlowRunDispatchErrorKind.INVALID_REQUEST
            ),
            "dispatch_exhausted_at": run.created_at,
        }
    )
    terminal_run = failed.model_copy(update={"status": FlowRunStatus.FAILED})
    run_repo = MagicMock()
    run_repo.mark_dispatch_exhausted_if_due = AsyncMock(return_value=None)
    run_repo.claim_queued_run_for_dispatch = AsyncMock(return_value=claimed)
    run_repo.record_dispatch_failure = AsyncMock(return_value=failed)
    backend = MagicMock()
    backend.dispatch = AsyncMock()
    terminalizer = MagicMock()
    terminalizer.terminalize_run = AsyncMock(
        return_value=SimpleNamespace(run=terminal_run)
    )
    _install_dispatch_dependencies(
        monkeypatch,
        run_repo=run_repo,
        backend=backend,
        terminalizer=terminalizer,
        events=events,
    )

    result = await dispatch_flow_run_recoverably_after_commit(
        run_id=run.id,
        tenant_id=run.tenant_id,
        expected_revision=run.revision,
    )

    assert isinstance(result, FlowRunDispatchInvalidRequest)
    assert result.run.status == FlowRunStatus.FAILED
    terminalizer.terminalize_run.assert_awaited_once()
    backend.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_coordinator_terminalizes_certified_final_rejection_once(
    monkeypatch,
) -> None:
    events: list[str] = []
    run = _run(flow_id=uuid4(), tenant_id=uuid4())
    claimed = run.model_copy(update={"dispatch_attempt_count": 5})
    exhausted = claimed.model_copy(update={"dispatch_exhausted_at": run.created_at})
    terminal_run = exhausted.model_copy(update={"status": FlowRunStatus.FAILED})
    run_repo = MagicMock()
    run_repo.mark_dispatch_exhausted_if_due = AsyncMock(return_value=None)
    run_repo.claim_queued_run_for_dispatch = AsyncMock(return_value=claimed)
    run_repo.record_dispatch_failure = AsyncMock(return_value=exhausted)
    backend = MagicMock()
    backend.dispatch = AsyncMock(
        side_effect=FlowExecutionDispatchRejected("broker rejected dispatch")
    )
    terminalizer = MagicMock()
    terminalizer.terminalize_run = AsyncMock(
        return_value=SimpleNamespace(run=terminal_run)
    )
    _install_dispatch_dependencies(
        monkeypatch,
        run_repo=run_repo,
        backend=backend,
        terminalizer=terminalizer,
        events=events,
    )

    result = await dispatch_flow_run_recoverably_after_commit(
        run_id=run.id,
        tenant_id=run.tenant_id,
        expected_revision=run.revision,
    )

    assert isinstance(result, FlowRunDispatchFailed)
    assert result.run.status == FlowRunStatus.FAILED
    terminalizer.terminalize_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_coordinator_keeps_final_ambiguous_exception_queued_and_exhausted(
    monkeypatch,
) -> None:
    events: list[str] = []
    run = _run(flow_id=uuid4(), tenant_id=uuid4())
    claimed = run.model_copy(
        update={"dispatch_attempt_count": FLOW_DISPATCH_MAX_ATTEMPTS}
    )
    exhausted = claimed.model_copy(
        update={
            "status": FlowRunStatus.QUEUED,
            "dispatch_last_error": None,
            "dispatch_next_attempt_at": None,
            "dispatch_exhausted_at": run.created_at,
        }
    )
    run_repo = MagicMock()
    run_repo.mark_dispatch_exhausted_if_due = AsyncMock(return_value=None)
    run_repo.claim_queued_run_for_dispatch = AsyncMock(return_value=claimed)
    run_repo.record_dispatch_outcome_unknown = AsyncMock(return_value=exhausted)
    run_repo.record_dispatch_failure = AsyncMock()
    backend = MagicMock()
    backend.dispatch = AsyncMock(side_effect=RuntimeError("transport outcome unknown"))
    terminalizer = MagicMock()
    terminalizer.terminalize_run = AsyncMock()
    _install_dispatch_dependencies(
        monkeypatch,
        run_repo=run_repo,
        backend=backend,
        terminalizer=terminalizer,
        events=events,
    )

    result = await dispatch_flow_run_recoverably_after_commit(
        run_id=run.id,
        tenant_id=run.tenant_id,
        expected_revision=run.revision,
    )

    assert isinstance(result, FlowRunDispatchOutcomeUnknown)
    assert result.run.status == FlowRunStatus.QUEUED
    assert result.run.dispatch_last_error is None
    assert result.run.dispatch_next_attempt_at is None
    assert result.run.dispatch_exhausted_at is not None
    run_repo.record_dispatch_outcome_unknown.assert_awaited_once()
    run_repo.record_dispatch_failure.assert_not_awaited()
    terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_coordinator_terminalizes_due_exhausted_epoch_once(
    monkeypatch,
) -> None:
    events: list[str] = []
    run = _run(flow_id=uuid4(), tenant_id=uuid4()).model_copy(
        update={
            "status": FlowRunStatus.QUEUED,
            "dispatch_attempt_count": FLOW_DISPATCH_MAX_ATTEMPTS,
            "dispatch_last_error": FlowRunDispatchError.from_kind(
                FlowRunDispatchErrorKind.EXECUTION_BACKEND_FAILURE
            ),
        }
    )
    exhausted = run.model_copy(update={"dispatch_exhausted_at": run.created_at})
    terminal_run = exhausted.model_copy(update={"status": FlowRunStatus.FAILED})
    run_repo = MagicMock()
    run_repo.mark_dispatch_exhausted_if_due = AsyncMock(return_value=exhausted)
    run_repo.claim_queued_run_for_dispatch = AsyncMock()
    backend = MagicMock()
    backend.dispatch = AsyncMock()
    terminalizer = MagicMock()
    terminalizer.terminalize_run = AsyncMock(
        return_value=SimpleNamespace(run=terminal_run)
    )
    _install_dispatch_dependencies(
        monkeypatch,
        run_repo=run_repo,
        backend=backend,
        terminalizer=terminalizer,
        events=events,
    )

    result = await dispatch_flow_run_recoverably_after_commit(
        run_id=run.id,
        tenant_id=run.tenant_id,
        expected_revision=run.revision,
    )

    assert isinstance(result, FlowRunDispatchExhausted)
    assert result.run.status == FlowRunStatus.FAILED
    terminalizer.terminalize_run.assert_awaited_once()
    terminal_error = terminalizer.terminalize_run.await_args.kwargs["error"]
    assert terminal_error.code == FlowApiErrorCode.RUN_DISPATCH_FAILED
    assert terminal_error.message == (
        "flow_dispatch_failed: Flow run dispatch exhausted its bounded attempts."
    )
    run_repo.claim_queued_run_for_dispatch.assert_not_awaited()
    backend.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_coordinator_keeps_accepted_due_exhaustion_queued(
    monkeypatch,
) -> None:
    events: list[str] = []
    run = _run(flow_id=uuid4(), tenant_id=uuid4())
    accepted = run.model_copy(
        update={
            "status": FlowRunStatus.QUEUED,
            "dispatch_attempt_count": FLOW_DISPATCH_MAX_ATTEMPTS,
            "dispatched_at": run.created_at,
        }
    )
    exhausted = accepted.model_copy(update={"dispatch_exhausted_at": run.created_at})
    run_repo = MagicMock()
    run_repo.mark_dispatch_exhausted_if_due = AsyncMock(return_value=exhausted)
    run_repo.claim_queued_run_for_dispatch = AsyncMock()
    backend = MagicMock()
    backend.dispatch = AsyncMock()
    terminalizer = MagicMock()
    terminalizer.terminalize_run = AsyncMock()
    _install_dispatch_dependencies(
        monkeypatch,
        run_repo=run_repo,
        backend=backend,
        terminalizer=terminalizer,
        events=events,
    )

    result = await dispatch_flow_run_recoverably_after_commit(
        run_id=run.id,
        tenant_id=run.tenant_id,
        expected_revision=run.revision,
    )

    assert isinstance(result, FlowRunDispatchExhausted)
    assert result.run.status == FlowRunStatus.QUEUED
    assert result.run.dispatch_exhausted_at is not None
    terminalizer.terminalize_run.assert_not_awaited()
    run_repo.claim_queued_run_for_dispatch.assert_not_awaited()
    backend.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_coordinator_keeps_outcome_unknown_exhaustion_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    run = _run(flow_id=uuid4(), tenant_id=uuid4())
    exhausted = run.model_copy(
        update={
            "status": FlowRunStatus.QUEUED,
            "dispatch_attempt_count": FLOW_DISPATCH_MAX_ATTEMPTS,
            "dispatch_exhausted_at": run.created_at,
            "dispatch_last_error": None,
        }
    )
    run_repo = MagicMock()
    run_repo.mark_dispatch_exhausted_if_due = AsyncMock(return_value=exhausted)
    run_repo.claim_queued_run_for_dispatch = AsyncMock()
    backend = MagicMock()
    backend.dispatch = AsyncMock()
    terminalizer = MagicMock()
    terminalizer.terminalize_run = AsyncMock()
    _install_dispatch_dependencies(
        monkeypatch,
        run_repo=run_repo,
        backend=backend,
        terminalizer=terminalizer,
        events=events,
    )

    result = await dispatch_flow_run_recoverably_after_commit(
        run_id=run.id,
        tenant_id=run.tenant_id,
        expected_revision=run.revision,
    )

    assert isinstance(result, FlowRunDispatchExhausted)
    assert result.run.status == FlowRunStatus.QUEUED
    terminalizer.terminalize_run.assert_not_awaited()
    run_repo.claim_queued_run_for_dispatch.assert_not_awaited()
    backend.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_coordinator_leaves_prescheduled_recovery_when_accept_record_fails(
    monkeypatch,
) -> None:
    events: list[str] = []
    run = _run(flow_id=uuid4(), tenant_id=uuid4())
    claimed = run.model_copy(
        update={
            "dispatch_attempt_count": 1,
            "dispatch_next_attempt_at": run.created_at + timedelta(seconds=30),
        }
    )
    run_repo = MagicMock()
    run_repo.mark_dispatch_exhausted_if_due = AsyncMock(return_value=None)
    run_repo.claim_queued_run_for_dispatch = AsyncMock(return_value=claimed)
    run_repo.record_dispatch_accepted = AsyncMock(
        side_effect=RuntimeError("local success write failed")
    )
    backend = MagicMock()
    backend.dispatch = AsyncMock()
    terminalizer = MagicMock()
    terminalizer.terminalize_run = AsyncMock()
    _install_dispatch_dependencies(
        monkeypatch,
        run_repo=run_repo,
        backend=backend,
        terminalizer=terminalizer,
        events=events,
    )

    with pytest.raises(RuntimeError, match="local success write failed"):
        await dispatch_flow_run_recoverably_after_commit(
            run_id=run.id,
            tenant_id=run.tenant_id,
            expected_revision=run.revision,
        )

    assert claimed.dispatch_next_attempt_at is not None
    backend.dispatch.assert_awaited_once()
    terminalizer.terminalize_run.assert_not_awaited()
