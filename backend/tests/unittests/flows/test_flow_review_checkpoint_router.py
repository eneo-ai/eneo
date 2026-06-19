from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    MagicMock,
)
from uuid import uuid4

import pytest

from intric.authentication.auth_dependencies import ScopeFilter
from intric.flows.api import flow_access_context as flow_access_context_module
from intric.flows.api import flow_run_execution_router as router_module
from intric.flows.api.flow_assembler import FlowAssembler
from intric.flows.api.flow_models import (
    FlowRunReviewCheckpointApproveRequest,
    FlowRunReviewCheckpointEditRequest,
    FlowRunReviewCheckpointRejectRequest,
    FlowRunReviewCheckpointResumeRequest,
)
from intric.flows.api.flow_run_execution_router import (
    approve_flow_run_review_checkpoint,
    edit_flow_run_review_checkpoint,
    reject_flow_run_review_checkpoint,
    resume_flow_run_review_checkpoint,
)
from intric.flows.application.flow_dispatch import (
    dispatch_flow_run_recoverably_after_commit,
)
from intric.flows.domain.flow import FlowRunStatus
from intric.flows.flow_run_dispatch_request import FlowRunUserDispatchRequest
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

    def _build_dispatch_request(_run):
        events.append("build_dispatch_request")
        return FlowRunUserDispatchRequest(
            run_id=run.id,
            flow_id=flow_id,
            tenant_id=user.tenant_id,
            principal_user_id=user.id,
        )

    run_service = AsyncMock()
    review_service = AsyncMock()
    review_service.resume_review_checkpoint.return_value = SimpleNamespace(
        checkpoint=checkpoint,
        run=run,
        accepted=True,
    )
    run_service.build_dispatch_request = MagicMock(side_effect=_build_dispatch_request)
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
        "build_dispatch_request",
        "present_review_checkpoint",
        "transaction_exit",
        "add_task",
    ]
    assert len(background_tasks.tasks) == 1
    scheduled = background_tasks.tasks[0]
    assert scheduled.func is dispatch_flow_run_recoverably_after_commit
    assert scheduled.kwargs == {
        "request": FlowRunUserDispatchRequest(
            run_id=run.id,
            flow_id=flow_id,
            tenant_id=user.tenant_id,
            principal_user_id=user.id,
        )
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
            current_payload_json={"text": "reviewed"},
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
        current_payload_json={"text": "reviewed"},
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
        return ctx.checkpoint

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
