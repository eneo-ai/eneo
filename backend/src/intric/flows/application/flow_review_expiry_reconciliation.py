from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from intric.flows.application.flow_run_terminalization import FlowRunTerminalizer
from intric.flows.domain.flow import FlowRunStatus
from intric.flows.domain.flow_run_exceptions import FlowRunNotFoundError
from intric.flows.enums import FlowRunLifecycleSource
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.flow_review_expiry_policy import (
    FLOW_REVIEW_EXPIRED_TERMINAL_MESSAGE,
)
from intric.flows.flow_run_error import FlowRunError
from intric.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)

_EXPIRED_CHECKPOINT_RECONCILE_BATCH_SIZE = 10


class FlowReviewExpiryReconciler:
    def __init__(
        self,
        flow_run_review_checkpoint_repo: FlowRunReviewCheckpointRepository,
        flow_run_terminalizer: FlowRunTerminalizer,
    ):
        self.flow_run_review_checkpoint_repo = flow_run_review_checkpoint_repo
        self.flow_run_terminalizer = flow_run_terminalizer

    async def reconcile_next_expired_checkpoint(self, *, tenant_id: UUID) -> int:
        expires_before = datetime.now(timezone.utc)
        expired_checkpoints = (
            await self.flow_run_review_checkpoint_repo.list_expired_review_checkpoints(
                tenant_id=tenant_id,
                expires_before=expires_before,
                limit=_EXPIRED_CHECKPOINT_RECONCILE_BATCH_SIZE,
            )
        )
        for checkpoint in expired_checkpoints:
            try:
                expired = await self.flow_run_review_checkpoint_repo.expire_review_checkpoint_for_reconciliation(
                    checkpoint_id=checkpoint.id,
                    flow_run_id=checkpoint.flow_run_id,
                    tenant_id=tenant_id,
                    expires_before=expires_before,
                )
            except FlowRunNotFoundError:
                continue
            if expired is None:
                continue
            try:
                result = await self.flow_run_terminalizer.terminalize_run(
                    run_id=expired.flow_run_id,
                    tenant_id=tenant_id,
                    target_status=FlowRunStatus.CANCELLED,
                    source=FlowRunLifecycleSource.REVIEW_EXPIRED,
                    error=FlowRunError.from_source(
                        FlowRunLifecycleSource.REVIEW_EXPIRED,
                        code=FlowApiErrorCode.REVIEW_EXPIRED,
                        message=FLOW_REVIEW_EXPIRED_TERMINAL_MESSAGE,
                    ),
                    cancelled_at=datetime.now(timezone.utc),
                )
            except FlowRunNotFoundError:
                continue
            if result.did_transition:
                return 1
        return 0
