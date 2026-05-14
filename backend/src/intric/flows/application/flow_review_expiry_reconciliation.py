from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from intric.flows.application.flow_run_terminalization import FlowRunTerminalizer
from intric.flows.domain.flow import FlowRunStatus
from intric.flows.enums import FlowRunLifecycleSource
from intric.flows.flow_review_expiry_policy import (
    FLOW_REVIEW_EXPIRED,
    FLOW_REVIEW_EXPIRED_TERMINAL_MESSAGE,
)
from intric.flows.infrastructure.flow_run_repo import FlowRunRepository


class FlowReviewExpiryReconciler:
    def __init__(
        self,
        flow_run_repo: FlowRunRepository,
        flow_run_terminalizer: FlowRunTerminalizer,
    ):
        self.flow_run_repo = flow_run_repo
        self.flow_run_terminalizer = flow_run_terminalizer

    async def reconcile_next_expired_checkpoint(self, *, tenant_id: UUID) -> int:
        expires_before = datetime.now(timezone.utc)
        expired_checkpoints = await self.flow_run_repo.list_expired_review_checkpoints(
            tenant_id=tenant_id,
            expires_before=expires_before,
            limit=1,
        )
        for checkpoint in expired_checkpoints:
            expired = (
                await self.flow_run_repo.expire_review_checkpoint_for_reconciliation(
                    checkpoint_id=checkpoint.id,
                    tenant_id=tenant_id,
                    expires_before=expires_before,
                )
            )
            if expired is None:
                continue
            result = await self.flow_run_terminalizer.terminalize_run(
                run_id=expired.flow_run_id,
                tenant_id=tenant_id,
                target_status=FlowRunStatus.CANCELLED,
                source=FlowRunLifecycleSource.REVIEW_EXPIRED,
                error_code=FLOW_REVIEW_EXPIRED,
                error_message=FLOW_REVIEW_EXPIRED_TERMINAL_MESSAGE,
                cancelled_at=datetime.now(timezone.utc),
            )
            if result.did_transition:
                return 1
        return 0
