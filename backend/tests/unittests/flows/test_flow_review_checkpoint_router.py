from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    MagicMock,
)
from uuid import uuid4

import pytest

from eneo.audit.domain.action_types import ActionType
from eneo.authentication.auth_dependencies import ScopeFilter
from eneo.flows.api import flow_access_context as flow_access_context_module
from eneo.flows.api import flow_run_review_router as router_module
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_models import (
    FlowRunReviewCheckpointApproveRequest,
    FlowRunReviewCheckpointEditRequest,
    FlowRunReviewCheckpointRejectRequest,
    FlowRunReviewCheckpointResumeRequest,
)
from eneo.flows.api.flow_run_review_router import (
    approve_flow_run_review_checkpoint,
    edit_flow_run_review_checkpoint,
    get_active_flow_run_review_checkpoint,
    reject_flow_run_review_checkpoint,
    resume_flow_run_review_checkpoint,
)
from eneo.flows.application.flow_dispatch import (
    dispatch_flow_run_recoverably_after_commit,
)
from eneo.flows.application.flow_run_review_checkpoint_service import (
    FlowReviewCheckpointApproval,
)
from eneo.flows.domain.flow import FlowRunStatus, FlowStepAttempt, FlowStepResult
from eneo.flows.enums import (
    FlowRunReviewCheckpointState,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import AuditLoggingUnavailableException
from tests.unittests.flows.test_flow_router import (
    _disable_flow_scope_filter,
    _enable_explicit_transaction,
    _enable_review_checkpoint_route_context,
    _enable_space_access,
    _flow,
    _RecordingBackgroundTasks,
    _review_checkpoint,
    _run,
)


def _record_review_checkpoint_public(monkeypatch, events: list[str]):
    async def _present_review_checkpoint(*, container, checkpoint):
        events.append("present_review_checkpoint")
        checkpoint_for_public = checkpoint.model_copy(
            update={
                "requester_user_id": uuid4(),
                "decided_by_user_id": uuid4(),
            }
        )
        return FlowAssembler().to_review_checkpoint_public(checkpoint_for_public)

    monkeypatch.setattr(
        router_module,
        "_present_review_checkpoint",
        _present_review_checkpoint,
    )


class _CommitFailureTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc is None:
            raise RuntimeError("commit failed")
        return False


def _enable_citation_presentation(monkeypatch, container, *, ctx, edited_at=None):
    source_id = "11111111-1111-1111-1111-111111111111"
    now = datetime.now(timezone.utc)
    step_result = FlowStepResult(
        id=uuid4(),
        flow_run_id=ctx.run.id,
        flow_id=ctx.flow_id,
        tenant_id=ctx.run.tenant_id,
        step_id=ctx.checkpoint.step_id,
        step_order=ctx.checkpoint.step_order,
        current_attempt_no=ctx.checkpoint.attempt_no,
        input_payload_json={
            "rag": {
                "citation_sources": [
                    {
                        "id": source_id,
                        "title": "Review source",
                        "source_container_name_raw": "Review docs",
                    }
                ]
            }
        },
        status=FlowStepResultStatus.COMPLETED,
        created_at=now,
        updated_at=now,
    )
    attempt = FlowStepAttempt(
        id=uuid4(),
        flow_run_id=ctx.run.id,
        flow_id=ctx.flow_id,
        tenant_id=ctx.run.tenant_id,
        step_id=ctx.checkpoint.step_id,
        step_order=ctx.checkpoint.step_order,
        attempt_no=ctx.checkpoint.attempt_no,
        status=FlowStepAttemptStatus.COMPLETED,
        provenance_json={
            "schema_version": "flow-attempt-provenance.v3",
            "citations": {
                "citation_compliance": "observed",
                "cited_source_ids": [source_id],
                "unknown_citation_ids": [],
                "upstream_grounded_step_orders": [],
            },
        },
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )
    run_repo = AsyncMock()
    run_repo.get.return_value = ctx.run
    run_repo.get_step_result.return_value = step_result
    run_repo.get_step_attempt.return_value = attempt
    container.flow_run_repo.return_value = run_repo
    container.flow_version_repo.return_value = AsyncMock()
    definition = SimpleNamespace(
        runtime_steps=lambda: [
            SimpleNamespace(
                step_id=ctx.checkpoint.step_id,
                step_order=ctx.checkpoint.step_order,
                output_config={"citation_mode": "inline_inref_sidecar"},
            )
        ]
    )
    monkeypatch.setattr(
        router_module,
        "load_published_definition",
        AsyncMock(return_value=definition),
    )
    checkpoint = ctx.checkpoint.model_copy(
        update={
            "state": (
                FlowRunReviewCheckpointState.EDITED
                if edited_at is not None
                else FlowRunReviewCheckpointState.AWAITING_REVIEW
            ),
            "requester_user_id": uuid4(),
            "decided_by_user_id": uuid4() if edited_at is not None else None,
            "decided_by_principal_type": (
                ctx.checkpoint.decided_by_principal_type
                if edited_at is not None
                else None
            ),
            "edited_at": edited_at,
        }
    )
    return checkpoint


@pytest.mark.asyncio
async def test_active_review_checkpoint_includes_current_citation_summary(monkeypatch):
    container = MagicMock()
    ctx = _enable_review_checkpoint_route_context(container)
    checkpoint = _enable_citation_presentation(
        monkeypatch,
        container,
        ctx=ctx,
    )
    ctx.review_service.get_active_review_checkpoint.return_value = checkpoint
    _disable_flow_scope_filter(monkeypatch)

    response = await get_active_flow_run_review_checkpoint(
        id=ctx.flow_id,
        run_id=ctx.run.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        container=container,
    )

    assert response is not None
    assert response.citation_summary is not None
    assert response.citation_summary.status == "observed"
    assert response.citation_summary.stale_after_edit is False
    ctx.run_service.get_run.assert_awaited_once_with(
        run_id=ctx.run.id,
        flow_id=ctx.flow_id,
        access_kind="content",
    )
    audit_event = container.audit_service.return_value.log.await_args.kwargs
    assert audit_event["action"] is ActionType.FLOW_EVIDENCE_VIEWED
    assert audit_event["required"] is True
    assert audit_event["metadata"]["extra"] == {
        "evidence_detail": "active_review_checkpoint",
        "checkpoint_present": True,
        "flow_id": str(ctx.flow_id),
        "run_id": str(ctx.run.id),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["insert", "commit"])
async def test_active_review_checkpoint_exposes_no_payload_when_audit_fails(
    monkeypatch,
    failure_kind: str,
) -> None:
    container = MagicMock()
    ctx = _enable_review_checkpoint_route_context(container)
    ctx.review_service.get_active_review_checkpoint.return_value = ctx.checkpoint
    _record_review_checkpoint_public(monkeypatch, ctx.events)
    _disable_flow_scope_filter(monkeypatch)
    if failure_kind == "insert":
        container.audit_service.return_value.log.side_effect = RuntimeError(
            "audit insert failed"
        )
    else:
        container.session.return_value.begin.return_value = _CommitFailureTransaction()

    with pytest.raises(AuditLoggingUnavailableException) as exc_info:
        await get_active_flow_run_review_checkpoint(
            id=ctx.flow_id,
            run_id=ctx.run.id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )

    assert exc_info.value.code == FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED.value
    assert exc_info.value.context == {"audit_required": True}


@pytest.mark.asyncio
async def test_edit_response_marks_citation_summary_stale_without_refetch(monkeypatch):
    container = MagicMock()
    ctx = _enable_review_checkpoint_route_context(container)
    checkpoint = _enable_citation_presentation(
        monkeypatch,
        container,
        ctx=ctx,
        edited_at=datetime.now(timezone.utc),
    )
    ctx.review_service.edit_review_checkpoint.return_value = checkpoint
    _disable_flow_scope_filter(monkeypatch)

    response = await edit_flow_run_review_checkpoint(
        id=ctx.flow_id,
        run_id=ctx.run.id,
        checkpoint_id=ctx.checkpoint.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        review_in=FlowRunReviewCheckpointEditRequest(
            expected_checkpoint_revision=ctx.checkpoint.revision,
            edited_value="reviewed",
        ),
        container=container,
    )

    assert response.citation_summary is not None
    assert response.citation_summary.stale_after_edit is True


@pytest.mark.asyncio
async def test_resume_review_checkpoint_schedules_dispatch_after_commit(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    step_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id).model_copy(
        update={"status": FlowRunStatus.QUEUED}
    )
    checkpoint = _review_checkpoint(
        flow_id=flow_id,
        run_id=run.id,
        tenant_id=user.tenant_id,
        step_id=step_id,
    )
    events: list[str] = []

    run_service = AsyncMock()
    review_service = AsyncMock()
    review_service.resume_review_checkpoint.return_value = SimpleNamespace(
        checkpoint=checkpoint,
        run=run,
        accepted=True,
    )
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_run_service.return_value = run_service
    container.flow_run_review_checkpoint_service.return_value = review_service
    container.flow_service.return_value = flow_service
    container.user.return_value = user
    _enable_space_access(container)
    _enable_explicit_transaction(container, events)
    _record_review_checkpoint_public(monkeypatch, events)
    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    background_tasks = _RecordingBackgroundTasks(events)
    response = await resume_flow_run_review_checkpoint(
        id=flow_id,
        run_id=run.id,
        checkpoint_id=checkpoint.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        review_in=FlowRunReviewCheckpointResumeRequest(
            expected_checkpoint_revision=checkpoint.revision
        ),
        background_tasks=background_tasks,
        idempotency_key="resume-review-checkpoint",
        container=container,
    )

    assert response.run.id == run.id
    assert response.checkpoint.id == checkpoint.id
    assert events == [
        "transaction_enter",
        "present_review_checkpoint",
        "transaction_exit",
        "add_task",
    ]
    assert len(background_tasks.tasks) == 1
    scheduled = background_tasks.tasks[0]
    assert scheduled.func is dispatch_flow_run_recoverably_after_commit
    assert scheduled.kwargs == {
        "run_id": run.id,
        "tenant_id": user.tenant_id,
        "expected_revision": run.revision,
    }


@pytest.mark.asyncio
async def test_edit_review_checkpoint_builds_response_inside_transaction(monkeypatch):
    container = MagicMock()
    ctx = _enable_review_checkpoint_route_context(container)
    _record_review_checkpoint_public(monkeypatch, ctx.events)

    async def _edit_review_checkpoint(**_kwargs):
        ctx.events.append("edit_review_checkpoint")
        return ctx.checkpoint

    ctx.review_service.edit_review_checkpoint.side_effect = _edit_review_checkpoint
    _disable_flow_scope_filter(monkeypatch)

    response = await edit_flow_run_review_checkpoint(
        id=ctx.flow_id,
        run_id=ctx.run.id,
        checkpoint_id=ctx.checkpoint.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        review_in=FlowRunReviewCheckpointEditRequest(
            expected_checkpoint_revision=ctx.checkpoint.revision,
            edited_value="reviewed",
        ),
        container=container,
    )

    assert response.id == ctx.checkpoint.id
    assert ctx.events == [
        "transaction_enter",
        "edit_review_checkpoint",
        "present_review_checkpoint",
        "transaction_exit",
    ]
    ctx.review_service.edit_review_checkpoint.assert_awaited_once_with(
        flow_id=ctx.flow_id,
        run_id=ctx.run.id,
        checkpoint_id=ctx.checkpoint.id,
        expected_checkpoint_revision=ctx.checkpoint.revision,
        edited_value="reviewed",
    )


@pytest.mark.asyncio
async def test_approve_review_checkpoint_builds_response_inside_transaction(
    monkeypatch,
):
    container = MagicMock()
    ctx = _enable_review_checkpoint_route_context(container)
    _record_review_checkpoint_public(monkeypatch, ctx.events)

    async def _approve_review_checkpoint(**_kwargs):
        ctx.events.append("approve_review_checkpoint")
        return FlowReviewCheckpointApproval(
            checkpoint=ctx.checkpoint, corrections_fold=None
        )

    ctx.review_service.approve_review_checkpoint.side_effect = (
        _approve_review_checkpoint
    )
    _disable_flow_scope_filter(monkeypatch)

    response = await approve_flow_run_review_checkpoint(
        id=ctx.flow_id,
        run_id=ctx.run.id,
        checkpoint_id=ctx.checkpoint.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        review_in=FlowRunReviewCheckpointApproveRequest(
            expected_checkpoint_revision=ctx.checkpoint.revision
        ),
        container=container,
    )

    assert response.id == ctx.checkpoint.id
    assert ctx.events == [
        "transaction_enter",
        "approve_review_checkpoint",
        "present_review_checkpoint",
        "transaction_exit",
    ]
    ctx.review_service.approve_review_checkpoint.assert_awaited_once_with(
        flow_id=ctx.flow_id,
        run_id=ctx.run.id,
        checkpoint_id=ctx.checkpoint.id,
        expected_checkpoint_revision=ctx.checkpoint.revision,
    )


@pytest.mark.asyncio
async def test_reject_review_checkpoint_builds_response_inside_transaction(monkeypatch):
    container = MagicMock()
    ctx = _enable_review_checkpoint_route_context(container)
    _record_review_checkpoint_public(monkeypatch, ctx.events)

    async def _reject_review_checkpoint(**_kwargs):
        ctx.events.append("reject_review_checkpoint")
        return ctx.checkpoint

    ctx.review_service.reject_review_checkpoint.side_effect = _reject_review_checkpoint
    _disable_flow_scope_filter(monkeypatch)

    response = await reject_flow_run_review_checkpoint(
        id=ctx.flow_id,
        run_id=ctx.run.id,
        checkpoint_id=ctx.checkpoint.id,
        request=SimpleNamespace(state=SimpleNamespace()),
        review_in=FlowRunReviewCheckpointRejectRequest(
            expected_checkpoint_revision=ctx.checkpoint.revision,
            reason="Needs correction",
        ),
        container=container,
    )

    assert response.id == ctx.checkpoint.id
    assert ctx.events == [
        "transaction_enter",
        "reject_review_checkpoint",
        "present_review_checkpoint",
        "transaction_exit",
    ]
    ctx.review_service.reject_review_checkpoint.assert_awaited_once_with(
        flow_id=ctx.flow_id,
        run_id=ctx.run.id,
        checkpoint_id=ctx.checkpoint.id,
        expected_checkpoint_revision=ctx.checkpoint.revision,
        reason="Needs correction",
    )
