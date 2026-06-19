from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.application.flow_review_expiry_reconciliation import (
    FlowReviewExpiryReconciler,
)
from intric.flows.domain.flow import FlowRunStatus
from intric.flows.domain.flow_run_exceptions import FlowRunNotFoundError
from intric.flows.enums import FlowRunLifecycleSource


@pytest.mark.asyncio
async def test_reconcile_next_expired_checkpoint_expires_checkpoint_then_cancels_run():
    tenant_id = uuid4()
    checkpoint = SimpleNamespace(id=uuid4(), flow_run_id=uuid4())
    expired_checkpoint = SimpleNamespace(id=checkpoint.id, flow_run_id=uuid4())
    checkpoint_repo = AsyncMock()
    checkpoint_repo.list_expired_review_checkpoints.return_value = [checkpoint]
    checkpoint_repo.expire_review_checkpoint_for_reconciliation.return_value = (
        expired_checkpoint
    )
    terminalizer = AsyncMock()
    terminalizer.terminalize_run.return_value = SimpleNamespace(did_transition=True)
    reconciler = FlowReviewExpiryReconciler(
        flow_run_review_checkpoint_repo=checkpoint_repo,
        flow_run_terminalizer=terminalizer,
    )

    count = await reconciler.reconcile_next_expired_checkpoint(tenant_id=tenant_id)

    assert count == 1
    checkpoint_repo.list_expired_review_checkpoints.assert_awaited_once()
    checkpoint_repo.expire_review_checkpoint_for_reconciliation.assert_awaited_once()
    assert (
        checkpoint_repo.expire_review_checkpoint_for_reconciliation.await_args.kwargs[
            "flow_run_id"
        ]
        == checkpoint.flow_run_id
    )
    terminalizer.terminalize_run.assert_awaited_once()
    terminal_kwargs = terminalizer.terminalize_run.await_args.kwargs
    assert terminal_kwargs["run_id"] == expired_checkpoint.flow_run_id
    assert terminal_kwargs["tenant_id"] == tenant_id
    assert terminal_kwargs["target_status"] == FlowRunStatus.CANCELLED
    assert terminal_kwargs["source"] == FlowRunLifecycleSource.REVIEW_EXPIRED
    assert terminal_kwargs["error"].code == "flow_review_expired"
    assert terminal_kwargs["error"].message.startswith("flow_review_expired:")


@pytest.mark.asyncio
async def test_reconcile_next_expired_checkpoint_skips_lost_expiry_race():
    tenant_id = uuid4()
    checkpoint = SimpleNamespace(id=uuid4(), flow_run_id=uuid4())
    checkpoint_repo = AsyncMock()
    checkpoint_repo.list_expired_review_checkpoints.return_value = [checkpoint]
    checkpoint_repo.expire_review_checkpoint_for_reconciliation.return_value = None
    terminalizer = AsyncMock()
    reconciler = FlowReviewExpiryReconciler(
        flow_run_review_checkpoint_repo=checkpoint_repo,
        flow_run_terminalizer=terminalizer,
    )

    count = await reconciler.reconcile_next_expired_checkpoint(tenant_id=tenant_id)

    assert count == 0
    terminalizer.terminalize_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_next_expired_checkpoint_skips_missing_parent_run_and_continues():
    tenant_id = uuid4()
    missing_parent = SimpleNamespace(id=uuid4(), flow_run_id=uuid4())
    next_checkpoint = SimpleNamespace(id=uuid4(), flow_run_id=uuid4())
    expired_checkpoint = SimpleNamespace(
        id=next_checkpoint.id,
        flow_run_id=next_checkpoint.flow_run_id,
    )
    checkpoint_repo = AsyncMock()
    checkpoint_repo.list_expired_review_checkpoints.return_value = [
        missing_parent,
        next_checkpoint,
    ]
    checkpoint_repo.expire_review_checkpoint_for_reconciliation.side_effect = [
        FlowRunNotFoundError(
            run_id=missing_parent.flow_run_id,
            tenant_id=tenant_id,
        ),
        expired_checkpoint,
    ]
    terminalizer = AsyncMock()
    terminalizer.terminalize_run.return_value = SimpleNamespace(did_transition=True)
    reconciler = FlowReviewExpiryReconciler(
        flow_run_review_checkpoint_repo=checkpoint_repo,
        flow_run_terminalizer=terminalizer,
    )

    count = await reconciler.reconcile_next_expired_checkpoint(tenant_id=tenant_id)

    assert count == 1
    assert checkpoint_repo.expire_review_checkpoint_for_reconciliation.await_count == 2
    terminalizer.terminalize_run.assert_awaited_once()
    assert terminalizer.terminalize_run.await_args.kwargs["run_id"] == (
        next_checkpoint.flow_run_id
    )


@pytest.mark.asyncio
async def test_reconcile_next_expired_checkpoint_skips_terminalizer_missing_run_and_continues():
    tenant_id = uuid4()
    deleted_after_expiry = SimpleNamespace(id=uuid4(), flow_run_id=uuid4())
    next_checkpoint = SimpleNamespace(id=uuid4(), flow_run_id=uuid4())
    expired_deleted_checkpoint = SimpleNamespace(
        id=deleted_after_expiry.id,
        flow_run_id=deleted_after_expiry.flow_run_id,
    )
    expired_next_checkpoint = SimpleNamespace(
        id=next_checkpoint.id,
        flow_run_id=next_checkpoint.flow_run_id,
    )
    checkpoint_repo = AsyncMock()
    checkpoint_repo.list_expired_review_checkpoints.return_value = [
        deleted_after_expiry,
        next_checkpoint,
    ]
    checkpoint_repo.expire_review_checkpoint_for_reconciliation.side_effect = [
        expired_deleted_checkpoint,
        expired_next_checkpoint,
    ]
    terminalizer = AsyncMock()
    terminalizer.terminalize_run.side_effect = [
        FlowRunNotFoundError(
            run_id=deleted_after_expiry.flow_run_id,
            tenant_id=tenant_id,
        ),
        SimpleNamespace(did_transition=True),
    ]
    reconciler = FlowReviewExpiryReconciler(
        flow_run_review_checkpoint_repo=checkpoint_repo,
        flow_run_terminalizer=terminalizer,
    )

    count = await reconciler.reconcile_next_expired_checkpoint(tenant_id=tenant_id)

    assert count == 1
    assert checkpoint_repo.expire_review_checkpoint_for_reconciliation.await_count == 2
    assert terminalizer.terminalize_run.await_count == 2
    assert terminalizer.terminalize_run.await_args.kwargs["run_id"] == (
        next_checkpoint.flow_run_id
    )
