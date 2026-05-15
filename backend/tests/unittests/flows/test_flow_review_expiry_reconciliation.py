from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.application.flow_review_expiry_reconciliation import (
    FlowReviewExpiryReconciler,
)
from intric.flows.domain.flow import FlowRunStatus
from intric.flows.enums import FlowRunLifecycleSource


@pytest.mark.asyncio
async def test_reconcile_next_expired_checkpoint_expires_checkpoint_then_cancels_run():
    tenant_id = uuid4()
    checkpoint = SimpleNamespace(id=uuid4())
    expired_checkpoint = SimpleNamespace(id=checkpoint.id, flow_run_id=uuid4())
    flow_run_repo = AsyncMock()
    flow_run_repo.list_expired_review_checkpoints.return_value = [checkpoint]
    flow_run_repo.expire_review_checkpoint_for_reconciliation.return_value = (
        expired_checkpoint
    )
    terminalizer = AsyncMock()
    terminalizer.terminalize_run.return_value = SimpleNamespace(did_transition=True)
    reconciler = FlowReviewExpiryReconciler(
        flow_run_repo=flow_run_repo,
        flow_run_terminalizer=terminalizer,
    )

    count = await reconciler.reconcile_next_expired_checkpoint(tenant_id=tenant_id)

    assert count == 1
    flow_run_repo.list_expired_review_checkpoints.assert_awaited_once()
    flow_run_repo.expire_review_checkpoint_for_reconciliation.assert_awaited_once()
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
    checkpoint = SimpleNamespace(id=uuid4())
    flow_run_repo = AsyncMock()
    flow_run_repo.list_expired_review_checkpoints.return_value = [checkpoint]
    flow_run_repo.expire_review_checkpoint_for_reconciliation.return_value = None
    terminalizer = AsyncMock()
    reconciler = FlowReviewExpiryReconciler(
        flow_run_repo=flow_run_repo,
        flow_run_terminalizer=terminalizer,
    )

    count = await reconciler.reconcile_next_expired_checkpoint(tenant_id=tenant_id)

    assert count == 0
    terminalizer.terminalize_run.assert_not_awaited()
