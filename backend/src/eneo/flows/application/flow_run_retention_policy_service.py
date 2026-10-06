from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.data_retention.application.retention_runner import is_retention_timeout
from eneo.data_retention.application.retention_sql_limits import (
    retention_request_sql_limits,
)
from eneo.data_retention.domain.retention import RETENTION_STALE_AFTER
from eneo.data_retention.infrastructure.retention_job_run_repo import (
    RetentionJobRunRepository,
)
from eneo.flows.application.flow_retention_authz import (
    require_retention_manage,
    require_retention_view,
)
from eneo.flows.application.flow_run_history_deletion import PurgeScope
from eneo.flows.application.flow_run_history_purge import FlowRunHistoryExplicitPurge
from eneo.flows.domain.flow_retention_hold import FlowRetentionHoldReviewLimit
from eneo.flows.domain.flow_run_history_deletion_status import (
    FlowRetentionStatusUnavailableError,
    FlowRunHistoryDeletionStatus,
    FlowRunHistoryOverdueStatus,
    FlowRunHistoryReceiptStatus,
    RetentionExecutionStatus,
    RetentionTaskStatus,
)
from eneo.flows.domain.flow_run_retention_policy import (
    FLOW_RETENTION_AUTO_DELETE_UNAVAILABLE_CODE,
    FLOW_RETENTION_DAYS_ABOVE_MAXIMUM_CODE,
    FLOW_RETENTION_REASON_REQUIRED_CODE,
    FlowRunRetentionFlowTargetPage,
    FlowRunRetentionMode,
    FlowRunRetentionPolicy,
    FlowRunRetentionPolicySettings,
    FlowRunRetentionReviewCursor,
    FlowRunRetentionReviewPage,
    FlowRunRetentionScope,
    FlowRunRetentionSpaceTargetPage,
    effective_flow_run_retention_policy,
    flow_run_retention_change_postpones_deletion,
)
from eneo.flows.infrastructure.flow_run_history_due_repo import (
    FlowRunHistoryDueRepository,
)
from eneo.flows.infrastructure.flow_run_retention_policy_repo import (
    FlowRunRetentionPolicyChange,
    FlowRunRetentionPolicyRepository,
)
from eneo.flows.runtime.live_transcription.repository import LiveTranscriptRepository
from eneo.main.config import get_settings
from eneo.main.exceptions import BadRequestException
from eneo.settings.settings import (
    FlowRunHistoryPurgeBlockedPublic,
    FlowRunHistoryPurgePublic,
)
from eneo.users.user import UserInDB


class FlowRunRetentionPolicyService:
    def __init__(
        self,
        *,
        user: UserInDB,
        repository: FlowRunRetentionPolicyRepository,
        audit_service: AuditService,
    ) -> None:
        self.user = user
        self.repository = repository
        self.audit_service = audit_service

    async def get_organization(self) -> FlowRunRetentionPolicySettings:
        require_retention_view(self.user)
        return await self.repository.get_organization(tenant_id=self.user.tenant_id)

    async def list_space_targets(
        self,
        *,
        limit: int,
        offset: int,
    ) -> FlowRunRetentionSpaceTargetPage:
        require_retention_view(self.user)
        return await self.repository.list_space_targets(
            tenant_id=self.user.tenant_id,
            limit=limit,
            offset=offset,
        )

    async def list_flow_targets(
        self,
        *,
        space_id: UUID,
        limit: int,
        offset: int,
    ) -> FlowRunRetentionFlowTargetPage:
        require_retention_view(self.user)
        return await self.repository.list_flow_targets(
            tenant_id=self.user.tenant_id,
            space_id=space_id,
            limit=limit,
            offset=offset,
        )

    async def replace_organization(
        self,
        *,
        policy: FlowRunRetentionPolicy | None,
        reason: str | None = None,
    ) -> FlowRunRetentionPolicySettings:
        require_retention_manage(self.user)
        self._require_writable(policy)
        change = await self.repository.replace_organization(
            tenant_id=self.user.tenant_id,
            policy=policy,
        )
        await self._audit_change(change, reason=reason)
        return change.after

    async def get_space(self, *, space_id: UUID) -> FlowRunRetentionPolicySettings:
        require_retention_view(self.user)
        return await self.repository.get_space(
            tenant_id=self.user.tenant_id,
            space_id=space_id,
        )

    async def replace_space(
        self,
        *,
        space_id: UUID,
        policy: FlowRunRetentionPolicy | None,
        reason: str | None = None,
    ) -> FlowRunRetentionPolicySettings:
        require_retention_manage(self.user)
        self._require_writable(policy)
        change = await self.repository.replace_space(
            tenant_id=self.user.tenant_id,
            space_id=space_id,
            policy=policy,
        )
        await self._audit_change(change, reason=reason)
        return change.after

    async def get_flow(self, *, flow_id: UUID) -> FlowRunRetentionPolicySettings:
        require_retention_view(self.user)
        return await self.repository.get_flow(
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
        )

    async def replace_flow(
        self,
        *,
        flow_id: UUID,
        policy: FlowRunRetentionPolicy | None,
        reason: str | None = None,
    ) -> FlowRunRetentionPolicySettings:
        require_retention_manage(self.user)
        self._require_writable(policy)
        change = await self.repository.replace_flow(
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
            policy=policy,
        )
        await self._audit_change(change, reason=reason)
        return change.after

    async def list_organization_review_queue(
        self,
        *,
        limit: int,
        cursor: FlowRunRetentionReviewCursor | None,
    ) -> FlowRunRetentionReviewPage:
        require_retention_manage(self.user)
        return await self.repository.list_review_queue(
            tenant_id=self.user.tenant_id,
            now=datetime.now(timezone.utc),
            limit=limit,
            cursor=cursor,
        )

    async def list_space_review_queue(
        self,
        *,
        space_id: UUID,
        limit: int,
        cursor: FlowRunRetentionReviewCursor | None,
    ) -> FlowRunRetentionReviewPage:
        require_retention_manage(self.user)
        await self.repository.get_space(
            tenant_id=self.user.tenant_id,
            space_id=space_id,
        )
        return await self.repository.list_review_queue(
            tenant_id=self.user.tenant_id,
            now=datetime.now(timezone.utc),
            limit=limit,
            cursor=cursor,
            space_id=space_id,
        )

    async def list_flow_review_queue(
        self,
        *,
        flow_id: UUID,
        limit: int,
        cursor: FlowRunRetentionReviewCursor | None,
    ) -> FlowRunRetentionReviewPage:
        require_retention_manage(self.user)
        await self.repository.get_flow(
            tenant_id=self.user.tenant_id,
            flow_id=flow_id,
        )
        return await self.repository.list_review_queue(
            tenant_id=self.user.tenant_id,
            now=datetime.now(timezone.utc),
            limit=limit,
            cursor=cursor,
            flow_id=flow_id,
        )

    async def purge_due_history(
        self,
        *,
        dry_run: bool,
        limit: int,
        space_id: UUID | None = None,
        flow_id: UUID | None = None,
    ) -> FlowRunHistoryPurgePublic:
        require_retention_manage(self.user)
        settings_ = get_settings()
        session = self.repository.session
        async with retention_request_sql_limits(
            session,
            statement_timeout_ms=settings_.gallring_chunk_statement_timeout_ms,
            lock_timeout_ms=settings_.gallring_chunk_lock_timeout_ms,
        ):
            if flow_id is not None:
                settings = await self.repository.get_flow(
                    tenant_id=self.user.tenant_id, flow_id=flow_id
                )
            elif space_id is not None:
                settings = await self.repository.get_space(
                    tenant_id=self.user.tenant_id, space_id=space_id
                )
            else:
                settings = await self.repository.get_organization(
                    tenant_id=self.user.tenant_id
                )
            now = datetime.now(timezone.utc)
            purge = FlowRunHistoryExplicitPurge(session)
            scope = PurgeScope(
                tenant_id=self.user.tenant_id, space_id=space_id, flow_id=flow_id
            )
            blocked = await purge.blocked(scope, now=now)
            result = await purge.run(
                scope,
                now=now,
                limit=limit,
                dry_run=dry_run,
                triggered_by_user_id=self.user.id,
                max_rows=settings_.gallring_max_rows_per_run,
                max_files=settings_.gallring_max_files_per_run,
            )
            transcripts = await LiveTranscriptRepository(
                session
            ).delete_expired_unbound(
                tenant_id=self.user.tenant_id,
                now=now,
                limit=limit,
                dry_run=dry_run,
                space_id=space_id,
                flow_id=flow_id,
            )
            response = FlowRunHistoryPurgePublic(
                dry_run=dry_run,
                scope=settings.scope,
                candidate_count=result.candidate_count,
                selection_complete=result.selection_complete,
                purged_count=len(result.purged_run_ids),
                purged_run_ids=list(result.purged_run_ids),
                pending_count=len(result.pending_receipt_ids),
                pending_receipt_ids=list(result.pending_receipt_ids),
                transcript_candidate_count=transcripts.candidate_count,
                transcript_purged_count=transcripts.purged_count,
                blocked=FlowRunHistoryPurgeBlockedPublic(
                    undelivered_audit=blocked.undelivered_audit,
                    unresolved_webhook=blocked.unresolved_webhook,
                    review_required=blocked.review_required,
                    legal_hold=blocked.legal_hold,
                    counted_runs=blocked.counted_runs,
                    complete=blocked.complete,
                ),
            )
            if not dry_run:
                await self.audit_service.log(
                    tenant_id=self.user.tenant_id,
                    user=self.user,
                    action=ActionType.FLOW_RUN_HISTORY_PURGED,
                    entity_type=self._entity_type(settings.scope),
                    entity_id=settings.scope_id,
                    description="Purged due Flow run history and expired unbound live transcripts.",
                    metadata={
                        "scope": settings.scope.value,
                        "scope_id": str(settings.scope_id),
                        "tenant_id": str(self.user.tenant_id),
                        "space_id": str(space_id) if space_id is not None else None,
                        "flow_id": str(flow_id) if flow_id is not None else None,
                        "limit": limit,
                        "selection_complete": response.selection_complete,
                        "purged_count": response.purged_count,
                        "purged_run_ids": [
                            str(run_id) for run_id in result.purged_run_ids
                        ],
                        "pending_receipt_ids": [
                            str(receipt_id) for receipt_id in result.pending_receipt_ids
                        ],
                        "retention_effects": [
                            {
                                "counts": effect.counts,
                                "receipt_ids": [
                                    str(receipt_id) for receipt_id in effect.receipt_ids
                                ],
                            }
                            for effect in result.effects
                        ],
                        "retention_blocked": result.blocked,
                        "transcript_candidate_count": response.transcript_candidate_count,
                        "transcript_purged_count": response.transcript_purged_count,
                        "blocked": response.blocked.model_dump(),
                    },
                    required=True,
                )
            return response

    def _require_writable(self, policy: FlowRunRetentionPolicy | None) -> None:
        """The deployment's write limits, checked on the requested local policy
        before anything is written."""
        if policy is None:
            return
        rules = self.repository.write_rules
        if (
            policy.mode is FlowRunRetentionMode.AUTO_DELETE
            and not rules.auto_delete_available
        ):
            raise BadRequestException(
                "Automatic deletion is not available in this deployment yet.",
                code=FLOW_RETENTION_AUTO_DELETE_UNAVAILABLE_CODE,
            )
        if policy.days > rules.max_days:
            raise BadRequestException(
                f"A retention policy may keep run history at most {rules.max_days} "
                "days.",
                code=FLOW_RETENTION_DAYS_ABOVE_MAXIMUM_CODE,
            )

    async def _audit_change(
        self, change: FlowRunRetentionPolicyChange, *, reason: str | None
    ) -> None:
        """The required record of a change, from the locked before-state.

        A change that stops or delays automatic deletion at this level needs a
        reason; the exception rolls the change back with the request.
        """
        if not change.changed:
            return
        after = change.after
        previous_effective = effective_flow_run_retention_policy(
            change.before.effective
        )
        effective_policy = effective_flow_run_retention_policy(after.effective)
        if reason is None and flow_run_retention_change_postpones_deletion(
            before=previous_effective, after=effective_policy
        ):
            raise BadRequestException(
                "Give a reason for stopping or delaying automatic deletion.",
                code=FLOW_RETENTION_REASON_REQUIRED_CODE,
            )
        await self.audit_service.log(
            tenant_id=self.user.tenant_id,
            user=self.user,
            action=ActionType.FLOW_RUN_RETENTION_POLICY_CHANGED,
            entity_type=self._entity_type(after.scope),
            entity_id=after.scope_id,
            description="Changed Flow run-history retention policy.",
            metadata={
                "scope": after.scope.value,
                "scope_id": str(after.scope_id),
                "previous_local_policy": self._audit_policy(change.before.local_policy),
                "new_local_policy": self._audit_policy(after.local_policy),
                "previous_effective_policy": self._audit_policy(previous_effective),
                "effective_policy": self._audit_policy(effective_policy),
                "effective_source": after.effective.source,
                "reason": reason,
            },
            required=True,
        )

    async def get_deletion_status(self) -> FlowRunHistoryDeletionStatus:
        """A bounded status observation, or an explicit unavailable failure."""
        require_retention_view(self.user)
        session = self.repository.session
        try:
            async with session.begin_nested():
                previous_timeout = await session.scalar(
                    sa.select(sa.func.current_setting("statement_timeout"))
                )
                await session.scalar(
                    sa.select(
                        sa.func.set_config(
                            "statement_timeout",
                            f"{get_settings().gallring_chunk_statement_timeout_ms}ms",
                            True,
                        )
                    )
                )
                # Imported here: the task registry imports flows application modules.
                from eneo.data_retention.infrastructure.retention_tasks import (
                    RETENTION_TASKS,
                )

                settings = get_settings()
                job_runs = RetentionJobRunRepository(session)
                due = FlowRunHistoryDueRepository(session)
                now = datetime.now(timezone.utc)
                stale_before = now - RETENTION_STALE_AFTER
                tasks: list[RetentionTaskStatus] = []
                for registration in RETENTION_TASKS:
                    latest = await job_runs.latest(registration.name)
                    tasks.append(
                        RetentionTaskStatus(
                            name=registration.name,
                            enabled=registration.enabled(settings),
                            stale=registration.enabled(settings)
                            and await job_runs.is_stale(
                                registration.name, stale_before=stale_before
                            ),
                            last_completed_at=await job_runs.last_completed_at(
                                registration.name
                            ),
                            last_execution=(
                                RetentionExecutionStatus(
                                    outcome=latest.outcome,
                                    started_at=latest.started_at,
                                    finished_at=latest.finished_at,
                                    counts=latest.counts,
                                    blocked=latest.blocked,
                                    error_code=latest.error_code,
                                )
                                if latest is not None
                                else None
                            ),
                        )
                    )
                overdue = await due.overdue(
                    now=now,
                    window=timedelta(days=settings.gallring_overdue_window_days),
                    cap=settings.retention_overdue_max_rows,
                    tenant_id=self.user.tenant_id,
                )
                receipts = await due.receipts()
                result = FlowRunHistoryDeletionStatus(
                    auto_delete_available=self.repository.write_rules.auto_delete_available,
                    overdue_window_days=settings.gallring_overdue_window_days,
                    tasks=tasks,
                    overdue=FlowRunHistoryOverdueStatus(
                        count=overdue.count,
                        complete=overdue.complete,
                        oldest_due_at=overdue.oldest_due_at,
                        undelivered_audit=overdue.undelivered_audit,
                        unresolved_webhook=overdue.unresolved_webhook,
                        not_yet_deleted=overdue.not_yet_deleted,
                        held=overdue.held,
                    ),
                    receipts=FlowRunHistoryReceiptStatus(
                        unfinished=receipts.unfinished,
                        oldest_unfinished_started_at=receipts.oldest_unfinished_started_at,
                        oldest_physical_pending_completed_at=(
                            receipts.oldest_physical_pending_completed_at
                        ),
                    ),
                )

                await session.scalar(
                    sa.select(
                        sa.func.set_config("statement_timeout", previous_timeout, True)
                    )
                )
                return result
        except DBAPIError as error:
            if not is_retention_timeout(error):
                raise
            raise FlowRetentionStatusUnavailableError() from error

    async def get_hold_review_limit(self) -> FlowRetentionHoldReviewLimit:
        require_retention_view(self.user)
        return await self.repository.get_hold_review_limit(
            tenant_id=self.user.tenant_id
        )

    async def replace_hold_review_limit(
        self, *, days: int | None
    ) -> FlowRetentionHoldReviewLimit:
        """The guardrail on legal holds belongs to the people who own the rules."""
        require_retention_manage(self.user)
        before, after = await self.repository.replace_hold_review_limit(
            tenant_id=self.user.tenant_id, days=days
        )
        if before != after:
            await self.audit_service.log(
                tenant_id=self.user.tenant_id,
                user=self.user,
                action=ActionType.FLOW_RUN_RETENTION_POLICY_CHANGED,
                entity_type=EntityType.TENANT_SETTINGS,
                entity_id=self.user.tenant_id,
                description="Changed the review limit for legal holds on Flow run history.",
                metadata={
                    "scope": FlowRunRetentionScope.ORGANIZATION.value,
                    "scope_id": str(self.user.tenant_id),
                    "setting": "hold_review_limit_days",
                    "previous_value": before.days,
                    "new_value": after.days,
                },
                required=True,
            )
        return after

    @staticmethod
    def _audit_policy(
        policy: FlowRunRetentionPolicy | None,
    ) -> dict[str, str | int] | None:
        if policy is None:
            return None
        return {"mode": policy.mode.value, "days": policy.days}

    @staticmethod
    def _entity_type(scope: FlowRunRetentionScope) -> EntityType:
        if scope is FlowRunRetentionScope.ORGANIZATION:
            return EntityType.TENANT_SETTINGS
        if scope is FlowRunRetentionScope.SPACE:
            return EntityType.SPACE
        return EntityType.FLOW
